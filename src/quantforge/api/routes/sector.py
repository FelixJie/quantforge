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
    ck = "sina_industry_list"
    cached = _load_cache(ck, _TTL_BOARDS)
    if cached:
        return cached.get("boards", [])
    boards = await asyncio.to_thread(_sina_industry_list)
    if boards:
        _save_cache(ck, {"boards": boards})
    return boards


async def _sina_concept_boards_cached() -> list[dict]:
    ck = "sina_concept_list"
    cached = _load_cache(ck, _TTL_BOARDS)
    if cached:
        return cached.get("boards", [])
    boards = await asyncio.to_thread(_sina_concept_list)
    if boards:
        _save_cache(ck, {"boards": boards})
    return boards


# ── Industry endpoints ────────────────────────────────────────────────────────

@router.get("/industry")
async def get_industry_boards():
    """All A-share industry boards (Sina) with board-level stats."""
    ck = "industry_boards"
    cached = _load_cache(ck, _TTL_BOARDS)
    if cached:
        return cached

    try:
        boards = await _sina_boards_cached()
        if not boards:
            raise RuntimeError("空列表")
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
    """Constituent stocks for a specific industry board (Sina)."""
    ck = f"industry_cons_{name}"
    cached = _load_cache(ck, _TTL_STOCKS)
    if cached:
        return cached

    try:
        boards = await _sina_boards_cached()
        meta = next((b for b in boards if b["name"] == name or b["node"] == name), None)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"未找到行业板块: {name}")
        stocks = await asyncio.to_thread(_sina_node_stocks, meta["node"], meta["count"])
        stocks.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
        result = {"board": name, "stocks": stocks, "count": len(stocks)}
        _save_cache(ck, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Industry cons fetch failed for {name}: {e}")
        stale = _load_stale(ck)
        if stale:
            return stale
        raise HTTPException(status_code=503, detail=f"板块成分股获取失败: {e}")


# ── Concept endpoints ─────────────────────────────────────────────────────────

@router.get("/concept")
async def get_concept_boards():
    """All A-share concept boards (Sina). market_cap proxied by turnover so the
    treemap still renders (Sina's cheap list has no board market cap)."""
    ck = "concept_boards"
    cached = _load_cache(ck, _TTL_BOARDS)
    if cached:
        return cached

    try:
        boards = await _sina_concept_boards_cached()
        if not boards:
            raise RuntimeError("空列表")
        for b in boards:
            b["market_cap"] = b.get("amount")   # treemap area = turnover
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
    """Constituent stocks for a specific concept board (Sina)."""
    ck = f"concept_cons_{name}"
    cached = _load_cache(ck, _TTL_STOCKS)
    if cached:
        return cached

    try:
        boards = await _sina_concept_boards_cached()
        meta = next((b for b in boards if b["name"] == name or b["node"] == name), None)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"未找到概念板块: {name}")
        stocks = await asyncio.to_thread(_sina_node_stocks, meta["node"], meta["count"])
        stocks.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
        result = {"board": name, "stocks": stocks, "count": len(stocks)}
        _save_cache(ck, result)
        return result
    except HTTPException:
        raise
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


# ── Industry summary endpoint ─────────────────────────────────────────────────

async def _industry_stocks_cached(meta: dict) -> list[dict]:
    ck = f"industry_cons_{meta['name']}"
    cached = _load_cache(ck, _TTL_STOCKS)
    if cached:
        return cached.get("stocks", [])
    stocks = await asyncio.to_thread(_sina_node_stocks, meta["node"], meta["count"])
    stocks.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
    if stocks:
        _save_cache(ck, {"board": meta["name"], "stocks": stocks, "count": len(stocks)})
    return stocks


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


@router.get("/industry-summary")
async def industry_summary():
    """All industry boards with aggregated constituent valuations (PE/PB/成交额)."""
    ck = "industry_summary"
    cached = _load_cache(ck, _TTL_PE)
    if cached:
        return cached

    try:
        boards = await _sina_boards_cached()
    except Exception as e:
        logger.warning(f"Industry summary board list fetch failed: {e}")
        stale = _load_stale(ck)
        if stale:
            return stale
        raise HTTPException(status_code=503, detail=f"行业板块数据获取失败（数据源不可达）: {e}")

    if not boards:
        stale = _load_stale(ck)
        if stale:
            return stale
        raise HTTPException(status_code=503, detail="行业板块列表为空")

    sem = asyncio.Semaphore(6)

    async def enrich(meta: dict) -> dict:
        async with sem:
            try:
                stocks = await _industry_stocks_cached(meta)
            except Exception as e:
                logger.debug(f"Industry summary cons fetch failed for {meta['name']}: {e}")
                stocks = []

        up = sum(1 for s in stocks if (s.get("change_pct") or 0) > 0)
        down = sum(1 for s in stocks if (s.get("change_pct") or 0) < 0)
        mcap = sum(s["market_cap"] for s in stocks if s.get("market_cap"))
        turs = [s["turnover_rate"] for s in stocks if s.get("turnover_rate") is not None]
        leader = max(stocks, key=lambda s: s.get("change_pct") or -1e9, default=None)

        board = {
            "name":          meta["name"],
            "change_pct":    meta.get("change_pct"),
            "market_cap":    round(mcap, 2) if mcap else None,
            "turnover_rate": round(sum(turs) / len(turs), 4) if turs else None,
            "up_count":      up,
            "down_count":    down,
            "leader":        (leader or {}).get("name") or meta.get("leader", ""),
            "leader_change": (leader or {}).get("change_pct"),
        }
        return _summarise_industry_board(board, stocks)

    enriched = await asyncio.gather(*[enrich(b) for b in boards])
    result = {"boards": enriched, "count": len(enriched), "type": "industry"}
    _save_cache(ck, result)
    return result
