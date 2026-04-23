"""Market data endpoints and WebSocket streaming."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel

# ── Intraday disk cache ───────────────────────────────────────────────────────
_INTRADAY_DIR = Path("data/cache/intraday")
_INTRADAY_DIR.mkdir(parents=True, exist_ok=True)

def _iday_path(symbol: str, date: str, klt: int) -> Path:
    return _INTRADAY_DIR / f"{symbol}_{date}_{klt}.json"

def _iday_load(symbol: str, date: str, klt: int) -> list | None:
    p = _iday_path(symbol, date, klt)
    if p.exists():
        try:
            data = json.loads(p.read_text())
            if data:  # don't return empty cached failures
                return data
        except Exception:
            pass
    return None

def _iday_save(symbol: str, date: str, klt: int, bars: list):
    if bars:  # only cache non-empty results
        _iday_path(symbol, date, klt).write_text(json.dumps(bars))

from quantforge.api.deps import get_backtest_engine
from quantforge.core.constants import Exchange, Interval
from quantforge.data.feed.efinance_feed import detect_exchange

router = APIRouter(prefix="/market", tags=["market"])


def _resolve_exchange(symbol: str, exchange: str | None) -> Exchange:
    """Resolve exchange string or auto-detect from symbol prefix."""
    if exchange:
        try:
            return Exchange(exchange.upper())
        except ValueError:
            pass
    return detect_exchange(symbol)


# ── Historical bars ───────────────────────────────────────────────────────────

@router.get("/bars/{symbol}")
async def get_bars(
    symbol: str,
    exchange: str | None = None,   # optional — auto-detected if omitted
    start: str = "2024-01-01",
    end: str | None = None,
    interval: str = "1d",
    engine=Depends(get_backtest_engine),
):
    """Return historical bars for a symbol.

    Exchange is optional; if omitted it is inferred from the stock code prefix
    (6xxxxx → SSE, 0/3xxxxx → SZSE).
    """
    exc = _resolve_exchange(symbol, exchange)

    try:
        ivl = Interval(interval)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()

    df = engine._data_manager.load_bars(symbol, ivl, start_dt, end_dt)
    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No local data for {symbol}. Use POST /api/market/download to fetch."
        )

    records = df[["datetime", "open", "high", "low", "close", "volume"]].copy()
    records["datetime"] = records["datetime"].dt.strftime("%Y-%m-%d")
    return {
        "symbol": symbol,
        "exchange": exc.value,
        "count": len(records),
        "bars": records.to_dict(orient="records"),
    }


# ── Download endpoint ─────────────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    symbol: str
    exchange: str | None = None
    start: str = "2020-01-01"
    end: str | None = None
    interval: str = "1d"


@router.post("/download")
async def download_data(req: DownloadRequest, engine=Depends(get_backtest_engine)):
    """Download historical data from eFinance and store locally."""
    exc = _resolve_exchange(req.symbol, req.exchange)

    try:
        ivl = Interval(req.interval)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    start_dt = datetime.strptime(req.start, "%Y-%m-%d")
    end_dt = datetime.strptime(req.end, "%Y-%m-%d") if req.end else datetime.now()

    try:
        df = await engine._data_manager.download(
            symbol=req.symbol,
            interval=ivl,
            start=start_dt,
            end=end_dt,
            exchange=exc,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data returned for {req.symbol}")

    return {
        "symbol": req.symbol,
        "exchange": exc.value,
        "bars": len(df),
        "start": df["datetime"].min().strftime("%Y-%m-%d") if "datetime" in df.columns else req.start,
        "end": df["datetime"].max().strftime("%Y-%m-%d") if "datetime" in df.columns else req.end,
    }


# ── Symbol search ─────────────────────────────────────────────────────────────

@router.get("/symbols")
async def list_symbols(engine=Depends(get_backtest_engine)):
    """List all symbols that have local bar data (all exchanges)."""
    symbols = engine._data_manager.list_all_symbols()
    return {"symbols": symbols, "count": len(symbols)}


@router.get("/meta/names")
async def get_stock_names():
    """Return cached {code: name} mapping for all A-share stocks."""
    from quantforge.data.storage.stock_meta_cache import get_all_names, count
    names = get_all_names()
    return {"names": names, "count": count()}


async def _fetch_intraday_bars(symbol: str, date: str | None, klt: int) -> list:
    """Fetch intraday bars from efinance; tries requested klt then falls back to 5."""
    import efinance as ef

    for try_klt in ([klt] if klt == 5 else [klt, 5]):
        try:
            kwargs: dict = {"klt": try_klt}
            if date:
                d = date.replace("-", "")
                kwargs["beg"] = d
                kwargs["end"] = d
            df = await asyncio.to_thread(ef.stock.get_quote_history, symbol, **kwargs)
            if df is None or df.empty:
                continue
            result = []
            for _, row in df.iterrows():
                try:
                    result.append({
                        "datetime": str(row.iloc[2]),
                        "open":   float(row.iloc[3]),
                        "close":  float(row.iloc[4]),
                        "high":   float(row.iloc[5]),
                        "low":    float(row.iloc[6]),
                        "volume": float(row.iloc[7]),
                        "klt":    try_klt,
                    })
                except (ValueError, IndexError):
                    continue
            if date and result:
                result = [r for r in result if r["datetime"][:10] == date]
            elif not date and result:
                last_date = result[-1]["datetime"][:10]
                result = [r for r in result if r["datetime"][:10] == last_date]
            if result:
                return result
        except Exception as e:
            logger.warning(f"intraday fetch klt={try_klt} failed: {e}")
    return []


class PrefetchRequest(BaseModel):
    symbol: str
    dates: List[str]
    klt: int = 5


@router.post("/prefetch-intraday")
async def prefetch_intraday(req: PrefetchRequest):
    """Pre-fetch and cache intraday data for a list of dates."""
    results: dict = {}
    valid_klt = {1, 5, 15, 30, 60}
    klt = req.klt if req.klt in valid_klt else 5

    async def _fetch_one(date: str):
        if _iday_load(req.symbol, date, klt):
            results[date] = "cached"
            return
        try:
            bars = await _fetch_intraday_bars(req.symbol, date, klt)
            if bars:
                _iday_save(req.symbol, date, klt, bars)
                results[date] = f"{len(bars)} bars"
            else:
                results[date] = "no data"
        except Exception as e:
            results[date] = f"error: {e}"

    await asyncio.gather(*[_fetch_one(d) for d in req.dates[:60]])
    return {"symbol": req.symbol, "klt": klt, "results": results}


@router.get("/intraday/{symbol}")
async def get_intraday(symbol: str, klt: int = 5, date: str | None = None):
    """Return intraday bars for a symbol.
    klt: 1=1min, 5=5min, 15=15min, 30=30min, 60=60min
    date: YYYY-MM-DD to fetch a specific trading day (default: latest session)
    """
    valid_klt = {1, 5, 15, 30, 60}
    if klt not in valid_klt:
        raise HTTPException(status_code=400, detail=f"klt must be one of {valid_klt}")

    # Check disk cache first (historical data never changes)
    if date:
        cached = _iday_load(symbol, date, klt)
        if cached:
            return {"symbol": symbol, "klt": klt, "date": date, "bars": cached,
                    "count": len(cached), "cached": True}

    try:
        bars = await _fetch_intraday_bars(symbol, date, klt)
        if date and bars:
            _iday_save(symbol, date, klt, bars)
        actual_date = bars[0]["datetime"][:10] if bars else date
        return {"symbol": symbol, "klt": klt, "date": actual_date,
                "bars": bars, "count": len(bars), "cached": False}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/search/{query}")
async def search_symbols(query: str):
    """Search A-share symbols by code or name using efinance."""
    try:
        import efinance as ef
        df = await asyncio.to_thread(ef.stock.get_realtime_quotes)
        code_col = df.columns[1]
        name_col = df.columns[0]
        mask = (
            df[code_col].str.contains(query, case=False, na=False) |
            df[name_col].str.contains(query, na=False)
        )
        results = df[mask][[name_col, code_col]].head(20)
        return [
            {"symbol": row.iloc[1], "name": row.iloc[0],
             "exchange": detect_exchange(str(row.iloc[1])).value}
            for _, row in results.iterrows()
        ]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Search unavailable: {e}")


# ── Market overview endpoints ─────────────────────────────────────────────────

# Major A-share indices: (display_name, efinance_code)
_INDEX_LIST = [
    ("上证指数", "000001"),
    ("深证成指", "399001"),
    ("创业板指", "399006"),
    ("沪深300",  "000300"),
    ("中证500",  "000905"),
]


@router.get("/indices")
async def get_market_indices():
    """Return latest quotes for major A-share indices."""
    try:
        import efinance as ef

        results = []
        for name, code in _INDEX_LIST:
            try:
                df = await asyncio.to_thread(ef.stock.get_latest_quote, code)
                if df is None or df.empty:
                    results.append({"code": code, "name": name, "price": None, "change_pct": None, "change": None})
                    continue
                row = df.iloc[0]
                # get_latest_quote columns (positional): 0=code, 1=name, 2=涨跌幅, 3=最新价, 4=最高, 5=最低, 6=今开, 13=昨收
                price = float(row.iloc[3]) if row.iloc[3] not in (None, "-", "") else None
                change_pct = float(row.iloc[2]) if row.iloc[2] not in (None, "-", "") else None
                prev_close = float(row.iloc[13]) if row.iloc[13] not in (None, "-", "") else None
                change = round(price - prev_close, 2) if price is not None and prev_close is not None else None
                vol = float(row.iloc[7]) if len(row) > 7 and row.iloc[7] not in (None, "-", "") else None
                results.append({
                    "code": code, "name": name,
                    "price": price, "change_pct": change_pct, "change": change, "volume": vol,
                })
            except Exception:
                results.append({"code": code, "name": name, "price": None, "change_pct": None, "change": None})

        return {"indices": results}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/breadth")
async def get_market_breadth():
    """Return market breadth stats (up/down/flat counts, limit-up/down)."""
    try:
        import efinance as ef
        df = await asyncio.to_thread(ef.stock.get_realtime_quotes)
        if df is None or df.empty:
            raise HTTPException(status_code=503, detail="No realtime data")

        # Positional: 0=name, 1=code, 2=涨跌幅
        change_col = df.iloc[:, 2]
        change_vals = []
        for v in change_col:
            try:
                change_vals.append(float(v))
            except (TypeError, ValueError):
                pass

        import numpy as np
        vals = np.array(change_vals)
        up_count   = int((vals > 0.05).sum())
        down_count = int((vals < -0.05).sum())
        flat_count = int(((vals >= -0.05) & (vals <= 0.05)).sum())
        limit_up   = int((vals >= 9.9).sum())
        limit_down = int((vals <= -9.9).sum())
        total      = up_count + down_count + flat_count
        ratio      = round(up_count / down_count, 2) if down_count > 0 else None

        return {
            "up_count": up_count, "down_count": down_count, "flat_count": flat_count,
            "limit_up": limit_up, "limit_down": limit_down,
            "total": total, "advance_decline_ratio": ratio,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/movers")
async def get_market_movers(top: int = 20):
    """Return top gainers and losers from A-share universe."""
    try:
        import efinance as ef
        df = await asyncio.to_thread(ef.stock.get_realtime_quotes)
        if df is None or df.empty:
            raise HTTPException(status_code=503, detail="No realtime data")

        stocks = []
        for _, row in df.iterrows():
            try:
                name       = str(row.iloc[0])
                code       = str(row.iloc[1])
                change_pct = float(row.iloc[2])
                price      = float(row.iloc[3])
                stocks.append({"name": name, "code": code, "change_pct": change_pct, "price": price})
            except (TypeError, ValueError):
                continue

        # Return combined top/bottom (frontend sorts by mode)
        stocks.sort(key=lambda x: x["change_pct"], reverse=True)
        top_gainers = stocks[:top]
        top_losers  = stocks[-top:]
        combined    = {s["code"]: s for s in top_gainers + top_losers}

        return {"stocks": list(combined.values())}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── WebSocket ─────────────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict):
        for ws in list(self.active):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)


_manager = ConnectionManager()


@router.websocket("/ws")
async def market_ws(websocket: WebSocket):
    """WebSocket — push real-time quotes and portfolio updates every 5s.

    Client sends:
      {"action": "subscribe", "symbols": ["000001", "600519"]}
      {"action": "unsubscribe", "symbols": ["000001"]}
    Server pushes every 5s:
      {"type": "quotes", "data": {...}}
      {"type": "portfolio", "data": {...}}
    """
    from quantforge.api.deps import get_portfolio_manager

    await _manager.connect(websocket)
    mgr = get_portfolio_manager()

    async def push_loop():
        while True:
            await asyncio.sleep(5)
            try:
                rt = mgr._rt_stream
                quotes = rt.get_all_quotes() if rt else {}
                await websocket.send_json({"type": "quotes", "data": quotes})
                await websocket.send_json({"type": "portfolio", "data": mgr.aggregate_summary()})
            except Exception:
                break

    push_task = asyncio.create_task(push_loop())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                action = msg.get("action")
                symbols = msg.get("symbols", [])
                if action == "subscribe" and symbols:
                    for sym in symbols:
                        if mgr._rt_stream:
                            mgr._rt_stream.subscribe(sym, detect_exchange(sym))
                    await websocket.send_json({"type": "ack", "action": "subscribe", "symbols": symbols})
                elif action == "unsubscribe" and symbols:
                    for sym in symbols:
                        if mgr._rt_stream:
                            mgr._rt_stream.unsubscribe(sym)
                    await websocket.send_json({"type": "ack", "action": "unsubscribe"})
                else:
                    await websocket.send_json({"type": "ack"})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        push_task.cancel()
        _manager.disconnect(websocket)
