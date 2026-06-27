"""User watchlist API — per-account stock watchlist with metadata.

Endpoints:
  GET    /api/watchlist/           → current user's watchlist
  POST   /api/watchlist/           → add stock to watchlist
  DELETE /api/watchlist/{code}     → remove stock from watchlist
  GET    /api/watchlist/overview   → enriched watchlist (realtime quotes)
  PUT    /api/watchlist/{code}/notes → update notes for a stock
  DELETE /api/watchlist/           → clear watchlist

Storage:
  Per-account rows in the ``watchlist`` table of ``data/cache.db`` (SQLite),
  keyed by (user_id, code).  Quotes are sourced from Tencent (qt.gtimg.cn),
  which works behind proxies that hijack EastMoney.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field

from quantforge.api.routes.auth import get_current_user
from quantforge.data.storage import db_cache

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


# ── Schemas ────────────────────────────────────────────────────────────────

class WatchlistItem(BaseModel):
    code: str
    name: str
    added_at: Optional[str] = None
    notes: Optional[str] = ""
    tags: List[str] = Field(default_factory=list)
    color: Optional[str] = ""
    cost_price: Optional[float] = None
    shares: Optional[float] = None


class WatchlistAddRequest(BaseModel):
    code: str
    name: Optional[str] = ""
    notes: Optional[str] = ""
    tags: Optional[List[str]] = None


class WatchlistUpdateNotes(BaseModel):
    notes: str


class WatchlistSetTags(BaseModel):
    tags: List[str] = Field(default_factory=list)


class WatchlistSetColor(BaseModel):
    color: str = ""   # hex (e.g. '#ef4444') 或 '' 清除


class WatchlistSetHolding(BaseModel):
    cost_price: Optional[float] = None
    shares: Optional[float] = None


class WatchlistBatchAdd(BaseModel):
    items: List[WatchlistAddRequest]


class VerificationCreate(BaseModel):
    periodDays: int = 0
    startDate: str = ""
    endDate: str = ""
    totalReturn: float = 0
    results: List[dict] = Field(default_factory=list)


def _verif_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "periodDays": r["period_days"],
        "startDate": r["start_date"],
        "endDate": r["end_date"],
        "totalReturn": r["total_return"],
        "results": r["results"],
        "createdAt": r["created_at"],
    }


# ── Quote enrichment (Tencent — works behind proxy) ──────────────────────────

def _quote_fields(q: dict) -> dict:
    """Map a Tencent quote dict to the overview's quote fields (同花顺式丰富指标)."""
    amt_wan = q.get("amount_wan")
    mcap_yi = q.get("mcap_yi")
    fmcap_yi = q.get("float_mcap_yi")
    return {
        "name":       q.get("name"),
        "price":      q.get("price"),
        "change_pct": q.get("change_pct"),
        "change":     q.get("change_amt"),
        "open":       q.get("open"),
        "high":       q.get("high"),
        "low":        q.get("low"),
        "pre_close":  q.get("last_close"),
        "turnover":   amt_wan * 10000 if amt_wan else None,
        "pe":         q.get("pe_ttm"),
        "pb":         q.get("pb"),
        "turnover_rate":    q.get("turnover_pct"),
        "amplitude":        q.get("amplitude_pct"),     # 振幅 %
        "vol_ratio":        q.get("vol_ratio"),         # 量比
        "market_cap":       mcap_yi * 1e8 if mcap_yi else None,    # 总市值 (元)
        "float_market_cap": fmcap_yi * 1e8 if fmcap_yi else None,  # 流通市值 (元)
        "limit_up":         q.get("limit_up"),          # 涨停价
        "limit_down":       q.get("limit_down"),        # 跌停价
    }


# Tiny in-process quote cache: dedupes Tencent calls across users / rapid
# refreshes.  Per-code so different watchlists share entries.
_quote_cache: dict[str, tuple[float, dict]] = {}
_QUOTE_TTL = 15.0  # seconds


async def _fetch_quotes(codes: List[str]) -> dict:
    if not codes:
        return {}
    now = time.time()
    fresh = {c: v for c in codes
             for ts, v in [_quote_cache.get(c, (0, None))] if v and now - ts <= _QUOTE_TTL}
    missing = [c for c in codes if c not in fresh]
    if missing:
        try:
            from quantforge.data.feed import datasource
            raw = await asyncio.to_thread(datasource.quotes, missing)
            for code, q in raw.items():
                fields = _quote_fields(q)
                _quote_cache[code] = (now, fields)
                fresh[code] = fields
        except Exception as e:
            logger.debug(f"watchlist quote fetch failed: {e}")
    return {c: fresh[c] for c in codes if c in fresh}


async def _resolve_name(code: str) -> str:
    """Best-effort stock name: stock_meta cache → Tencent quote."""
    try:
        meta = db_cache.get_stock(code)
        if meta and meta.get("name"):
            return meta["name"]
    except Exception:
        pass
    q = (await _fetch_quotes([code])).get(code) or {}
    return q.get("name") or ""


# ── One-time migration from legacy data/watchlists/{user}.json ───────────────

_LEGACY_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "watchlists"


def _migrate_legacy(user_id: str) -> None:
    """Best-effort import of a user's old JSON watchlist into the DB (once)."""
    f = _LEGACY_DIR / f"{user_id}.json"
    if not f.exists():
        return
    if db_cache.get_watchlist(user_id):
        return  # already has DB rows — don't clobber
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return
    migrated = 0
    for it in data.get("items", []):
        code = (it.get("code") or "").strip().upper()
        if not code:
            continue
        if db_cache.watchlist_add(
            user_id, code, it.get("name", ""), it.get("notes", ""), it.get("tags") or []
        ):
            migrated += 1
    if migrated:
        logger.info(f"watchlist: migrated {migrated} legacy items for user {user_id}")
        try:
            f.rename(f.with_suffix(".json.migrated"))
        except Exception:
            pass


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[WatchlistItem])
async def get_watchlist(current_user: dict = Depends(get_current_user)):
    """Return the current user's watchlist (basic info — no quotes)."""
    uid = current_user["id"]
    _migrate_legacy(uid)
    return db_cache.get_watchlist(uid)


_QUOTE_OVERVIEW_FIELDS = (
    "name", "price", "change_pct", "change", "high", "low", "pre_close",
    "turnover", "pe", "pb", "turnover_rate",
)


@router.get("/overview")
async def get_watchlist_overview(current_user: dict = Depends(get_current_user)):
    """Return the watchlist enriched with latest market quotes (丰富指标).

    The watchlist is small, so we fetch **live** (rich) quotes for all codes in
    one batched Tencent request (15s in-process cached) — that gives 量比/振幅/
    市值/流通市值 etc. that the whole-market snapshot doesn't store.  Any code the
    live fetch misses falls back to the durable ``stock_quote`` snapshot, so the
    page still renders when upstream is briefly down.
    """
    uid = current_user["id"]
    _migrate_legacy(uid)
    items = db_cache.get_watchlist(uid)
    codes = [it["code"] for it in items]

    quote_map = await _fetch_quotes(codes)
    missing = [c for c in codes if c not in quote_map]
    if missing:
        snap = db_cache.quote_get_many(missing)
        for c, row in snap.items():
            quote_map[c] = {k: row.get(k) for k in _QUOTE_OVERVIEW_FIELDS}

    # 研报徽标：从本地库读篇数/最新日期（后台 warmer 已预热，纯 SQL，秒回）。
    reps = db_cache.reports_summary_many(codes)

    enriched = [{**it, **(quote_map.get(it["code"]) or {}),
                 "reports": reps.get(it["code"])} for it in items]
    return {"items": enriched, "count": len(enriched), "updated_at": datetime.utcnow().isoformat(timespec="seconds")}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    req: WatchlistAddRequest,
    current_user: dict = Depends(get_current_user),
):
    """Add a stock to the user's watchlist (idempotent on code)."""
    code = req.code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="股票代码不能为空")

    uid = current_user["id"]
    existing = db_cache.watchlist_get_item(uid, code)
    if existing is not None:
        return {"status": "exists", "item": existing}

    name = req.name or await _resolve_name(code)
    item = db_cache.watchlist_add(uid, code, name, req.notes or "", req.tags or [])
    if item is None:
        # Race: inserted between check and add
        return {"status": "exists", "item": db_cache.watchlist_get_item(uid, code)}
    count = len(db_cache.get_watchlist(uid))
    return {"status": "added", "item": item, "count": count}


@router.delete("/{code}")
async def remove_from_watchlist(
    code: str,
    current_user: dict = Depends(get_current_user),
):
    """Remove a stock from the user's watchlist by code."""
    code = code.strip().upper()
    if not db_cache.watchlist_remove(current_user["id"], code):
        raise HTTPException(status_code=404, detail="自选股中未找到该股票")
    count = len(db_cache.get_watchlist(current_user["id"]))
    return {"status": "removed", "code": code, "count": count}


@router.put("/{code}/notes")
async def update_notes(
    code: str,
    req: WatchlistUpdateNotes,
    current_user: dict = Depends(get_current_user),
):
    """Update the user's personal notes for a specific stock."""
    code = code.strip().upper()
    item = db_cache.watchlist_update_notes(current_user["id"], code, req.notes or "")
    if item is None:
        raise HTTPException(status_code=404, detail="自选股中未找到该股票")
    return {"status": "updated", "item": item}


@router.get("/tags")
async def list_tags(current_user: dict = Depends(get_current_user)):
    """Distinct tags across the user's watchlist with usage counts."""
    return db_cache.watchlist_tags(current_user["id"])


@router.put("/{code}/tags")
async def set_tags(
    code: str,
    req: WatchlistSetTags,
    current_user: dict = Depends(get_current_user),
):
    """Replace the tag list for a watchlist stock."""
    code = code.strip().upper()
    tags = [t.strip() for t in (req.tags or []) if t.strip()]
    item = db_cache.watchlist_set_tags(current_user["id"], code, tags)
    if item is None:
        raise HTTPException(status_code=404, detail="自选股中未找到该股票")
    return {"status": "updated", "item": item}


@router.put("/{code}/color")
async def set_color(
    code: str,
    req: WatchlistSetColor,
    current_user: dict = Depends(get_current_user),
):
    """Set (or clear) a single stock's marker color."""
    code = code.strip().upper()
    item = db_cache.watchlist_set_color(current_user["id"], code, (req.color or "").strip())
    if item is None:
        raise HTTPException(status_code=404, detail="自选股中未找到该股票")
    return {"status": "updated", "item": item}


@router.put("/{code}/holding")
async def set_holding(
    code: str,
    req: WatchlistSetHolding,
    current_user: dict = Depends(get_current_user),
):
    """Set (or clear) a stock's holding cost price & share count.

    Passing both ``cost_price`` and ``shares`` as null clears the holding.
    """
    code = code.strip().upper()
    cost = req.cost_price if (req.cost_price is not None and req.cost_price > 0) else None
    shares = req.shares if (req.shares is not None and req.shares > 0) else None
    # 只有成本与股数都给齐才算持仓，否则清空（避免半截脏数据）
    if cost is None or shares is None:
        cost, shares = None, None
    item = db_cache.watchlist_set_holding(current_user["id"], code, cost, shares)
    if item is None:
        raise HTTPException(status_code=404, detail="自选股中未找到该股票")
    return {"status": "updated", "item": item}


@router.post("/batch", status_code=status.HTTP_201_CREATED)
async def batch_add(
    req: WatchlistBatchAdd,
    current_user: dict = Depends(get_current_user),
):
    """Add many stocks at once. Names auto-resolved (one quote call) when missing."""
    uid = current_user["id"]
    need = [i.code.strip().upper() for i in req.items if not (i.name or "").strip()]
    qmap = await _fetch_quotes(need) if need else {}

    added, skipped = [], []
    for i in req.items:
        code = i.code.strip().upper()
        if not code or db_cache.watchlist_get_item(uid, code):
            if code:
                skipped.append(code)
            continue
        name = i.name or (qmap.get(code) or {}).get("name") or ""
        item = db_cache.watchlist_add(uid, code, name, i.notes or "", i.tags or [])
        (added if item else skipped).append(item or code)
    return {
        "status": "ok",
        "added": added,
        "added_count": len(added),
        "skipped": skipped,
        "count": len(db_cache.get_watchlist(uid)),
    }


@router.delete("/")
async def clear_watchlist(current_user: dict = Depends(get_current_user)):
    """Remove all stocks from the user's watchlist."""
    n = db_cache.watchlist_clear(current_user["id"])
    return {"status": "cleared", "count": n}


# ── AI 诊股评分（批量一次 LLM，按 code 落库缓存）──────────────────────────────

class AiDiagnoseRequest(BaseModel):
    codes: List[str] = Field(default_factory=list)
    force: bool = False


_AIDIAG_TTL = 6 * 3600   # 6h；盘中软信号，过期或 force 才重算


def _aidiag_key(code: str) -> str:
    return f"wl:aidiag:{code.strip().upper()}"


def _tech_brief(code: str) -> dict:
    """从本地日线提炼技术位摘要(只读 db_cache，自选已预热)。"""
    try:
        bars = db_cache.kline_load(code, "day", 60) or []
    except Exception:
        bars = []
    if len(bars) < 6:
        return {}
    closes = [float(b["close"]) for b in bars if b.get("close") is not None]
    highs = [float(b["high"]) for b in bars if b.get("high") is not None]
    lows = [float(b["low"]) for b in bars if b.get("low") is not None]
    if len(closes) < 6:
        return {}

    def _ma(n):
        return round(sum(closes[-n:]) / min(n, len(closes)), 2)

    def _ret(n):
        return round((closes[-1] / closes[-1 - n] - 1) * 100, 2) if len(closes) > n else None

    out = {"ma5": _ma(5), "ma20": _ma(20), "ma60": _ma(60),
           "ret5": _ret(5), "ret20": _ret(20)}
    w = highs[-20:]; v = lows[-20:]
    if w and v:
        hi, lo, last = max(w), min(v), closes[-1]
        out["pos20"] = round((last - lo) / (hi - lo) * 100, 1) if hi > lo else None
    return out


async def _build_diag_snapshot(codes: List[str]) -> dict:
    """组装诊断输入：现价/涨跌/量比/换手/估值 + 主力净流入 + 技术位。"""
    from quantforge.api.routes.market import fund_flow_map
    qmap = await _fetch_quotes(codes)
    try:
        ffmap = await fund_flow_map(codes)
    except Exception:
        ffmap = {}
    snap = {}
    for c in codes:
        q = qmap.get(c) or {}
        ff = ffmap.get(c) or {}
        tech = await asyncio.to_thread(_tech_brief, c)
        snap[c] = {
            "name": q.get("name") or "",
            "price": q.get("price"), "change_pct": q.get("change_pct"),
            "vol_ratio": q.get("vol_ratio"), "turnover_rate": q.get("turnover_rate"),
            "pe": q.get("pe"), "pb": q.get("pb"),
            "main_net_wan": round(ff["main_net"] / 1e4, 1) if ff.get("main_net") is not None else None,
            "main_pct": ff.get("main_pct"),
            **tech,
        }
    return snap


def _diag_prompt(snap: dict) -> str:
    lines = []
    for code, d in snap.items():
        parts = [f"{d.get('name','')}({code})"]
        if d.get("price") is not None: parts.append(f"现价{d['price']}")
        if d.get("change_pct") is not None: parts.append(f"涨跌{d['change_pct']:+.2f}%")
        if d.get("vol_ratio") is not None: parts.append(f"量比{d['vol_ratio']}")
        if d.get("turnover_rate") is not None: parts.append(f"换手{d['turnover_rate']}%")
        if d.get("pe") is not None: parts.append(f"PE{d['pe']}")
        if d.get("main_net_wan") is not None: parts.append(f"主力净流入{d['main_net_wan']}万")
        if d.get("ret5") is not None: parts.append(f"5日{d['ret5']:+.1f}%")
        if d.get("ret20") is not None: parts.append(f"20日{d['ret20']:+.1f}%")
        if d.get("ma20") is not None: parts.append(f"MA20={d['ma20']}")
        if d.get("pos20") is not None: parts.append(f"20日位置{d['pos20']}%")
        lines.append("- " + " ".join(parts))
    return "\n".join(lines)


@router.post("/ai-diagnose")
async def ai_diagnose(
    req: AiDiagnoseRequest,
    current_user: dict = Depends(get_current_user),
):
    """对自选股做 AI 综合诊断(评分 0-100 + 看多/中性/看空 + 一句点评)。

    一次性把待诊断的股票打包成单个 LLM 请求(省成本)，结果按 code 落库缓存 6h；
    ``force=true`` 强制重算。LLM 失败时返回已缓存部分，其余标记不可用。"""
    codes = [c.strip().upper() for c in (req.codes or []) if c.strip()][:60]
    if not codes:
        return {"data": {}}

    out: dict = {}
    need: List[str] = []
    for c in codes:
        cached = None if req.force else db_cache.get(_aidiag_key(c), _AIDIAG_TTL)
        if cached:
            out[c] = {**cached, "cached": True}
        else:
            need.append(c)

    if need:
        snap = await _build_diag_snapshot(need)
        # 只诊断拿到了行情的(避免对空数据瞎评)
        valid = [c for c in need if (snap.get(c) or {}).get("price") is not None]
        if valid:
            system = (
                "你是资深A股短线分析师。根据每只股票的量价/资金/技术位数据，"
                "给出客观诊断。只输出 JSON 数组，每元素形如 "
                '{"code":"600519","score":72,"rating":"看多","comment":"放量站上20日线,主力流入"}。'
                "score 为 0-100 综合强度分；rating 取 看多/中性/看空 之一；"
                "comment 不超过18字，点出核心理由。不要输出 JSON 以外任何内容。"
            )
            user = "股票数据如下：\n" + _diag_prompt({c: snap[c] for c in valid})
            try:
                from quantforge.api.ai_client import chat
                from quantforge.api.routes.research import _loads_lenient
                raw = await chat(system, user, max_tokens=2048,
                                 caller="wl_ai_diagnose",
                                 account=current_user.get("username"))
                parsed = _loads_lenient(raw)
                rows = parsed if isinstance(parsed, list) else parsed.get("data") or parsed.get("items") or []
                by_code = {str(r.get("code", "")).upper(): r for r in rows if isinstance(r, dict)}
                asof = datetime.utcnow().isoformat(timespec="seconds")
                for c in valid:
                    r = by_code.get(c) or by_code.get(_em6(c))
                    if not r:
                        continue
                    rec = {
                        "score": _clamp_score(r.get("score")),
                        "rating": str(r.get("rating") or "中性")[:6],
                        "comment": str(r.get("comment") or "")[:40],
                        "asof": asof,
                    }
                    db_cache.set(_aidiag_key(c), rec, _AIDIAG_TTL, "wl_ai_diag")
                    out[c] = {**rec, "cached": False}
            except Exception as e:
                logger.warning(f"wl ai-diagnose failed: {e}")

    return {"data": out, "count": len(out)}


# ── AI 一键分组 / 标色 ────────────────────────────────────────────────────────

class AiGroupRequest(BaseModel):
    codes: List[str] = Field(default_factory=list)
    force: bool = False


_AIGROUP_TTL = 2 * 3600   # 2h；分组建议偏好较稳定，但比诊断快照要短


def _aigroup_key(uid: str) -> str:
    return f"wl:aigroup:{uid}"


# 颜色语义说明（让 LLM 理解各颜色含义，做出合理映射）
_COLOR_HINTS = (
    "#ef4444=红(重点关注/强势突破), "
    "#f97316=橙(次重点/短线机会), "
    "#eab308=黄(观察/等待确认), "
    "#22c55e=绿(价值/持有), "
    "#3b82f6=蓝(科技/成长), "
    "#a855f7=紫(主题/特殊行情), "
    "#94a3b8=灰(暂时观望/弱势)"
)


def _group_prompt(snap: dict) -> str:
    lines = []
    for code, d in snap.items():
        parts = [f"{d.get('name','')}({code})"]
        if d.get("price") is not None:      parts.append(f"现价{d['price']}")
        if d.get("change_pct") is not None:  parts.append(f"涨跌{d['change_pct']:+.2f}%")
        if d.get("vol_ratio") is not None:   parts.append(f"量比{d['vol_ratio']}")
        if d.get("turnover_rate") is not None: parts.append(f"换手{d['turnover_rate']}%")
        if d.get("pe") is not None:          parts.append(f"PE{d['pe']}")
        if d.get("main_net_wan") is not None: parts.append(f"主力净{d['main_net_wan']}万")
        if d.get("ret5") is not None:        parts.append(f"5日{d['ret5']:+.1f}%")
        if d.get("ret20") is not None:       parts.append(f"20日{d['ret20']:+.1f}%")
        if d.get("pos20") is not None:       parts.append(f"20日位置{d['pos20']}%")
        lines.append("- " + " ".join(parts))
    return "\n".join(lines)


@router.post("/ai-group")
async def ai_group(
    req: AiGroupRequest,
    current_user: dict = Depends(get_current_user),
):
    """AI 一键分组 & 标色：分析自选股量价/资金/技术位，给出分组建议和颜色标记。

    每次以用户维度整体缓存 2h（force=true 跳过缓存）。
    返回格式: { data: { code: {group, color, reason} }, groups: ["分组A",...] }
    """
    uid = current_user["id"]
    codes = [c.strip().upper() for c in (req.codes or []) if c.strip()][:60]
    if not codes:
        return {"data": {}, "groups": []}

    cache_key = _aigroup_key(uid)
    if not req.force:
        cached = db_cache.get(cache_key, _AIGROUP_TTL)
        if cached and isinstance(cached, dict):
            # 过滤出本次请求的 codes（缓存可能包含旧 codes）
            filtered = {c: cached["data"][c] for c in codes if c in cached.get("data", {})}
            if len(filtered) == len(codes):
                return {"data": filtered, "groups": cached.get("groups", []), "cached": True}

    snap = await _build_diag_snapshot(codes)
    valid = [c for c in codes if (snap.get(c) or {}).get("price") is not None]
    if not valid:
        return {"data": {}, "groups": [], "warning": "无法获取行情数据"}

    system = (
        "你是专业A股自选股整理助手。根据用户提供的持仓股量价/资金/技术位数据，"
        "帮助用户将其**自选股**分类整理，并给每只股票推荐一个标记颜色。\n\n"
        "分组要求：\n"
        "- 分 2~5 个语义清晰的组（如「强势突破」「价值持仓」「主题观察」「高风险」「暂时观望」等，按实际情况命名）\n"
        "- 每只股票归属一个最合适的组\n\n"
        "颜色映射参考：" + _COLOR_HINTS + "\n\n"
        "只输出 JSON，格式为数组，每个元素：\n"
        '{"code":"600519","group":"价值持仓","color":"#22c55e","reason":"高PE但现金流稳，主力净流入"}\n'
        "reason 不超过16字。不要输出 JSON 以外任何内容。"
    )
    user = "自选股数据如下：\n" + _group_prompt({c: snap[c] for c in valid})

    try:
        from quantforge.api.ai_client import chat
        from quantforge.api.routes.research import _loads_lenient
        raw = await chat(system, user, max_tokens=2048,
                         caller="wl_ai_group",
                         account=current_user.get("username"))
        parsed = _loads_lenient(raw)
        rows = parsed if isinstance(parsed, list) else parsed.get("data") or parsed.get("items") or []
        by_code: dict = {}
        groups_set: list = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            code = str(r.get("code", "")).strip().upper()
            code = _em6(code) if not code[2:3].isdigit() else code  # normalize
            # 匹配原始 code（带交易所前缀的如 SH600519 也做纯数字匹配）
            matched = code if code in valid else next(
                (c for c in valid if c == code or _em6(c) == code), None)
            if not matched:
                continue
            group = str(r.get("group") or "其他")[:20].strip()
            color = str(r.get("color") or "").strip()
            # 只允许预设色板中的颜色，防止 LLM 输出随机值
            allowed = {"#ef4444","#f97316","#eab308","#22c55e","#3b82f6","#a855f7","#94a3b8"}
            if color not in allowed:
                color = ""
            by_code[matched] = {
                "group": group,
                "color": color,
                "reason": str(r.get("reason") or "")[:40],
            }
            if group and group not in groups_set:
                groups_set.append(group)

        result = {"data": by_code, "groups": groups_set}
        db_cache.set(cache_key, result, _AIGROUP_TTL, "wl_ai_group")
        return {**result, "cached": False}
    except Exception as e:
        logger.warning(f"wl ai-group failed: {e}")
        return {"data": {}, "groups": [], "error": str(e)}


def _em6(code: str) -> str:
    c = code.strip().upper()
    for p in ("SH", "SZ", "BJ"):
        if c.startswith(p):
            return c[2:]
    return c


def _clamp_score(v) -> Optional[int]:
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return None


# ── Verification records (per-account) ───────────────────────────────────────

@router.get("/verifications")
async def list_verifications(current_user: dict = Depends(get_current_user)):
    """List the current user's saved watchlist-verification snapshots."""
    rows = db_cache.get_watch_verifications(current_user["id"])
    return [_verif_out(r) for r in rows]


@router.post("/verifications", status_code=status.HTTP_201_CREATED)
async def create_verification(
    req: VerificationCreate,
    current_user: dict = Depends(get_current_user),
):
    """Persist a verification snapshot (computed client-side) for this account."""
    saved = db_cache.add_watch_verification(
        current_user["id"], req.periodDays, req.startDate, req.endDate,
        req.totalReturn, req.results,
    )
    if saved is None:
        raise HTTPException(status_code=500, detail="保存验证记录失败")
    return _verif_out(saved)


@router.delete("/verifications/{vid}")
async def delete_verification(
    vid: int,
    current_user: dict = Depends(get_current_user),
):
    """Delete one verification snapshot by id."""
    if not db_cache.delete_watch_verification(current_user["id"], vid):
        raise HTTPException(status_code=404, detail="未找到该验证记录")
    return {"status": "removed", "id": vid}
