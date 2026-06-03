"""Stock data aggregation — unified endpoints for search, quotes and K-lines.

Endpoints:
  GET /api/stock/search?q=...        → fuzzy search by code/name
  GET /api/stock/quote/{code}        → latest quote + metadata
  GET /api/stock/kline/{code}        → K-line (support period/interval)
  GET /api/stock/detail/{code}       → combined info + quote + short chart

The backend is thin — it delegates to efinance and returns normalized JSON so
that the frontend can rely on a predictable schema.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/stock", tags=["stock"])


# ── Schemas ────────────────────────────────────────────────────────────────

class StockQuote(BaseModel):
    code: str
    name: str
    price: Optional[float] = None
    change_pct: Optional[float] = None
    change: Optional[float] = None
    volume: Optional[float] = None
    turnover: Optional[float] = None
    amplitude: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    open: Optional[float] = None
    pre_close: Optional[float] = None


class KlineItem(BaseModel):
    datetime: str
    open: float
    close: float
    high: float
    low: float
    volume: float


class StockSearchItem(BaseModel):
    code: str
    name: str
    exchange: Optional[str] = ""


# ── Helpers ─────────────────────────────────────────────────────────────────

_PERIOD_MAP = {
    "1d": 101,     # 日K
    "1w": 102,     # 周K
    "1m": 103,     # 月K
    "5min": 5,
    "15min": 15,
    "30min": 30,
    "60min": 60,
}


# ── Search ──────────────────────────────────────────────────────────────────

@router.get("/search", response_model=List[StockSearchItem])
async def search_stocks(q: str = Query("", min_length=1, max_length=20)):
    """Fuzzy-search stocks by code or name.

    Uses the in-memory metadata cache (``stock_meta_cache``) for speed — cache
    is populated in background at app startup via ``stock_meta_cache.refresh``.
    """
    query = (q or "").strip().lower()
    if not query:
        return []

    try:
        from quantforge.data.storage.stock_meta_cache import get_all_names
        names = get_all_names() or {}
    except Exception:
        names = {}

    results = []
    for code, name in names.items():
        if query in code.lower() or query in (name or "").lower():
            results.append({"code": code, "name": name or code, "exchange": ""})
            if len(results) >= 20:
                break

    # Fallback: if the local cache is empty, attempt a live search via efinance
    if not results:
        try:
            import efinance as ef

            def _live_search():
                df = ef.stock.get_realtime_quotes()
                if df is None or df.empty:
                    return []
                matches = []
                for _, row in df.iterrows():
                    try:
                        code = str(row.iloc[1]).strip()
                        nm = str(row.iloc[0]).strip()
                        if query in code.lower() or query in nm.lower():
                            matches.append({"code": code, "name": nm, "exchange": ""})
                            if len(matches) >= 20:
                                break
                    except Exception:
                        continue
                return matches

            results = await asyncio.to_thread(_live_search)
        except Exception:
            pass

    return results


# ── Quote ──────────────────────────────────────────────────────────────────

@router.get("/quote/{code}", response_model=StockQuote)
async def get_stock_quote(code: str):
    """Return a normalized latest quote for a single stock code."""
    code = code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="股票代码不能为空")

    try:
        import efinance as ef

        def _sync():
            df = ef.stock.get_latest_quote(code)
            if df is None or df.empty:
                return None
            row = df.iloc[0]
            code_val = str(row.iloc[0]).strip() if len(row) > 0 else code
            name_val = str(row.iloc[1]).strip() if len(row) > 1 else code
            price = float(row.iloc[3]) if len(row) > 3 else None
            change_pct = float(row.iloc[2]) if len(row) > 2 else None
            high = float(row.iloc[4]) if len(row) > 4 else None
            low = float(row.iloc[5]) if len(row) > 5 else None
            open_price = float(row.iloc[4]) if len(row) > 4 else None  # fallback
            volume = float(row.iloc[6]) if len(row) > 6 else None
            turnover = float(row.iloc[7]) if len(row) > 7 else None
            amplitude = float(row.iloc[8]) if len(row) > 8 else None
            pre_close = float(row.iloc[13]) if len(row) > 13 else None
            change = None
            if price is not None and pre_close is not None:
                change = round(price - pre_close, 2)
            return {
                "code": code_val,
                "name": name_val,
                "price": price,
                "change_pct": change_pct,
                "change": change,
                "volume": volume,
                "turnover": turnover,
                "amplitude": amplitude,
                "high": high,
                "low": low,
                "open": open_price,
                "pre_close": pre_close,
            }

        result = await asyncio.to_thread(_sync)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"获取行情失败: {exc}")

    if not result:
        raise HTTPException(status_code=404, detail="未找到该股票行情数据")
    return result


# ── K-line ──────────────────────────────────────────────────────────────────

@router.get("/kline/{code}")
async def get_kline(
    code: str,
    period: str = Query("1d", description="K线周期: 1d, 1w, 1m, 5min, 15min, 30min, 60min"),
    days: int = Query(180, ge=1, le=2000, description="获取最近多少根K线"),
):
    """Return K-line data for ``code`` in the requested period/interval.

    Intraday periods (``5min`` … ``60min``) are fetched via the intraday API;
    daily/weekly/monthly use the historical data API.
    """
    code = code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="股票代码不能为空")

    valid_periods = set(_PERIOD_MAP.keys())
    if period not in valid_periods:
        raise HTTPException(status_code=400, detail=f"不支持的周期，支持: {', '.join(sorted(valid_periods))}")

    is_intraday = period.endswith("min")

    try:
        import efinance as ef

        def _sync_historical():
            """Historical K-line — daily / weekly / monthly."""
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=max(days * 2, 60))).strftime("%Y%m%d")
            kwargs = {}
            if period == "1d":
                kwargs["klt"] = 101
            elif period == "1w":
                kwargs["klt"] = 102
            elif period == "1m":
                kwargs["klt"] = 103
            df = ef.stock.get_quote_history(code, beg=start_date, end=end_date, **kwargs)
            if df is None or df.empty:
                return []
            result = []
            for _, row in df.iterrows():
                try:
                    # efinance columns: 日期, 开盘, 收盘, 最高, 最低, 成交量, …
                    dt_val = str(row.iloc[0]) if len(row) > 0 else ""
                    open_price = float(row.iloc[1]) if len(row) > 1 else 0.0
                    close_price = float(row.iloc[2]) if len(row) > 2 else 0.0
                    high_price = float(row.iloc[3]) if len(row) > 3 else 0.0
                    low_price = float(row.iloc[4]) if len(row) > 4 else 0.0
                    volume_val = float(row.iloc[5]) if len(row) > 5 else 0.0
                    result.append({
                        "datetime": dt_val,
                        "open": open_price,
                        "close": close_price,
                        "high": high_price,
                        "low": low_price,
                        "volume": volume_val,
                    })
                except (ValueError, TypeError, IndexError):
                    continue
            return result[-days:]

        def _sync_intraday():
            """Intraday K-line — 5/15/30/60 min.  Reads the historical intraday feed."""
            klt = _PERIOD_MAP[period]
            # Recent ~60 bars — efinance intraday gives current-day only, but we
            # call get_quote_history with the intraday klt which returns
            # multi-session intraday bars when the back-end has them.
            try:
                df = ef.stock.get_quote_history(code, klt=klt)
            except Exception:
                df = None
            if df is None or df.empty:
                return []
            result = []
            for _, row in df.iterrows():
                try:
                    dt_val = str(row.iloc[0]) if len(row) > 0 else ""
                    open_price = float(row.iloc[1]) if len(row) > 1 else 0.0
                    close_price = float(row.iloc[2]) if len(row) > 2 else 0.0
                    high_price = float(row.iloc[3]) if len(row) > 3 else 0.0
                    low_price = float(row.iloc[4]) if len(row) > 4 else 0.0
                    volume_val = float(row.iloc[5]) if len(row) > 5 else 0.0
                    result.append({
                        "datetime": dt_val,
                        "open": open_price,
                        "close": close_price,
                        "high": high_price,
                        "low": low_price,
                        "volume": volume_val,
                    })
                except (ValueError, TypeError, IndexError):
                    continue
            return result[-days:]

        if is_intraday:
            bars = await asyncio.to_thread(_sync_intraday)
        else:
            bars = await asyncio.to_thread(_sync_historical)

        if not bars:
            # Provide an empty-but-valid response so the UI can render a "no data" state
            return {"code": code, "period": period, "count": 0, "bars": []}

        return {"code": code, "period": period, "count": len(bars), "bars": bars}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"获取K线数据失败: {exc}")


# ── Combined detail view ────────────────────────────────────────────────────

@router.get("/detail/{code}")
async def get_stock_detail(code: str):
    """Return combined data for the detail view — quote + recent K-line (60 bars).

    Designed for the StockDetail Vue page — one HTTP call has everything the
    page needs to render summary + candlestick chart.
    """
    code = code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="股票代码不能为空")

    quote_task = get_stock_quote(code)
    kline_task = get_kline(code, period="1d", days=120)

    # Run both in parallel — careful: these are async coroutine results, but
    # they call await asyncio.to_thread internally.  gather is safe.
    results = await asyncio.gather(quote_task, kline_task, return_exceptions=True)

    quote = None
    bars = []
    errors = []

    if isinstance(results[0], Exception):
        errors.append(f"quote: {results[0]}")
    else:
        quote = results[0]

    if isinstance(results[1], Exception):
        errors.append(f"kline: {results[1]}")
    else:
        bars = results[1].get("bars", []) if isinstance(results[1], dict) else []

    if quote is None and not bars:
        raise HTTPException(status_code=503, detail="无法获取股票数据; errors=" + "; ".join(errors))

    # Compute simple derived stats from the bars
    avg_volume = None
    latest_close = None
    highest_high = None
    lowest_low = None
    if bars:
        vols = [b.get("volume") or 0 for b in bars[-20:] if b.get("volume") is not None]
        if vols:
            avg_volume = round(sum(vols) / len(vols), 2)
        closes = [b.get("close") for b in bars if b.get("close") is not None]
        if closes:
            latest_close = closes[-1]
        highs = [b.get("high") for b in bars[-60:] if b.get("high") is not None]
        lows = [b.get("low") for b in bars[-60:] if b.get("low") is not None]
        if highs:
            highest_high = max(highs)
        if lows:
            lowest_low = min(lows)

    return {
        "code": code,
        "quote": quote,
        "bars": bars,
        "stats": {
            "avg_volume_20d": avg_volume,
            "latest_close": latest_close,
            "high_60d": highest_high,
            "low_60d": lowest_low,
        },
        "errors": errors,
    }


# ── Market summary ──────────────────────────────────────────────────────────

@router.get("/market-summary")
async def get_market_summary():
    """Return a lightweight market summary — major indices + market breadth.

    Used by the dashboard and watchlist pages to give the user a quick
    overview of the A-share market status.
    """
    indices = [
        ("上证指数", "000001"),
        ("深证成指", "399001"),
        ("创业板指", "399006"),
        ("沪深300", "000300"),
        ("中证500", "000905"),
        ("科创50", "000688"),
    ]

    try:
        import efinance as ef

        def _sync():
            out = []
            for name, code in indices:
                try:
                    df = ef.stock.get_latest_quote(code)
                    if df is None or df.empty:
                        out.append({"name": name, "code": code, "price": None,
                                     "change_pct": None, "change": None})
                        continue
                    row = df.iloc[0]
                    price = float(row.iloc[3]) if len(row) > 3 else None
                    change_pct = float(row.iloc[2]) if len(row) > 2 else None
                    pre_close = float(row.iloc[13]) if len(row) > 13 else None
                    change = round(price - pre_close, 2) if price is not None and pre_close is not None else None
                    out.append({"name": name, "code": code, "price": price,
                                 "change_pct": change_pct, "change": change})
                except Exception:
                    out.append({"name": name, "code": code, "price": None,
                                 "change_pct": None, "change": None})
            return out

        idx_results = await asyncio.to_thread(_sync)
    except Exception as exc:
        idx_results = []
        logger_warning = str(exc)
        import warnings
        warnings.warn(logger_warning)

    return {"indices": idx_results}
