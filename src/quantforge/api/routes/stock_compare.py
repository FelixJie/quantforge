"""Multi-stock side-by-side comparison.

复用个股分析（stock_analysis）的取数逻辑，把 2~6 只股票放在一起做横向对比：
行情、估值（PE/PB/ROE/毛利率/市值）、技术面（信号/RSI/MACD/支撑压力）、
动量评分与买卖点、机构一致目标价与上行空间、估值风险。并对可量化的维度
给出跨标的排名，前端可一眼看出谁强谁弱。

Endpoint:
  POST /api/stock-compare   body: {"symbols": ["600519", "000858", ...], "days": 180}
"""

from __future__ import annotations

import asyncio
import datetime as _dt

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from loguru import logger

from quantforge.api.routes import stock_analysis as _sa

router = APIRouter(prefix="/stock-compare", tags=["stock-compare"])

_MAX_SYMBOLS = 6


class CompareRequest(BaseModel):
    symbols: list[str]
    days: int = 180


def _last(seq) -> float | None:
    """取序列里最后一个非空值。"""
    if not seq:
        return None
    for v in reversed(seq):
        if v is not None:
            return v
    return None


def _build_one(symbol: str, days: int) -> dict:
    """组装单只股票的对比所需字段（运行在线程池里，可同步取数）。"""
    sym = str(symbol).strip().upper()
    out: dict = {"symbol": sym, "name": sym, "ok": False}

    try:
        ov = _sa._fetch_overview(sym)
    except Exception as e:
        logger.warning(f"compare overview {sym} failed: {e}")
        ov = {}

    try:
        tech = _sa._fetch_technical(sym, days)
    except Exception as e:
        logger.warning(f"compare technical {sym} failed: {e}")
        tech = {}

    try:
        mom = _sa._fetch_momentum(sym, days)
    except Exception as e:
        logger.warning(f"compare momentum {sym} failed: {e}")
        mom = {}

    name = ov.get("name") or sym
    last_close = None
    bars = tech.get("bars") or []
    if bars:
        last_close = bars[-1].get("close")

    # 归一化收盘价序列（首日=100），供前端叠加走势对比
    norm = []
    dates = []
    base = None
    for b in bars[-days:]:
        c = b.get("close")
        if c is None:
            continue
        if base is None and c:
            base = c
        dates.append(b.get("date"))
        norm.append(round(c / base * 100, 2) if base else None)

    # 区间涨跌（首末收盘）
    period_chg = None
    if base and last_close:
        period_chg = round((last_close / base - 1) * 100, 2)

    rsi_last = _last(tech.get("rsi"))
    macd = tech.get("macd") or {}
    macd_hist = _last(macd.get("hist"))

    mom_cur = mom.get("current") or {}
    target = mom.get("target") or {}
    consensus = target.get("consensus") or {}
    risk = mom.get("risk") or {}

    out.update({
        "name": name,
        "ok": True,
        # 行情
        "price":            ov.get("price") or last_close,
        "change_pct":       ov.get("change_pct"),
        "period_change_pct": period_chg,
        "turnover_rate":    ov.get("turnover_rate"),
        "amplitude":        ov.get("amplitude"),
        "vol_ratio":        ov.get("vol_ratio"),
        # 估值
        "pe_ttm":           ov.get("pe_ttm"),
        "pb":               ov.get("pb"),
        "roe":              ov.get("roe"),
        "gross_margin":     ov.get("gross_margin"),
        "market_cap":       ov.get("market_cap"),
        "circ_cap":         ov.get("circ_cap"),
        # 技术面
        "signal":           tech.get("signal"),
        "rsi":              rsi_last,
        "macd_hist":        macd_hist,
        "support":          tech.get("support"),
        "resistance":       tech.get("resistance"),
        # 动量与买卖点
        "momentum_score":   mom_cur.get("score"),
        "momentum_state":   mom_cur.get("state"),
        "buy_price":        mom_cur.get("buy_price"),
        "stop_price":       mom_cur.get("stop_price"),
        "target_price":     mom_cur.get("target_price"),
        # 机构一致目标价
        "consensus_median": consensus.get("median"),
        "consensus_upside": consensus.get("upside_pct"),
        "consensus_count":  consensus.get("count"),
        "rating_top":       _top_rating(consensus.get("ratings")),
        # 风险
        "risk_level":       risk.get("level"),
        "risk_items":       [it.get("msg") for it in (risk.get("items") or [])][:4],
        # 走势对比序列
        "norm_dates":       dates,
        "norm_series":      norm,
    })
    return out


def _top_rating(ratings: dict | None) -> str | None:
    if not ratings:
        return None
    try:
        return max(ratings.items(), key=lambda kv: kv[1])[0]
    except Exception:
        return None


# 排名口径：True = 数值越大越优（绿色高亮第一名），False = 越小越优
_RANK_FIELDS = {
    "period_change_pct": True,
    "roe":              True,
    "gross_margin":     True,
    "momentum_score":   True,
    "consensus_upside": True,
    "market_cap":       True,
    "pe_ttm":           False,   # 低估值更优（仅对正 PE 排名）
    "pb":               False,
}


def _annotate_ranks(rows: list[dict]) -> dict:
    """对可量化字段做横向排名，返回 {field: {symbol: rank}}（rank 从 1 起）。"""
    ranks: dict = {}
    for field, higher_better in _RANK_FIELDS.items():
        scored = []
        for r in rows:
            v = r.get(field)
            if v is None:
                continue
            if field == "pe_ttm" and (not isinstance(v, (int, float)) or v <= 0):
                continue  # 负/零 PE 不参与估值排名
            scored.append((r["symbol"], v))
        if len(scored) < 2:
            continue
        scored.sort(key=lambda kv: kv[1], reverse=higher_better)
        ranks[field] = {sym: i + 1 for i, (sym, _) in enumerate(scored)}
    return ranks


@router.post("")
async def compare(body: CompareRequest):
    syms = [s.strip().upper() for s in (body.symbols or []) if s and s.strip()]
    # 去重保序
    seen: set[str] = set()
    syms = [s for s in syms if not (s in seen or seen.add(s))]

    if len(syms) < 2:
        raise HTTPException(status_code=400, detail="请至少提供 2 只股票代码")
    if len(syms) > _MAX_SYMBOLS:
        raise HTTPException(status_code=400, detail=f"最多对比 {_MAX_SYMBOLS} 只股票")

    days = max(30, min(int(body.days or 180), 500))

    try:
        rows = await asyncio.gather(
            *(asyncio.to_thread(_build_one, s, days) for s in syms)
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    rows = list(rows)
    ranks = _annotate_ranks([r for r in rows if r.get("ok")])

    return {
        "symbols":     syms,
        "days":        days,
        "stocks":      rows,
        "ranks":       ranks,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
