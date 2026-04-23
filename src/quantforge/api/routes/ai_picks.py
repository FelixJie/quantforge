"""AI daily stock picks — every day the AI analyses candidate stocks and recommends 10.

Flow:
  1. Load today's screener summary (or run a quick one if stale)
  2. Aggregate top candidates across all strategies (unique, top ~40)
  3. Enrich each candidate with latest market data (price, change%, technical signals)
  4. Send to Doubao AI with a structured prompt
  5. Parse JSON response → cache for 24 h per calendar date
  6. Return picks + market summary

Endpoints:
  GET  /api/ai-picks/daily      → today's 10 picks (cached)
  POST /api/ai-picks/refresh    → force regenerate in background
  GET  /api/ai-picks/history    → list of cached dates + performance preview
"""

from __future__ import annotations

import asyncio
import json
import math
import datetime as _dt
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from loguru import logger

router = APIRouter(prefix="/ai-picks", tags=["ai-picks"])

_CACHE_DIR = Path("data/cache/ai_picks")
_RUNNING = False   # simple flag to avoid concurrent regeneration


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _next_trading_day() -> _dt.date:
    """Return the next trading day the user will buy on.

    - Before 15:00 on a weekday → today (market still open or about to open)
    - After 15:00 on a weekday  → next weekday
    - Weekend                   → next Monday
    """
    now = _dt.datetime.now()
    day = now.date()
    # After market close (15:00) → advance to next day
    if now.hour >= 15:
        day += _dt.timedelta(days=1)
    # Skip weekends (5=Sat, 6=Sun)
    while day.weekday() >= 5:
        day += _dt.timedelta(days=1)
    return day


def _today_key() -> str:
    return _next_trading_day().isoformat()


def _cache_path(date_key: str) -> Path:
    return _CACHE_DIR / f"{date_key}.json"


def _load_today() -> dict | None:
    f = _cache_path(_today_key())
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save(data: dict, date_key: str | None = None):
    key = date_key or _today_key()
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(key).write_text(
            json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"ai_picks cache save failed: {e}")


def _list_history() -> list[dict]:
    """Return all cached dates sorted descending, with basic metadata."""
    if not _CACHE_DIR.exists():
        return []
    result = []
    for f in sorted(_CACHE_DIR.glob("*.json"), reverse=True)[:30]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result.append({
                "date": f.stem,
                "generated_at": data.get("generated_at", ""),
                "pick_count": len(data.get("picks", [])),
                "market_summary": data.get("market_summary", ""),
            })
        except Exception:
            continue
    return result


# ── Candidate collection ───────────────────────────────────────────────────────

async def _collect_candidates() -> list[dict]:
    """Run screener summary and return top unique candidates."""
    from quantforge.screener.cache import get_cached, run_all

    summary = get_cached()
    # Check if cache has any stocks; if empty, force re-run
    has_stocks = any(
        len(r.get("stocks", [])) > 0
        for r in (summary or {}).get("results", {}).values()
    )
    if not summary or not has_stocks:
        logger.info("ai_picks: no screener cache or empty results, running strategies now...")
        summary = await run_all()

    # Aggregate stocks across all strategy results
    code_scores: dict[str, dict] = {}
    for key, result in summary.get("results", {}).items():
        strat = result.get("strategy", {})
        stocks = result.get("stocks", [])
        for rank, s in enumerate(stocks[:20]):   # top 20 per strategy
            code = s.get("code", "")
            if not code:
                continue
            if code not in code_scores:
                code_scores[code] = {**s, "hit_strategies": [], "hit_count": 0, "avg_rank": 0}
            code_scores[code]["hit_strategies"].append({
                "key": key,
                "name": strat.get("display_name", key),
                "color": strat.get("category_color", "#3b82f6"),
            })
            code_scores[code]["hit_count"] += 1
            code_scores[code]["avg_rank"] = (
                code_scores[code].get("avg_rank", 0) + rank + 1
            )

    # Sort: more strategy hits first, then lower avg rank
    candidates = list(code_scores.values())
    for c in candidates:
        if c["hit_count"] > 0:
            c["avg_rank"] = round(c["avg_rank"] / c["hit_count"], 1)
    candidates.sort(key=lambda x: (-x["hit_count"], x.get("avg_rank", 999)))

    return candidates[:40]   # top 40 for AI to choose from


# ── Market data enrichment ─────────────────────────────────────────────────────

def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    except Exception:
        return None


async def _enrich_candidates(candidates: list[dict]) -> list[dict]:
    """Add latest price, change%, technical signals to each candidate."""
    if not candidates:
        return candidates

    try:
        import efinance as ef
        codes = [c["code"] for c in candidates if c.get("code")]

        def _fetch():
            return ef.stock.get_realtime_quotes(codes)

        df = await asyncio.to_thread(_fetch)

        # Build lookup: code → row
        lookup: dict[str, dict] = {}
        for _, row in df.iterrows():
            try:
                code = str(row.iloc[1]).strip().zfill(6)
                lookup[code] = {
                    "price":      _safe_float(row.iloc[3]),
                    "change_pct": _safe_float(row.iloc[5]),
                    "volume":     _safe_float(row.iloc[6]),
                    "turnover":   _safe_float(row.iloc[7]),
                    "amplitude":  _safe_float(row.iloc[8]),
                    "high":       _safe_float(row.iloc[9]),
                    "low":        _safe_float(row.iloc[10]),
                    "pre_close":  _safe_float(row.iloc[12]),
                }
            except Exception:
                continue

        for c in candidates:
            code = c.get("code", "")
            if code in lookup:
                c.update(lookup[code])
    except Exception as e:
        logger.warning(f"ai_picks: realtime enrich failed: {e}")

    return candidates


# ── AI analysis ────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """你是一位专业的A股量化分析师，擅长技术面与基本面结合分析。
你将收到一批经过多因子模型筛选的候选股票数据，包括估值、动量、策略命中、实时行情等信息。
请综合技术面（均线、量价关系）、基本面（PE/PB估值）和市场情绪，从候选股中精选10只最具潜力的股票。

重要要求：
1. 给出精确的买入价位（支撑位/均线回踩位），不要模糊区间
2. 给出明确的止损价（基于关键支撑或ATR，不超过8%）
3. 给出目标价（基于上方阻力位或目标涨幅）
4. 给出操作前置条件清单（满足全部条件才操作）

输出格式要求：严格返回JSON，不要任何markdown或其他文字，格式如下：
{
  "market_summary": "一句话描述今日A股市场整体环境和操作思路",
  "operation_strategy": "今日整体操作策略：进攻/均衡/防守，及理由",
  "picks": [
    {
      "rank": 1,
      "code": "股票代码（6位）",
      "name": "股票名称",
      "sector": "所属行业",
      "reason": "推荐理由，2-3句话，涵盖技术面+估值+催化剂",
      "signals": ["关键信号1", "关键信号2", "关键信号3"],
      "buy_price": 精确买入价如12.50,
      "stop_price": 精确止损价如11.80,
      "target_price": 精确目标价如14.20,
      "target_pct": 目标涨幅百分比数字如12.5,
      "stop_pct": 止损幅度百分比数字如5.0,
      "checklist": [
        "条件1: 价格回踩MA20且站稳",
        "条件2: 成交量相对前日缩量",
        "条件3: 大盘无系统性风险"
      ],
      "confidence": 置信度0-100整数,
      "risk_level": "低|中|高",
      "holding_period": "持有周期如1-2周"
    }
  ]
}
"""


def _build_user_prompt(candidates: list[dict]) -> str:
    today = _dt.date.today().strftime("%Y年%m月%d日")
    lines = [f"今日日期：{today}", "", "候选股票数据（多因子筛选后）：", ""]

    for i, c in enumerate(candidates[:40], 1):
        code = c.get("code", "")
        name = c.get("name", "")
        price = c.get("price") or c.get("current_price")
        change = c.get("change_pct")
        pe = c.get("pe")
        pb = c.get("pb")
        mktcap = c.get("market_cap")
        hit = c.get("hit_count", 1)
        strats = ", ".join(s["name"] for s in c.get("hit_strategies", []))

        parts = [f"{i}. {code} {name}"]
        if price:
            parts.append(f"现价{price}")
        if change is not None:
            parts.append(f"涨跌{change:+.2f}%")
        if pe:
            parts.append(f"PE={pe}")
        if pb:
            parts.append(f"PB={pb}")
        if mktcap:
            parts.append(f"市值{mktcap:.0f}亿" if mktcap > 100 else f"市值{mktcap:.1f}亿")
        if strats:
            parts.append(f"命中策略:[{strats}]×{hit}")
        lines.append(" | ".join(parts))

    lines.append("")
    lines.append("请根据以上数据，综合分析后选出10只最具潜力的股票，按推荐优先级排列。")
    return "\n".join(lines)


async def _call_ai(candidates: list[dict]) -> dict:
    from quantforge.api.ai_client import chat

    user_prompt = _build_user_prompt(candidates)
    logger.info(f"ai_picks: calling AI with {len(candidates)} candidates...")

    raw = await chat(
        system=_SYSTEM_PROMPT,
        user=user_prompt,
        max_tokens=4000,
        caller="ai_picks",
    )

    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    if text.endswith("```"):
        text = text[: text.rfind("```")].strip()

    result = json.loads(text)
    return result


# ── Generation pipeline ────────────────────────────────────────────────────────

async def _generate() -> dict:
    global _RUNNING
    if _RUNNING:
        raise HTTPException(status_code=409, detail="AI分析正在进行中，请稍后刷新")
    _RUNNING = True
    try:
        candidates = await _collect_candidates()
        if not candidates:
            raise ValueError("no candidates from screener")

        candidates = await _enrich_candidates(candidates)

        ai_result = await _call_ai(candidates)

        # Merge actual price data back into picks
        # Build code map with multiple key variants (with/without leading zeros)
        code_map: dict[str, dict] = {}
        for c in candidates:
            code = c.get("code", "")
            if code:
                code_map[code] = c
                code_map[code.lstrip("0")] = c
                code_map[code.zfill(6)] = c
        for pick in ai_result.get("picks", []):
            pcode = pick.get("code", "")
            row = code_map.get(pcode) or code_map.get(pcode.lstrip("0")) or code_map.get(pcode.zfill(6))
            if row:
                pick.setdefault("price", row.get("price") or row.get("current_price"))
                pick.setdefault("change_pct", row.get("change_pct"))
                pick.setdefault("pe", row.get("pe"))
                pick.setdefault("pb", row.get("pb"))
                pick["hit_strategies"] = row.get("hit_strategies", [])

        payload = {
            "generated_at": _dt.datetime.now().isoformat(),
            "date": _today_key(),
            "market_summary": ai_result.get("market_summary", ""),
            "operation_strategy": ai_result.get("operation_strategy", ""),
            "picks": ai_result.get("picks", []),
            "candidate_count": len(candidates),
        }
        _save(payload)
        logger.info(f"ai_picks: generated {len(payload['picks'])} picks")

        # Auto-record predictions for same-day verification
        try:
            from quantforge.prediction.tracker import PredictionTracker
            PredictionTracker.record_picks(payload["picks"], date=_today_key())
        except Exception as e:
            logger.warning(f"ai_picks: prediction recording failed: {e}")

        # Push notifications if ai_picks event is enabled
        try:
            from quantforge.notification.manager import NotificationManager, load_settings
            cfg = load_settings()
            if cfg.get("enabled") and cfg.get("events", {}).get("ai_picks", True):
                mgr = NotificationManager.from_settings()
                title, body = NotificationManager.format_ai_picks(payload)
                asyncio.create_task(mgr.notify(title, body))
        except Exception as e:
            logger.warning(f"ai_picks: notification failed: {e}")

        return payload
    finally:
        _RUNNING = False


# ── API endpoints ──────────────────────────────────────────────────────────────

@router.get("/daily")
async def get_daily_picks():
    """Return today's AI-selected stock picks (cached, regenerated once per day)."""
    cached = _load_today()
    if cached:
        cached["from_cache"] = True
        return cached

    # No cache for today — generate now (synchronous, user waits)
    return await _generate()


@router.post("/refresh")
async def refresh_picks(background_tasks: BackgroundTasks, force: bool = False):
    """Force-regenerate today's picks in the background."""
    global _RUNNING
    if _RUNNING:
        return {"status": "already_running", "message": "AI分析正在进行中"}

    if not force:
        cached = _load_today()
        if cached:
            return {"status": "fresh", "message": "今日推荐已是最新", "generated_at": cached.get("generated_at")}

    background_tasks.add_task(_generate)
    return {"status": "started", "message": "AI分析已在后台启动，约1分钟后刷新页面查看结果"}


@router.get("/status")
async def get_status():
    """Return whether a generation is in progress and cache state."""
    cached = _load_today()
    return {
        "running": _RUNNING,
        "has_today": cached is not None,
        "generated_at": cached.get("generated_at") if cached else None,
        "pick_count": len(cached.get("picks", [])) if cached else 0,
    }


@router.get("/history")
async def get_history():
    """List previously cached daily pick sets."""
    return {"history": _list_history()}


@router.get("/history-date/{date_key}")
async def get_history_date(date_key: str):
    """Return cached picks for a specific date (YYYY-MM-DD)."""
    path = _cache_path(date_key)
    if not path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"No picks found for {date_key}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))
