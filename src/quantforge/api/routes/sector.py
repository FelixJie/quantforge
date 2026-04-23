"""Sector (板块) analysis API routes.

Data sources: akshare (EastMoney backend, free, no token)
  - Industry boards:  ak.stock_board_industry_name_em()
  - Industry stocks:  ak.stock_board_industry_cons_em(symbol)
  - Concept boards:   ak.stock_board_concept_name_em()
  - Concept stocks:   ak.stock_board_concept_cons_em(symbol)
  - Fund flow rank:   ak.stock_sector_fund_flow_rank(indicator, sector_type)

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

router = APIRouter(prefix="/sector", tags=["sector"])

_CACHE_DIR = Path("data/cache/sector")
_TTL_BOARDS = 15 * 60   # 15 minutes for board lists
_TTL_STOCKS = 10 * 60   # 10 minutes for constituent stocks
_TTL_FLOW   = 10 * 60   # 10 minutes for fund flow


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


# ── Industry endpoints ────────────────────────────────────────────────────────

@router.get("/industry")
async def get_industry_boards():
    """All A-share industry boards with performance stats."""
    ck = "industry_boards"
    cached = _load_cache(ck, _TTL_BOARDS)
    if cached:
        return cached

    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_board_industry_name_em)
        boards = _normalise_boards(df)
        result = {"boards": boards, "count": len(boards), "type": "industry"}
        _save_cache(ck, result)
        return result
    except Exception as e:
        logger.warning(f"Industry boards fetch failed: {e}")
        stale = _load_stale(ck)
        if stale:
            return stale
        raise HTTPException(status_code=503, detail=f"行业板块数据获取失败: {e}")


@router.get("/industry/{name}")
async def get_industry_stocks(name: str):
    """Constituent stocks for a specific industry board."""
    ck = f"industry_cons_{name}"
    cached = _load_cache(ck, _TTL_STOCKS)
    if cached:
        return cached

    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_board_industry_cons_em, name)
        stocks = _normalise_cons(df)
        # Sort by change_pct desc
        stocks.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
        result = {"board": name, "stocks": stocks, "count": len(stocks)}
        _save_cache(ck, result)
        return result
    except Exception as e:
        logger.warning(f"Industry cons fetch failed for {name}: {e}")
        stale = _load_stale(ck)
        if stale:
            return stale
        raise HTTPException(status_code=503, detail=f"板块成分股获取失败: {e}")


# ── Concept endpoints ─────────────────────────────────────────────────────────

@router.get("/concept")
async def get_concept_boards():
    """All A-share concept boards with performance stats."""
    ck = "concept_boards"
    cached = _load_cache(ck, _TTL_BOARDS)
    if cached:
        return cached

    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_board_concept_name_em)
        boards = _normalise_boards(df)
        result = {"boards": boards, "count": len(boards), "type": "concept"}
        _save_cache(ck, result)
        return result
    except Exception as e:
        logger.warning(f"Concept boards fetch failed: {e}")
        stale = _load_stale(ck)
        if stale:
            return stale
        raise HTTPException(status_code=503, detail=f"概念板块数据获取失败: {e}")


@router.get("/concept/{name}")
async def get_concept_stocks(name: str):
    """Constituent stocks for a specific concept board."""
    ck = f"concept_cons_{name}"
    cached = _load_cache(ck, _TTL_STOCKS)
    if cached:
        return cached

    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_board_concept_cons_em, name)
        stocks = _normalise_cons(df)
        stocks.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
        result = {"board": name, "stocks": stocks, "count": len(stocks)}
        _save_cache(ck, result)
        return result
    except Exception as e:
        logger.warning(f"Concept cons fetch failed for {name}: {e}")
        stale = _load_stale(ck)
        if stale:
            return stale
        raise HTTPException(status_code=503, detail=f"概念成分股获取失败: {e}")


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
