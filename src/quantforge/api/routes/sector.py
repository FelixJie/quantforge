"""Sector (板块) analysis API routes.

行业板块走新浪 (newSinaHy)，概念板块改用**同花顺指数** (q.10jqka.com.cn，
见 :mod:`quantforge.data.feed.ths_concept`)——新浪概念词条窄且无指数行情。

  - Industry boards/stocks:  新浪 newSinaHy + getHQNodeData (本文件)
  - Concept boards/stocks:   同花顺概念指数 (ths_concept 模块)
  - Fund flow rank:          akshare ak.stock_sector_fund_flow_rank

Column mapping uses positional indexing to avoid GBK/UTF-8 encoding issues.
"""

from __future__ import annotations

import asyncio
import json
import math
import datetime as _dt
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from quantforge.data.storage import db_cache
from quantforge.data.feed import ths_concept

router = APIRouter(prefix="/sector", tags=["sector"])

_CACHE_DIR = Path("data/cache/sector")
_TTL_BOARDS = 15 * 60   # 15 minutes for board lists
_TTL_STOCKS = 10 * 60   # 10 minutes for constituent stocks
_TTL_FLOW   = 10 * 60   # 10 minutes for fund flow
_TTL_PE     = 20 * 60   # 20 minutes for industry summary


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(key: str) -> Path:
    return _CACHE_DIR / f"{key}.json"


def _load_cache(key: str, ttl: int) -> dict | None:
    f = _cache_path(key)
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        ts = _dt.datetime.fromisoformat(data.get("_cached_at", "2000-01-01"))
        if (_dt.datetime.now() - ts).total_seconds() > ttl:
            return None
        return data
    except Exception:
        return None


def _save_cache(key: str, data: dict):
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data["_cached_at"] = _dt.datetime.now().isoformat()
        _cache_path(key).write_text(
            json.dumps(data, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        logger.debug(f"Sector cache save failed: {e}")


def _load_stale(key: str) -> dict | None:
    """Return stale cache as fallback when live fetch fails."""
    f = _cache_path(key)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    except (TypeError, ValueError):
        return None


def _safe_str(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return str(v).strip()


# ── Board list normaliser ─────────────────────────────────────────────────────
# Positional columns for stock_board_industry_name_em / stock_board_concept_name_em:
# 0=序号, 1=板块名称, 2=板块代码, 3=最新价, 4=涨跌额, 5=涨跌幅,
# 6=总市值, 7=换手率, 8=上涨家数, 9=下跌家数, 10=领涨股票, 11=领涨股票-涨跌幅

def _normalise_boards(df: pd.DataFrame) -> list[dict]:
    result = []
    for _, row in df.iterrows():
        try:
            result.append({
                "name":          _safe_str(row.iloc[1]),
                "change_pct":    _safe_float(row.iloc[5]),
                "market_cap":    _safe_float(row.iloc[6]),
                "turnover_rate": _safe_float(row.iloc[7]),
                "up_count":      int(row.iloc[8]) if pd.notna(row.iloc[8]) else 0,
                "down_count":    int(row.iloc[9]) if pd.notna(row.iloc[9]) else 0,
                "leader":        _safe_str(row.iloc[10]),
                "leader_change": _safe_float(row.iloc[11]),
            })
        except (IndexError, Exception):
            continue
    return result


# Positional columns for stock_board_industry_cons_em / stock_board_concept_cons_em:
# 0=序号, 1=代码, 2=名称, 3=最新价, 4=涨跌额, 5=涨跌幅,
# 6=成交量, 7=成交额, 8=振幅, 9=最高, 10=最低, 11=开盘, 12=收盘,
# 13=换手率, 14=市盈率-动态, 15=市净率

def _normalise_cons(df: pd.DataFrame) -> list[dict]:
    result = []
    for _, row in df.iterrows():
        try:
            result.append({
                "code":          _safe_str(row.iloc[1]),
                "name":          _safe_str(row.iloc[2]),
                "price":         _safe_float(row.iloc[3]),
                "change_pct":    _safe_float(row.iloc[5]),
                "volume":        _safe_float(row.iloc[6]),
                "turnover":      _safe_float(row.iloc[7]),
                "high":          _safe_float(row.iloc[9]),
                "low":           _safe_float(row.iloc[10]),
                "turnover_rate": _safe_float(row.iloc[13]),
                "pe":            _safe_float(row.iloc[14]) if len(row) > 14 else None,
                "pb":            _safe_float(row.iloc[15]) if len(row) > 15 else None,
            })
        except (IndexError, Exception):
            continue
    return result


# Positional columns for stock_sector_fund_flow_rank:
# Varies — use named cols where possible, fallback to position

def _normalise_flow(df: pd.DataFrame) -> list[dict]:
    cols = list(df.columns)
    result = []
    for _, row in df.iterrows():
        try:
            d = {
                "name":       _safe_str(row.iloc[0]),
                "change_pct": _safe_float(row.iloc[1]) if len(row) > 1 else None,
                "net_flow":   _safe_float(row.iloc[2]) if len(row) > 2 else None,
                "net_flow_pct": _safe_float(row.iloc[3]) if len(row) > 3 else None,
                "main_flow":  _safe_float(row.iloc[4]) if len(row) > 4 else None,
            }
            result.append(d)
        except Exception:
            continue
    return result


# ── Sina data source (industry boards) ────────────────────────────────────────
# EastMoney push2 is unreachable behind some proxies (TUN/fake-IP hijack), so
# industry boards are sourced from Sina Finance, which exposes the board list
# plus per-constituent PE/PB/market-cap in one place.

import re as _re
import urllib.request as _urlreq

_SINA_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_SINA_REFERER = "https://finance.sina.com.cn"


def _sina_http(url: str, decode: str = "gbk") -> str:
    req = _urlreq.Request(url, headers={"User-Agent": _SINA_UA, "Referer": _SINA_REFERER})
    return _urlreq.urlopen(req, timeout=12).read().decode(decode, "replace")


def _sina_parse_boards(obj: dict) -> list[dict]:
    """Parse Sina board map → board dicts.

    Each value is CSV: ``node,name,count,avg_price,avg_chg_amt,avg_chg_pct,
    volume,amount,leader_symbol,...,leader_name``.
    """
    boards = []
    for node, line in obj.items():
        parts = str(line).split(",")
        if len(parts) < 13:
            continue
        boards.append({
            "node":       parts[0],
            "name":       parts[1],
            "count":      int(float(parts[2])) if parts[2] else 0,
            "change_pct": _safe_float(parts[5]),
            "amount":     _safe_float(parts[7]),
            "leader":     parts[12],
        })
    return boards


def _sina_board_list(url: str) -> list[dict]:
    raw = _sina_http(url)
    m = _re.search(r"=\s*(\{.*\})", raw, _re.S)
    return _sina_parse_boards(json.loads(m.group(1))) if m else []


def _sina_industry_list() -> list[dict]:
    """新浪行业板块列表 (newSinaHy.php)。"""
    return _sina_board_list("https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php")


def _sina_concept_list() -> list[dict]:
    """新浪概念板块列表 (newFLJK.php?param=class)，node 前缀 gn_。"""
    return _sina_board_list("https://vip.stock.finance.sina.com.cn/q/view/newFLJK.php?param=class")


def _sina_node_stocks(node: str, count: int = 0) -> list[dict]:
    """新浪板块成分股（含 PE/PB/市值），按需翻页。"""
    per = 80
    pages = max(1, (count + per - 1) // per) if count else 1
    stocks = []
    for page in range(1, pages + 1):
        url = (
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"Market_Center.getHQNodeData?page={page}&num={per}&sort=symbol&asc=1"
            f"&node={node}&symbol=&_s_r_a=page"
        )
        try:
            arr = json.loads(_sina_http(url))
        except Exception:
            break
        if not arr:
            break
        for s in arr:
            mcap_wan = _safe_float(s.get("mktcap"))
            stocks.append({
                "code":          _safe_str(s.get("code")),
                "name":          _safe_str(s.get("name")),
                "price":         _safe_float(s.get("trade")),
                "change_pct":    _safe_float(s.get("changepercent")),
                "volume":        _safe_float(s.get("volume")),
                "turnover":      _safe_float(s.get("amount")),
                "high":          _safe_float(s.get("high")),
                "low":           _safe_float(s.get("low")),
                "turnover_rate": _safe_float(s.get("turnoverratio")),
                "pe":            _safe_float(s.get("per")),
                "pb":            _safe_float(s.get("pb")),
                "market_cap":    round(mcap_wan * 10000, 2) if mcap_wan else None,  # 万元→元
            })
        if len(arr) < per:
            break
    return stocks


async def _sina_boards_cached() -> list[dict]:
    ck = "sector:sina_industry_list"
    cached = db_cache.get(ck, _TTL_BOARDS)
    if cached:
        return cached.get("boards", [])
    boards = await asyncio.to_thread(_sina_industry_list)
    if boards:
        db_cache.set(ck, {"boards": boards}, _TTL_BOARDS, category="sector")
    return boards


async def _sina_concept_boards_cached() -> list[dict]:
    ck = "sector:sina_concept_list"
    cached = db_cache.get(ck, _TTL_BOARDS)
    if cached:
        return cached.get("boards", [])
    boards = await asyncio.to_thread(_sina_concept_list)
    if boards:
        db_cache.set(ck, {"boards": boards}, _TTL_BOARDS, category="sector")
    return boards


# ── Industry endpoints ────────────────────────────────────────────────────────

@router.get("/industry")
async def get_industry_boards():
    """All A-share industry boards (Sina) with board-level stats."""
    try:
        boards = await _sina_boards_cached()
        if not boards:
            raise RuntimeError("空列表")
        return {"boards": boards, "count": len(boards), "type": "industry"}
    except Exception as e:
        logger.warning(f"Industry boards fetch failed: {e}")
        raise HTTPException(status_code=503, detail=f"行业板块数据获取失败: {e}")


@router.get("/industry/{name}")
async def get_industry_stocks(name: str):
    """Constituent stocks for a specific industry board (Sina, stored in DB)."""
    return await _drill_down("industry", name, _sina_boards_cached, "行业板块")


# ── Concept endpoints (同花顺指数) ─────────────────────────────────────────────
# 概念板块取自同花顺概念指数 (ths_concept)；DB(sector_boards/sector_constituents,
# kind="concept") 作新鲜缓存 + 数据源不可达时的陈旧回退。

async def _ths_concept_boards() -> list[dict] | None:
    """概念板块快照。**用户请求永远只读落库快照，绝不内联抓取**——抓取(373 详情页)
    统一交给后台预热器 `sector_summary_warmer`，避免用户流量在缓存过期后各自触发
    373 次详情页请求、反复撞同花顺限频。仅在「从未落过库」(冷启动)时做一次性兜底抓取。"""
    boards = db_cache.get_sector_boards("concept")
    if boards:
        return boards
    # 冷启动且无任何快照：一次性兜底抓取（含 60% 残缺护栏）。
    fresh = await asyncio.to_thread(ths_concept.concept_boards)
    if fresh:
        db_cache.replace_sector_boards("concept", fresh)
    return fresh or []


def cached_concept_boards() -> list[dict]:
    """已落库的同花顺概念板块（不触发抓取，可能陈旧/为空）。

    供首页榜单 / 聊天上下文等轻量场景复用概念页预热的指数数据，
    为空时调用方自行回退到新浪概念列表。"""
    return db_cache.get_sector_boards("concept") or []


@router.get("/concept")
async def get_concept_boards():
    """All A-share concept boards (同花顺指数). market_cap proxied by turnover so
    the treemap still renders (概念无板块市值)。"""
    boards = await _ths_concept_boards()
    if not boards:
        raise HTTPException(status_code=503, detail="概念板块数据获取失败（同花顺源不可达）")
    return {"boards": boards, "count": len(boards), "type": "concept"}


@router.get("/concept/{name}")
async def get_concept_stocks(name: str):
    """Constituent stocks for a specific concept board (同花顺, stored in DB)."""
    if db_cache.sector_constituents_fresh("concept", name, _TTL_STOCKS):
        stocks = db_cache.get_sector_constituents("concept", name) or []
        return {"board": name, "stocks": stocks, "count": len(stocks)}
    try:
        stocks = await asyncio.to_thread(ths_concept.concept_stocks, name)
    except Exception as e:
        logger.warning(f"THS concept cons fetch failed for {name}: {e}")
        stocks = None
    if stocks:
        db_cache.replace_sector_constituents("concept", name, stocks)
        return {"board": name, "stocks": stocks, "count": len(stocks)}
    stale = db_cache.get_sector_constituents("concept", name)
    if stale:
        return {"board": name, "stocks": stale, "count": len(stale)}
    raise HTTPException(status_code=503, detail=f"概念板块成分股获取失败: {name}")


# ── Fund flow endpoint ────────────────────────────────────────────────────────

@router.get("/fund-flow")
async def get_fund_flow(indicator: str = Query("今日", enum=["今日", "5日", "10日"])):
    """Industry fund flow ranking (net inflow/outflow)."""
    ck = f"fund_flow_{indicator}"
    cached = _load_cache(ck, _TTL_FLOW)
    if cached:
        return cached

    try:
        import akshare as ak
        df = await asyncio.to_thread(
            ak.stock_sector_fund_flow_rank,
            indicator=indicator,
            sector_type="行业资金流",
        )
        boards = _normalise_flow(df)
        # Sort by net_flow desc
        boards.sort(key=lambda x: x.get("net_flow") or 0, reverse=True)
        for i, b in enumerate(boards):
            b["rank"] = i + 1
        result = {"indicator": indicator, "boards": boards, "count": len(boards)}
        _save_cache(ck, result)
        return result
    except Exception as e:
        logger.warning(f"Fund flow fetch failed: {e}")
        stale = _load_stale(ck)
        if stale:
            return stale
        raise HTTPException(status_code=503, detail=f"资金流向数据获取失败（非交易时间可能无数据）: {e}")


# ── Industry summary endpoint ─────────────────────────────────────────────────

async def _node_stocks_cached(meta: dict, kind: str) -> list[dict]:
    """Constituents for a board, stored in the sector_constituents table.

    Summary and drill-down share the same per-board rows (keyed kind+name)."""
    name = meta["name"]
    if db_cache.sector_constituents_fresh(kind, name, _TTL_STOCKS):
        return db_cache.get_sector_constituents(kind, name) or []
    stocks = await asyncio.to_thread(_sina_node_stocks, meta["node"], meta["count"])
    stocks.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
    if stocks:
        db_cache.replace_sector_constituents(kind, name, stocks)
    else:
        stale = db_cache.get_sector_constituents(kind, name)
        if stale:
            return stale
    return stocks


async def _drill_down(kind: str, name: str, boards_loader, label: str) -> dict:
    """Resolve a board's constituents (DB-first, then Sina) for a drill-down."""
    if db_cache.sector_constituents_fresh(kind, name, _TTL_STOCKS):
        stocks = db_cache.get_sector_constituents(kind, name) or []
        return {"board": name, "stocks": stocks, "count": len(stocks)}
    try:
        boards = await boards_loader()
        meta = next((b for b in boards if b["name"] == name or b["node"] == name), None)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"未找到{label}: {name}")
        stocks = await _node_stocks_cached(meta, kind)
        return {"board": name, "stocks": stocks, "count": len(stocks)}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"{kind} cons fetch failed for {name}: {e}")
        stale = db_cache.get_sector_constituents(kind, name)
        if stale:
            return {"board": name, "stocks": stale, "count": len(stale)}
        raise HTTPException(status_code=503, detail=f"{label}成分股获取失败: {e}")


def _summarise_industry_board(board: dict, stocks: list[dict]) -> dict:
    """Merge board-level stats with aggregated constituent valuations."""
    pe_vals = sorted(s["pe"] for s in stocks
                     if s.get("pe") is not None and 0 < s["pe"] < 1000)
    pb_vals = [s["pb"] for s in stocks if s.get("pb") is not None and s["pb"] > 0]
    amount  = sum(s["turnover"] for s in stocks if s.get("turnover"))

    n = len(pe_vals)
    median_pe = None
    avg_pe = None
    if n:
        median_pe = round(pe_vals[n // 2] if n % 2 else (pe_vals[n // 2 - 1] + pe_vals[n // 2]) / 2, 2)
        avg_pe = round(sum(pe_vals) / n, 2)

    return {
        **board,   # name, change_pct, market_cap, turnover_rate, up_count, down_count, leader, leader_change
        "total":     len(stocks),
        "avg_pe":    avg_pe,
        "median_pe": median_pe,
        "pe_valid":  n,
        "avg_pb":    round(sum(pb_vals) / len(pb_vals), 2) if pb_vals else None,
        "amount":    round(amount, 2) if amount else None,
    }


async def _build_summary(boards: list[dict], prefix: str) -> list[dict]:
    """Aggregate each board's constituents into board-level valuation stats."""
    sem = asyncio.Semaphore(6)

    async def enrich(meta: dict) -> dict:
        async with sem:
            try:
                stocks = await _node_stocks_cached(meta, prefix)
            except Exception as e:
                logger.debug(f"{prefix} summary cons fetch failed for {meta['name']}: {e}")
                stocks = []

        up = sum(1 for s in stocks if (s.get("change_pct") or 0) > 0)
        down = sum(1 for s in stocks if (s.get("change_pct") or 0) < 0)
        mcap = sum(s["market_cap"] for s in stocks if s.get("market_cap"))
        turs = [s["turnover_rate"] for s in stocks if s.get("turnover_rate") is not None]
        leader = max(stocks, key=lambda s: s.get("change_pct") or -1e9, default=None)

        board = {
            "name":          meta["name"],
            "node":          meta.get("node"),
            "change_pct":    meta.get("change_pct"),
            "market_cap":    round(mcap, 2) if mcap else None,
            "turnover_rate": round(sum(turs) / len(turs), 4) if turs else None,
            "up_count":      up,
            "down_count":    down,
            "leader":        (leader or {}).get("name") or meta.get("leader", ""),
            "leader_change": (leader or {}).get("change_pct"),
        }
        return _summarise_industry_board(board, stocks)

    return await asyncio.gather(*[enrich(b) for b in boards])


def _boards_result(kind: str, boards: list[dict]) -> dict:
    return {"boards": boards, "count": len(boards), "type": kind}


async def _summary_endpoint(kind: str, boards_loader, label: str) -> dict:
    # Serve from the sector_boards table while fresh.
    if db_cache.sector_boards_fresh(kind, _TTL_PE):
        return _boards_result(kind, db_cache.get_sector_boards(kind) or [])

    try:
        metas = await boards_loader()
    except Exception as e:
        logger.warning(f"{kind} summary board list fetch failed: {e}")
        stale = db_cache.get_sector_boards(kind)
        if stale:
            return _boards_result(kind, stale)
        raise HTTPException(status_code=503, detail=f"{label}数据获取失败（数据源不可达）: {e}")

    if not metas:
        stale = db_cache.get_sector_boards(kind)
        if stale:
            return _boards_result(kind, stale)
        raise HTTPException(status_code=503, detail=f"{label}列表为空")

    enriched = await _build_summary(metas, kind)
    db_cache.replace_sector_boards(kind, enriched)
    return _boards_result(kind, enriched)


@router.get("/industry-summary")
async def industry_summary():
    """All industry boards with aggregated constituent valuations (PE/PB/成交额)."""
    return await _summary_endpoint("industry", _sina_boards_cached, "行业板块")


@router.get("/concept-summary")
async def concept_summary():
    """All concept boards with 同花顺指数 (涨跌幅/资金净流入/成交额)。

    概念板块无统一板块 PE/PB，故 PE/PB 列留空（成分股下钻仍含 PE）。"""
    boards = await _ths_concept_boards()
    if not boards:
        raise HTTPException(status_code=503, detail="概念板块数据获取失败（同花顺源不可达）")
    return _boards_result("concept", boards)


# ── 板块拥挤度 ─────────────────────────────────────────────────────────────────
# 拥挤度 = 资金/交易/动量/估值在某板块的过度集中度，合成 0-100 评分并分 6 档。
# 主因子用**横截面分位**(在全部板块中排名)，冷启动当天即可算；时序因子(放量
# 倍数 / N日动量 / 成交占比时序分位)在 sector_metric_history 攒够历史后自动叠加。
import bisect

_CROWD_LOOKBACK = 60          # 时序分位/动量回看天数
_MOM_WINDOW     = 20          # N日动量窗口(交易日)
_TS_MIN_PTS     = 5           # 时序因子所需最少历史点

# 因子基础权重(行业含估值；缺失因子按可用权重归一)
_CROWD_WEIGHTS = {
    "amount_share": 0.28,     # 成交额占全市场比 —— 拥挤核心
    "turnover":     0.20,     # 换手率(投机强度)
    "momentum":     0.18,     # 近期动量(过热)
    "valuation":    0.13,     # 估值分位(贵=拥挤；概念无 PE/PB 自动跳过)
    "breadth":      0.12,     # 赚钱效应一致性(上涨家数占比)
    "volume":       0.14,     # 放量倍数(今日量 vs 自身均量；无历史跳过)
}

_BANDS = [
    (85, "极度拥挤", "extreme"),
    (70, "拥挤",     "high"),
    (55, "偏热",     "warm"),
    (40, "中性",     "neutral"),
    (25, "偏冷",     "cool"),
    (0,  "冷清",     "cold"),
]


def _band_of(score: float) -> tuple[str, str]:
    for lo, label, key in _BANDS:
        if score >= lo:
            return label, key
    return "冷清", "cold"


def _pctile_map(pairs: list[tuple[int, float | None]]) -> dict[int, float]:
    """横截面分位(0-100，升序：值越大分位越高)。并列取平均秩。"""
    valid = [(i, v) for i, v in pairs if v is not None]
    if not valid:
        return {}
    if len(valid) == 1:
        return {valid[0][0]: 50.0}
    svals = sorted(v for _, v in valid)
    n = len(svals)
    out = {}
    for i, v in valid:
        lo = bisect.bisect_left(svals, v)
        hi = bisect.bisect_right(svals, v)
        rank = (lo + hi - 1) / 2.0
        out[i] = round(rank / (n - 1) * 100, 1)
    return out


def _ts_percentile(series: list[float], value: float) -> float | None:
    """value(今日，外部样本)在自身历史 series 中的时序分位(0-100)。

    用 (低于数 + 0.5·并列数)/n 公式 —— value 超出历史区间时自然落在 0/100，
    不会像横截面 /(n-1) 那样越界(>100)。"""
    vals = [v for v in series if v is not None]
    if len(vals) < _TS_MIN_PTS:
        return None
    svals = sorted(vals)
    n = len(svals)
    lo = bisect.bisect_left(svals, value)
    hi = bisect.bisect_right(svals, value)
    rank = (lo + hi) / 2.0
    return round(rank / n * 100, 1)


def _compute_crowding(kind: str, boards: list[dict], history: dict[str, list[dict]],
                      store_history: bool = False) -> dict:
    """从板块快照(横截面) + 历史(时序)合成拥挤度。

    返回 {boards, summary, has_history, history_days}。``store_history`` 为真时
    把当日合成分写回 sector_metric_history(供趋势对比)。
    """
    boards = [b for b in boards if b.get("name")]
    total_amount = sum((b.get("amount") or 0) for b in boards) or 1.0
    hist_days = max((len(v) for v in history.values()), default=0)
    has_history = hist_days >= _TS_MIN_PTS

    # ── 1) 每板块原始因子值 ──────────────────────────────────────
    rows = []
    for b in boards:
        name = b["name"]
        amount = b.get("amount") or 0
        share = amount / total_amount * 100        # 成交占比 %
        hseries = history.get(name, [])
        hist_amts   = [h["amount"] for h in hseries if h.get("amount")]
        hist_shares = [h["amount_share"] for h in hseries if h.get("amount_share") is not None]
        hist_chgs   = [h["change_pct"] for h in hseries if h.get("change_pct") is not None]

        # 动量：近 N 日累计涨幅(历史 change_pct 求和)；无历史回退当日涨跌
        momentum = None
        if len(hist_chgs) >= 3:
            momentum = round(sum(hist_chgs[-_MOM_WINDOW:]), 2)
        else:
            momentum = b.get("change_pct")

        # 放量倍数：今日成交额 / 自身历史均量(剔今日)
        volume_surge = None
        if len(hist_amts) >= _TS_MIN_PTS:
            base = hist_amts[:-1] if len(hist_amts) > 1 else hist_amts
            avg = sum(base) / len(base) if base else 0
            if avg > 0 and amount > 0:
                volume_surge = round(amount / avg, 2)

        # 成交占比时序分位 + 趋势
        share_ts_pct = _ts_percentile(hist_shares, share) if hist_shares else None
        trend_delta = None
        if len(hist_shares) >= 3:
            base_share = sum(hist_shares) / len(hist_shares)
            trend_delta = round(share - base_share, 3)

        up = b.get("up_count") or 0
        tot = b.get("total") or (up + (b.get("down_count") or 0)) or 0
        breadth = (up / tot * 100) if tot else None

        rows.append({
            "b": b, "name": name, "share": round(share, 3), "amount": amount,
            "_raw": {
                "amount_share": share,
                "turnover":     b.get("turnover_rate"),
                "momentum":     momentum,
                "valuation":    b.get("avg_pb"),
                "breadth":      breadth,
                "volume":       volume_surge,
            },
            "momentum_nd":  momentum,
            "volume_surge": volume_surge,
            "share_ts_pct": share_ts_pct,
            "trend_delta":  trend_delta,
        })

    # ── 2) 各因子横截面分位 ──────────────────────────────────────
    pct_by_factor: dict[str, dict[int, float]] = {}
    for f in _CROWD_WEIGHTS:
        pct_by_factor[f] = _pctile_map([(i, r["_raw"][f]) for i, r in enumerate(rows)])

    # ── 3) 合成 + 分档 ───────────────────────────────────────────
    out_boards = []
    for i, r in enumerate(rows):
        factors = {}
        num = den = 0.0
        for f, w in _CROWD_WEIGHTS.items():
            p = pct_by_factor[f].get(i)
            factors[f] = p
            if p is not None:
                num += w * p
                den += w
        crowding = round(num / den, 1) if den else 50.0
        label, band_key = _band_of(crowding)
        b = r["b"]
        td = r["trend_delta"]
        trend = "up" if (td or 0) > 0.02 else "down" if (td or 0) < -0.02 else "flat"
        out_boards.append({
            "name":         r["name"],
            "crowding":     crowding,
            "band":         band_key,
            "band_label":   label,
            "factors":      factors,             # {factor: 分位 or None}
            "amount_share": r["share"],          # %
            "amount":       r["amount"],
            "change_pct":   b.get("change_pct"),
            "turnover_rate": b.get("turnover_rate"),
            "avg_pb":       b.get("avg_pb"),
            "median_pe":    b.get("median_pe"),
            "momentum_nd":  r["momentum_nd"],
            "volume_surge": r["volume_surge"],
            "net_flow":     b.get("net_flow"),
            "market_cap":   b.get("market_cap"),
            "up_count":     b.get("up_count"),
            "down_count":   b.get("down_count"),
            "leader":       b.get("leader"),
            "share_ts_pct": r["share_ts_pct"],
            "trend":        trend,
            "trend_delta":  td,
        })

    out_boards.sort(key=lambda x: x["crowding"], reverse=True)

    # ── 4) 市场概览 ──────────────────────────────────────────────
    scores = sorted(x["crowding"] for x in out_boards)
    n = len(scores)
    median = scores[n // 2] if n % 2 else (scores[n // 2 - 1] + scores[n // 2]) / 2 if n else 0
    avg = round(sum(scores) / n, 1) if n else 0
    band_counts = {}
    for x in out_boards:
        band_counts[x["band"]] = band_counts.get(x["band"], 0) + 1
    bands_summary = [
        {"band": key, "label": label, "count": band_counts.get(key, 0)}
        for lo, label, key in _BANDS
    ]
    hot = sum(1 for x in out_boards if x["crowding"] >= 70)
    hot_ratio = hot / n if n else 0
    regime = ("过热" if hot_ratio >= 0.18 else "升温" if hot_ratio >= 0.10
              else "均衡" if hot_ratio >= 0.04 else "清淡")
    rising = sorted(
        [x for x in out_boards if x.get("trend_delta") is not None],
        key=lambda x: x["trend_delta"], reverse=True,
    )[:5]

    if store_history:
        today = _dt.date.today().isoformat()
        db_cache.sector_history_append(kind, today, [
            {"name": x["name"], "change_pct": x["change_pct"],
             "turnover_rate": x["turnover_rate"], "amount": x["amount"],
             "market_cap": x["market_cap"], "net_flow": x["net_flow"],
             "amount_share": x["amount_share"], "crowding": x["crowding"]}
            for x in out_boards
        ])

    return {
        "kind": kind,
        "count": n,
        "has_history": has_history,
        "history_days": hist_days,
        "summary": {
            "avg": avg,
            "median": round(median, 1),
            "temp": round(median, 1),
            "regime": regime,
            "hot_count": hot,
            "bands": bands_summary,
            "most_crowded": [x["name"] for x in out_boards[:5]],
            "rising": [{"name": x["name"], "delta": x["trend_delta"],
                        "crowding": x["crowding"]} for x in rising],
        },
        "boards": out_boards,
    }


async def _crowding_boards(kind: str) -> list[dict]:
    """拥挤度所需的板块快照：优先读 sector_boards 落库(预热器维护)，
    冷启动时回退到对应汇总加载。"""
    boards = db_cache.get_sector_boards(kind)
    if boards:
        return boards
    if kind == "concept":
        return await _ths_concept_boards() or []
    # 行业：聚合成分股估值
    metas = await _sina_boards_cached()
    if not metas:
        return []
    enriched = await _build_summary(metas, "industry")
    db_cache.replace_sector_boards("industry", enriched)
    return enriched


@router.get("/crowding")
async def get_crowding(
    kind: str = Query("industry", enum=["industry", "concept"]),
    lookback: int = Query(_CROWD_LOOKBACK, ge=5, le=250),
):
    """板块拥挤度：多因子合成 0-100 评分 + 6 档分类 + 市场拥挤温度概览。

    每个板块都有评分(不止前 N%)，附各因子横截面分位、成交占比时序分位与趋势。"""
    boards = await _crowding_boards(kind)
    if not boards:
        raise HTTPException(status_code=503,
                            detail=f"{'概念' if kind=='concept' else '行业'}板块数据未就绪，请稍后重试")
    history = await asyncio.to_thread(db_cache.sector_history_load, kind, lookback)
    result = await asyncio.to_thread(_compute_crowding, kind, boards, history, False)
    return result


# ── 板块汇总后台预热 ───────────────────────────────────────────────────────────
# 概念板块冷抓要逐个请求 ~373 个同花顺详情页(~30-75s)；行业汇总要聚合成分股估值。
# 缓存(sector_boards 表, TTL=_TTL_PE=20min)一旦过期，下一个访问的用户就要扛整段冷抓。
# 本预热器周期性地在后台重灌 DB，使前台访问几乎永远命中缓存(实测 <0.1s)。

async def sector_summary_warmer(interval: int = 20 * 60, cooldown: int = 45 * 60):
    """**唯一**抓取概念板块的地方：周期性预热概念/行业汇总落库，用户请求只读快照。

    概念抓取要逐个请求 ~373 个同花顺详情页，是限频高危动作。被限频(concept_boards
    因 60% 护栏返回 None)时**退避到 cooldown**，不硬刚加重封禁；正常则按 interval 刷新。
    行业走新浪很稳，每轮都刷。"""
    await asyncio.sleep(8)  # 让 app 完成启动
    while True:
        concept_ok = False
        # 概念：抓同花顺指数并落库（含 60% 残缺护栏，残缺不覆盖旧快照）
        try:
            boards = await asyncio.to_thread(ths_concept.concept_boards)
            if boards:
                db_cache.replace_sector_boards("concept", boards)
                concept_ok = True
                logger.info(f"[sector_warmer] 概念板块预热完成: {len(boards)} 个")
            else:
                logger.warning(f"[sector_warmer] 概念抓取失败/残缺(疑似限频)，退避 {cooldown // 60} 分钟")
        except Exception as e:
            logger.warning(f"[sector_warmer] 概念板块预热失败: {e}")
        # 行业：聚合成分股估值后落库
        try:
            metas = await _sina_boards_cached()
            if metas:
                enriched = await _build_summary(metas, "industry")
                db_cache.replace_sector_boards("industry", enriched)
                logger.info(f"[sector_warmer] 行业板块预热完成: {len(enriched)} 个")
        except Exception as e:
            logger.warning(f"[sector_warmer] 行业板块预热失败: {e}")
        # 拥挤度时序：把当日两类板块指标 + 合成拥挤度追加进历史(同日 upsert)，
        # 供拥挤度页的放量倍数/N日动量/成交占比时序分位逐日累积。
        for kind in ("industry", "concept"):
            try:
                boards = db_cache.get_sector_boards(kind)
                if boards:
                    history = db_cache.sector_history_load(kind, _CROWD_LOOKBACK)
                    _compute_crowding(kind, boards, history, store_history=True)
            except Exception as e:
                logger.debug(f"[sector_warmer] {kind} 拥挤度历史追加失败: {e}")
        # 概念被限频时拉长冷却，让封禁自然消退
        await asyncio.sleep(interval if concept_ok else cooldown)
