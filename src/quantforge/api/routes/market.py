"""Market data endpoints and WebSocket streaming."""

from __future__ import annotations

import asyncio
import json
import time
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

@router.get("/history")
async def get_history(
    symbol: str,
    start: str = "2024-01-01",
    end: str | None = None,
    engine=Depends(get_backtest_engine),
):
    """Get historical OHLCV data - simplified API for frontend.

    Returns array of {datetime, open, high, low, close, volume} objects.
    Tries local storage first; if not found, attempts to download from API.
    """
    exc = _resolve_exchange(symbol, None)
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()

    # Try local data first
    df = engine._data_manager.load_bars(symbol, Interval.DAILY, start_dt, end_dt)
    
    if df.empty:
        try:
            # Try to download if not found locally
            df = await engine._data_manager.download(
                symbol=symbol,
                interval=Interval.DAILY,
                start=start_dt,
                end=end_dt,
                exchange=exc,
            )
        except Exception as e:
            logger.warning(f"Failed to download {symbol}: {e}")
            # If download also fails, return empty array instead of 404
            return []
    
    records = df[["datetime", "open", "high", "low", "close", "volume"]].copy()
    records["datetime"] = records["datetime"].dt.strftime("%Y-%m-%d")
    return records.to_dict(orient="records")


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


def _tencent_intraday(symbol: str, date: str | None, klt: int, multiday: bool = False) -> list:
    """腾讯分钟K线（ifzq.gtimg.cn，已在代理白名单且不封）。

    东方财富 push2his 在本环境被服务器侧 RST（详见排查记录），分时改走腾讯。
    腾讯只回最近 ~320 根（约 7 个交易日），更早的历史日期取不到，返回空让调用方兜底。

    multiday=True 时不按单日过滤，返回全部（用于连续多日的分钟 K 线图）。
    """
    import urllib.request

    period = {1: "m1", 5: "m5", 15: "m15", 30: "m30", 60: "m60"}.get(klt, "m5")
    c = str(symbol).strip()
    if len(c) > 2 and c[:2].lower() in ("sh", "sz", "bj", "hk", "us"):
        tcode = c[:2].lower() + c[2:]   # 已带市场前缀(含指数码 sh000001)直接透传
    elif c.startswith(("6", "9")):
        tcode = f"sh{c}"
    elif c.startswith("8"):
        tcode = f"bj{c}"
    else:
        tcode = f"sz{c}"

    url = f"https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={tcode},{period},,320"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/",
        })
        raw = urllib.request.urlopen(req, timeout=6).read().decode("utf-8", "ignore")
        payload = json.loads(raw)
        rows = payload.get("data", {}).get(tcode, {}).get(period, []) or []
    except Exception as e:
        logger.warning(f"tencent intraday fetch failed for {symbol}: {e}")
        return []

    result = []
    for r in rows:
        try:
            ts = str(r[0])  # YYYYMMDDHHMM
            dt = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}"
            result.append({
                "datetime": dt,
                "open":   float(r[1]),
                "close":  float(r[2]),
                "high":   float(r[3]),
                "low":    float(r[4]),
                "volume": float(r[5]),
                "klt":    klt,
            })
        except (ValueError, IndexError, TypeError):
            continue

    if date:
        result = [x for x in result if x["datetime"][:10] == date]
    elif result and not multiday:
        last_date = result[-1]["datetime"][:10]
        result = [x for x in result if x["datetime"][:10] == last_date]
    return result


async def _fetch_intraday_bars(symbol: str, date: str | None, klt: int) -> list:
    """Fetch intraday bars: tries Tencent first, then efinance fallback."""
    # 腾讯优先（push2his 已不可用）
    bars = await asyncio.to_thread(_tencent_intraday, symbol, date, klt)
    if bars:
        return bars

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


# ── Sina all-A-share source (works behind proxies that hijack EastMoney) ──────

import re as _re
import urllib.request as _urlreq
from quantforge.data.storage import db_cache as _db

_SINA_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _sina_http(url: str) -> str:
    req = _urlreq.Request(url, headers={"User-Agent": _SINA_UA, "Referer": "https://finance.sina.com.cn"})
    return _urlreq.urlopen(req, timeout=12).read().decode("gbk", "replace")


def _sina_count(node: str) -> int:
    try:
        raw = _sina_http(
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"Market_Center.getHQNodeStockCount?node={node}"
        )
        m = _re.search(r"\d+", raw)
        return int(m.group()) if m else 0
    except Exception:
        return 0


def _sina_page(node: str, page: int, num: int = 100) -> list[dict]:
    url = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"Market_Center.getHQNodeData?page={page}&num={num}&sort=symbol&asc=1&node={node}&_s_r_a=page"
    )
    try:
        arr = json.loads(_sina_http(url))
    except Exception:
        return []
    def _f(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    out = []
    for s in arr:
        try:
            sym = str(s.get("symbol", ""))
            # Pre-market Sina returns trade=0; fall back to 昨收(settlement).
            price = _f(s.get("trade"))
            if not price:
                price = _f(s.get("settlement"))
            out.append({
                "code":          str(s.get("code", "")).strip(),
                "name":          s.get("name", ""),
                "price":         price,
                "change_pct":    float(s["changepercent"]) if s.get("changepercent") not in (None, "") else None,
                "turnover_rate": float(s["turnoverratio"]) if s.get("turnoverratio") not in (None, "") else None,
                "pe":            float(s["per"]) if s.get("per") not in (None, "") else None,
                "pb":            float(s["pb"]) if s.get("pb") not in (None, "") else None,
                "market_cap":    float(s["mktcap"]) * 10000 if s.get("mktcap") else None,
                "exchange":      "SH" if sym.startswith("sh") else ("SZ" if sym.startswith("sz") else ""),
            })
        except Exception:
            continue
    return out


async def _sina_all_stocks() -> list[dict]:
    """All A-shares from Sina (cached 10 min)."""
    ck = "market:all_stocks_sina"
    cached = _db.get(ck, 600)
    if cached:
        return cached.get("stocks", [])
    count = await asyncio.to_thread(_sina_count, "hs_a")
    if not count:
        stale = _db.get_stale(ck)
        return stale.get("stocks", []) if stale else []
    pages = (count + 99) // 100
    sem = asyncio.Semaphore(8)

    async def fetch(p: int) -> list[dict]:
        async with sem:
            return await asyncio.to_thread(_sina_page, "hs_a", p, 100)

    results = await asyncio.gather(*[fetch(p) for p in range(1, pages + 1)])
    stocks = [s for r in results for s in r if s.get("code")]
    if stocks:
        _db.set(ck, {"stocks": stocks}, 600, category="market")
    return stocks


@router.get("/datasource-status")
async def datasource_status():
    """当前生效的数据源（iFinD 优先，回退新浪/腾讯）。"""
    from quantforge.data.feed import datasource
    return datasource.status()


# ── 腾讯单股行情 + K线（gtimg，绕开被劫持的东财）────────────────────────────

def _qq_prefixed(code: str) -> str:
    c = code.strip()
    # 港/美市场码(hkHSI/usDJI)直接透传：前缀小写、后段保留原大小写
    if len(c) > 2 and c[:2].lower() in ("hk", "us"):
        return c[:2].lower() + c[2:]
    c = c.upper()
    for p in ("SH", "SZ", "BJ"):
        if c.startswith(p):
            return p.lower() + c[2:]
    if c.startswith(("6", "9")):
        return "sh" + c
    if c.startswith("8") or c.startswith("4"):
        return "bj" + c
    return "sz" + c


def _tencent_kline(code: str, period: str = "day", count: int = 320) -> list[dict]:
    """腾讯前复权 K 线。period ∈ {day, week, month}。

    注意：用 `ifzq.gtimg.cn`（**不带 web. 前缀**）——`web.ifzq.gtimg.cn` 子域名
    已对该接口返回 501 Not Implemented，裸 `ifzq.gtimg.cn` 同接口正常。
    上游异常时回退新浪日 K（_sina_kline）。
    """
    sym = _qq_prefixed(code)
    period = period if period in ("day", "week", "month") else "day"
    # 美股/美指历史 K 要走 usfqkline，fqkline 对 us 码只回最新一根
    api = "usfqkline" if sym.startswith("us") else "fqkline"
    url = (
        f"https://ifzq.gtimg.cn/appstock/app/{api}/get"
        f"?param={sym},{period},,,{int(count)},qfq"
    )
    try:
        req = _urlreq.Request(url, headers={"User-Agent": _SINA_UA, "Referer": "https://gu.qq.com/"})
        raw = _urlreq.urlopen(req, timeout=12).read().decode("utf-8", "replace")
        node = (json.loads(raw).get("data") or {}).get(sym) or {}
        rows = node.get(f"qfq{period}") or node.get(period) or []
        out = []
        for r in rows:
            # 腾讯顺序: [日期, 开, 收, 高, 低, 成交量(手)]
            if len(r) < 6:
                continue
            try:
                out.append({
                    "datetime": r[0],
                    "open": float(r[1]), "close": float(r[2]),
                    "high": float(r[3]), "low": float(r[4]),
                    "volume": float(r[5]),
                })
            except (TypeError, ValueError):
                continue
        if out:
            return out
    except Exception as e:
        logger.debug(f"_tencent_kline {code} failed, fallback to sina: {e}")
    if sym.startswith(("hk", "us")):
        return []   # 新浪 CN_MarketData 只有 A 股，港美码兜底无意义
    return _sina_kline(code, period, count)


# 新浪日/周 K 兜底：腾讯接口不可用时仍能出图（前复权由 sina 自带，scale 240=日线）
_SINA_KLINE_SCALE = {"day": 240, "week": 1680, "month": 7200}


def _sina_kline(code: str, period: str = "day", count: int = 320) -> list[dict]:
    """新浪 K 线兜底。返回字段同 _tencent_kline。"""
    sym = _qq_prefixed(code)
    scale = _SINA_KLINE_SCALE.get(period, 240)
    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={sym}&scale={scale}&ma=no&datalen={int(count)}"
    )
    try:
        req = _urlreq.Request(url, headers={"User-Agent": _SINA_UA, "Referer": "https://finance.sina.com.cn/"})
        raw = _urlreq.urlopen(req, timeout=12).read().decode("utf-8", "replace")
        rows = json.loads(raw) or []
    except Exception as e:
        logger.debug(f"_sina_kline {code} failed: {e}")
        return []
    out = []
    for r in rows:
        try:
            out.append({
                "datetime": r["day"],
                "open": float(r["open"]), "close": float(r["close"]),
                "high": float(r["high"]), "low": float(r["low"]),
                "volume": float(r["volume"]),
            })
        except (TypeError, ValueError, KeyError):
            continue
    return out


@router.get("/quote/{code}")
async def get_quote(code: str):
    """单股实时行情(丰富指标)，经数据源门面(iFinD→腾讯)。"""
    from quantforge.data.feed import datasource
    code = code.strip().upper()
    plain = code
    for p in ("SH", "SZ", "BJ"):
        if plain.startswith(p):
            plain = plain[2:]
    q = await asyncio.to_thread(datasource.quotes, [plain])
    item = q.get(plain) or (next(iter(q.values())) if q else None)
    if not item:
        raise HTTPException(status_code=503, detail="行情获取失败")
    return {"code": plain, **item}


# ── Daily K-line cache (Tencent 前复权，落 db_cache，提前拉到本地)────────────

def _kline_meta_key(code: str, period: str) -> str:
    """新鲜度标记键（记录上次成功刷新时间，按交易时段控制刷新频率）。"""
    return f"market:kline:meta:{code.strip().upper()}:{period}"


def _kline_read_ttl() -> int:
    """新鲜度窗口：A 股交易时段 2min，盘后/休市 1h（历史 K 线基本不变）。"""
    from quantforge.data.feed.snapshot import is_trade_hours
    return 120 if is_trade_hours() else 3600


def _kline_fetch(code: str, period: str, count: int) -> list[dict]:
    """iFinD 优先，回退腾讯前复权 K 线。"""
    from quantforge.data.feed import datasource
    bars = datasource.kline(code, "", "")  # iFinD 优先(目前返回 None)
    if not bars:
        bars = _tencent_kline(code, period, count)
    return bars or []


async def _kline_cached(code: str, period: str = "day", count: int = 320) -> tuple[list[dict], bool]:
    """日/周/月 K 线：DB 优先 + 增量更新；返回 (bars, cached)。

    历史 K 线不会变，所以一旦本地表里有了，刷新只补**最近少量**几根（覆盖新
    交易日 + 当日未收盘那根的滚动更新），绝不重拉整段历史。新鲜度按交易时段
    控制（盘中 2min / 盘后 1h）。上游失败时直接返回本地已有，保证图表不空。
    """
    code = code.strip().upper()
    period = period if period in ("day", "week", "month") else "day"

    existing = await asyncio.to_thread(_db.kline_load, code, period)
    fresh_mark = await asyncio.to_thread(_db.get, _kline_meta_key(code, period), _kline_read_ttl())
    # 库里根数已够请求量且新鲜 → 直接用；不够（如首灌时只取了少量）则即便新鲜也要回拉补齐
    if existing and len(existing) >= count and fresh_mark:
        return existing[-count:], True

    # 库里历史足够 → 只补最近 8 根（增量）；库里没有/不足请求量 → 拉满 count 根
    fetch_count = count if len(existing) < count else 8
    bars = await asyncio.to_thread(_kline_fetch, code, period, fetch_count)
    if bars:
        await asyncio.to_thread(_db.kline_upsert, code, period, bars)
        await asyncio.to_thread(_db.set, _kline_meta_key(code, period), {"ok": 1}, 86400, "market_kline_meta")
        merged = await asyncio.to_thread(_db.kline_load, code, period)
        return merged[-count:], False

    if existing:
        return existing[-count:], True
    return [], False


_MINUTE_PERIODS = {"m1": 1, "m5": 5, "m15": 15, "m30": 30, "m60": 60}


@router.get("/kline/{code}")
async def get_kline(code: str, period: str = "day", count: int = 320):
    """单股 K 线。日/周/月走 DB 增量；分钟级(m5/m15/m30/m60)走腾讯多日分钟K(短缓存)。"""
    if period in _MINUTE_PERIODS:
        klt = _MINUTE_PERIODS[period]
        key = f"market:mkline:{code.strip().upper()}:{period}"
        cached = await asyncio.to_thread(_db.get, key, _kline_read_ttl())
        if cached and cached.get("bars"):
            return {"code": code, "period": period, "count": len(cached["bars"]),
                    "bars": cached["bars"], "cached": True}
        bars = await asyncio.to_thread(_tencent_intraday, code, None, klt, True)
        if bars:
            await asyncio.to_thread(_db.set, key, {"bars": bars}, 86400, "market_mkline")
            return {"code": code, "period": period, "count": len(bars), "bars": bars, "cached": False}
        stale = await asyncio.to_thread(_db.get_stale, key)
        if stale and stale.get("bars"):
            return {"code": code, "period": period, "count": len(stale["bars"]),
                    "bars": stale["bars"], "cached": True}
        return {"code": code, "period": period, "count": 0, "bars": [], "cached": False}

    bars, cached = await _kline_cached(code, period, count)
    return {"code": code, "period": period, "count": len(bars),
            "bars": bars, "cached": cached}


async def prewarm_watchlist_klines() -> int:
    """提前把所有自选股的日 K 线拉到本地缓存，让首次打开自选页即时出图。"""
    codes = await asyncio.to_thread(_db.watchlist_all_codes)
    if not codes:
        return 0
    sem = asyncio.Semaphore(6)

    async def _one(c: str):
        async with sem:
            try:
                await _kline_cached(c, "day", 120)
            except Exception:
                pass

    await asyncio.gather(*[_one(c) for c in codes])
    return len(codes)


async def watchlist_kline_warmer() -> None:
    """后台循环：周期性预热自选股 K 线（交易时段 3min，盘后 30min）。"""
    from quantforge.data.feed.snapshot import is_trade_hours
    logger.info("market.watchlist_kline_warmer: starting watchlist K-line prewarmer")
    while True:
        try:
            n = await prewarm_watchlist_klines()
            if n:
                logger.info(f"watchlist kline warmer: prewarmed {n} codes")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"watchlist kline warmer error: {e}")
        await asyncio.sleep(180 if is_trade_hours() else 1800)


# ── 全市场 K 线预热（供 AI 荐股全市场扫描读缓存用）────────────────────────────────
#
# 荐股扫描要覆盖全市场就不能现拉 5000 只 K 线（慢 + 限流）。这里用一个低速后台
# 预热器把全市场日 K 线分批灌进 stock_kline 表，扫描时只读缓存。历史 K 线一旦落库
# 就基本不变，每日只增量补最近几根，所以稳态下很轻。

_MARKET_KLINE_CONCURRENCY = 5    # 并发，压低防腾讯限流
_MARKET_KLINE_BATCH = 60         # 每批数量，批间歇缓口气
_MARKET_KLINE_BATCH_PAUSE = 3.0  # 批间停顿秒


async def _market_codes_from_snapshot() -> list[str]:
    """从行情快照取全市场代码（剔除 ST/退市），作为预热与扫描的全集。"""
    codes: list[str] = []
    page = 1
    while True:
        rows, total = await asyncio.to_thread(
            _db.quote_query, page=page, page_size=500
        )
        if not rows:
            break
        for r in rows:
            code = (r.get("code") or "").strip()
            name = (r.get("name") or "")
            if not code or "ST" in name.upper() or "退" in name:
                continue
            codes.append(code.upper())
        if len(codes) >= total or len(rows) < 500:
            break
        page += 1
    return codes


async def prewarm_market_klines(limit: int | None = None) -> tuple[int, int]:
    """分批预热全市场日 K 线。返回 (尝试数, 成功落库/已缓存数)。

    低速、限流友好：每批 ``_MARKET_KLINE_BATCH`` 只、批间停顿。已新鲜的直接命中
    缓存（_kline_cached 返回 cached=True），不会重复打上游。
    """
    codes = await _market_codes_from_snapshot()
    if not codes:
        return 0, 0
    if limit:
        codes = codes[:limit]

    sem = asyncio.Semaphore(_MARKET_KLINE_CONCURRENCY)
    ok = 0

    async def _one(c: str) -> bool:
        async with sem:
            try:
                bars, _cached = await _kline_cached(c, "day", 200)
                return bool(bars)
            except Exception:
                return False

    for i in range(0, len(codes), _MARKET_KLINE_BATCH):
        batch = codes[i : i + _MARKET_KLINE_BATCH]
        results = await asyncio.gather(*[_one(c) for c in batch])
        ok += sum(1 for r in results if r)
        if i + _MARKET_KLINE_BATCH < len(codes):
            await asyncio.sleep(_MARKET_KLINE_BATCH_PAUSE)

    return len(codes), ok


async def market_kline_warmer() -> None:
    """后台循环：全市场日 K 线预热。

    首轮开机即灌一遍（耗时较长但低速），之后每日一次增量（盘后跑，盘中不抢带宽）。
    """
    from quantforge.data.feed.snapshot import is_trade_hours
    logger.info("market.market_kline_warmer: starting full-market K-line prewarmer")
    while True:
        try:
            attempted, ok = await prewarm_market_klines()
            if attempted:
                logger.info(f"market kline warmer: warmed {ok}/{attempted} codes")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"market kline warmer error: {e}")
        # 盘中不跑全量（避免和快照/自选预热抢上游），等到盘后；稳态每 6h 增量一次。
        await asyncio.sleep(1800 if is_trade_hours() else 6 * 3600)


class KlineBatchRequest(BaseModel):
    codes: List[str]
    period: str = "day"
    count: int = 120


@router.post("/kline-batch")
async def kline_batch(req: KlineBatchRequest):
    """批量预取/返回多只股票的 K 线（用于自选股迷你走势图，一次拉到本地）。"""
    codes = [c.strip().upper() for c in (req.codes or []) if c.strip()][:100]
    sem = asyncio.Semaphore(8)
    out: dict = {}

    async def _one(c: str):
        async with sem:
            try:
                bars, _ = await _kline_cached(c, req.period, req.count)
                out[c] = bars
            except Exception as e:
                logger.debug(f"kline-batch {c} failed: {e}")
                out[c] = []

    await asyncio.gather(*[_one(c) for c in codes])
    return {"period": req.period, "count": len(out), "data": out}


def _em_secid(code: str) -> str:
    """东财 secid：1.<沪/科创>，0.<深/创/京>。"""
    c = code.strip().upper()
    for p in ("SH", "SZ", "BJ"):
        if c.startswith(p):
            c = c[2:]
            break
    return ("1." if c.startswith(("6", "9")) else "0.") + c


def _tencent_minute(code: str) -> dict:
    """腾讯当日分时：返回 {pre_close, date, points:[{time, price, avg, volume}]}。

    接口: web.ifzq.gtimg.cn/appstock/app/minute/query?code=sh600519
    每条形如 "0930 12.34 100 74124000.00"(时间 价 量 累计成交额)。
    注意第 4 段是当日累计成交额(元)而非均价，均价需用 累计额/累计量 自算。
    """
    sym = _qq_prefixed(code)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={sym}"
    req = _urlreq.Request(url, headers={"User-Agent": _SINA_UA, "Referer": "https://gu.qq.com/"})
    raw = _urlreq.urlopen(req, timeout=12).read().decode("utf-8", "replace")
    node = (json.loads(raw).get("data") or {}).get(sym) or {}
    md = node.get("data") or {}
    qt = (node.get("qt") or {}).get(sym) or []
    pre_close = None
    try:
        pre_close = float(qt[4]) if len(qt) > 4 and qt[4] not in ("", None) else None
    except (TypeError, ValueError):
        pre_close = None

    cum_amt = 0.0      # 累计成交额(元)
    cum_vol = 0.0      # 累计成交量(手)
    points = []
    for line in (md.get("data") or []):
        parts = str(line).split()
        if len(parts) < 2:
            continue
        try:
            tm = parts[0]
            price = float(parts[1])
            vol = float(parts[2]) if len(parts) > 2 and parts[2] not in ("", None) else 0.0
            # 第 3 段是单笔量(手)，第 4 段是单笔成交额(元)，均非均价。
            # 当日均价 = 累计额 / (累计量 * 100)，1 手 = 100 股。
            cum_vol += vol
            if len(parts) > 3 and parts[3] not in ("", None):
                cum_amt += float(parts[3])
            else:
                cum_amt += price * vol * 100.0
            avg = round(cum_amt / (cum_vol * 100.0), 3) if cum_vol else price
            points.append({"time": tm, "price": price, "avg": avg, "volume": vol})
        except (TypeError, ValueError):
            continue
    return {"pre_close": pre_close, "date": md.get("date"), "points": points}


def _eastmoney_minute(code: str) -> dict:
    """东财当日分时(trends2)：数据最干净，均价已合并。

    接口: push2.eastmoney.com/api/qt/stock/trends2/get?secid=1.600519
    每条形如 "2026-06-05 09:30,1278.00,580,1278.000"(时间,价,量,均价)。
    """
    secid = _em_secid(code)
    url = (
        f"https://push2.eastmoney.com/api/qt/stock/trends2/get"
        f"?secid={secid}&fields1=f1,f8&fields2=f51,f53,f56,f58&ndays=1&iscr=0"
    )
    req = _urlreq.Request(url, headers={"User-Agent": _SINA_UA, "Referer": "https://quote.eastmoney.com/"})
    raw = _urlreq.urlopen(req, timeout=12).read().decode("utf-8", "replace")
    data = (json.loads(raw) or {}).get("data") or {}
    pre_close = data.get("preClose")
    try:
        pre_close = float(pre_close) if pre_close not in ("", None) else None
    except (TypeError, ValueError):
        pre_close = None

    points = []
    date = None
    for line in (data.get("trends") or []):
        parts = str(line).split(",")
        if len(parts) < 3:
            continue
        try:
            ts = parts[0]                         # "2026-06-05 09:30"
            date = ts.split(" ")[0]
            tm = ts.split(" ")[1].replace(":", "")[:4] if " " in ts else ts
            price = float(parts[1])
            vol = float(parts[2]) if parts[2] not in ("", None) else 0.0
            avg = float(parts[3]) if len(parts) > 3 and parts[3] not in ("", None) else price
            points.append({"time": tm, "price": price, "avg": avg, "volume": vol})
        except (TypeError, ValueError):
            continue
    return {"pre_close": pre_close, "date": date, "points": points}


def _sina_minute(code: str) -> dict:
    """新浪当日分时(Minline)：含 09:25 集合竞价点。

    接口: quotes.sina.cn/.../CN_MinlineService.getMinlineData?symbol=sh600519
    每条形如 {"m":"09:30:00","v":"105211","p":"1277.99","avg_p":"1278.222"}。
    pre_close 该接口不提供，留空交由前端用首点兜底。
    """
    sym = _qq_prefixed(code)
    url = (
        f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MinlineService.getMinlineData"
        f"?symbol={sym}"
    )
    req = _urlreq.Request(url, headers={"User-Agent": _SINA_UA, "Referer": "https://finance.sina.com.cn/"})
    raw = _urlreq.urlopen(req, timeout=12).read().decode("utf-8", "replace")
    rows = json.loads(raw) or []
    points = []
    for it in rows:
        try:
            tm = str(it.get("m", "")).replace(":", "")[:4]
            price = float(it["p"])
            vol = float(it.get("v") or 0.0)
            avg = float(it.get("avg_p") or price)
            points.append({"time": tm, "price": price, "avg": avg, "volume": vol})
        except (TypeError, ValueError, KeyError):
            continue
    return {"pre_close": None, "date": None, "points": points}


def _minute_with_fallback(code: str) -> dict:
    """当日分时多源回退：腾讯 → 东财 → 新浪，返回首个非空 points 的结果。"""
    sources = (
        ("tencent", _tencent_minute),
        ("eastmoney", _eastmoney_minute),
        ("sina", _sina_minute),
    )
    last_err = None
    for name, fn in sources:
        try:
            data = fn(code)
            if data.get("points"):
                return {**data, "source": name}
        except Exception as exc:  # 单源失败不影响后续兜底
            last_err = f"{name}: {exc}"
            continue
    return {"pre_close": None, "date": None, "points": [], "source": None, "error": last_err}


@router.get("/minute/{code}")
async def get_minute(code: str):
    """单股当日分时(腾讯→东财→新浪三级回退)。"""
    data = await asyncio.to_thread(_minute_with_fallback, code)
    return {"code": code, **data, "count": len(data.get("points", []))}


class MinuteBatchRequest(BaseModel):
    codes: List[str]


@router.post("/minute-batch")
async def minute_batch(req: MinuteBatchRequest):
    """批量当日分时(用于自选股迷你走势图)。并发三级回退，返回每只的分时点序列。

    分时点统一映射为 ``{time, close, avg}``，``close`` 复用迷你图既有的收盘价字段，
    前端无需区分日/分时即可直接绘制。"""
    codes = [c.strip().upper() for c in (req.codes or []) if c.strip()][:100]
    sem = asyncio.Semaphore(8)
    out: dict = {}
    pre: dict = {}      # code -> 昨收(基准价)，供前端分时图基准线/着色

    async def _one(c: str):
        async with sem:
            try:
                data = await asyncio.to_thread(_minute_with_fallback, c)
                pts = data.get("points") or []
                out[c] = [
                    {"time": p["time"], "close": p["price"], "avg": p.get("avg")}
                    for p in pts
                ]
                if data.get("pre_close") is not None:
                    pre[c] = data["pre_close"]
            except Exception as e:
                logger.debug(f"minute-batch {c} failed: {e}")
                out[c] = []

    await asyncio.gather(*[_one(c) for c in codes])
    return {"count": len(out), "data": out, "pre_close": pre}


# ── 主力资金流(东财 push2 ulist) ───────────────────────────────────────────────
# 字段：f62 主力净额(元) / f184 主力净占比% / f66 超大单净额 / f69 超大单净占比%
#       f72 大单净额 / f75 大单净占比% / f78 中单净额 / f84 小单净额
_FF_FIELDS = "f12,f14,f62,f184,f66,f69,f72,f75,f78,f84"
_ff_cache: dict[str, tuple[float, dict]] = {}   # code -> (ts, fields)


def _ff_ttl() -> int:
    """资金流新鲜度：盘中 60s / 盘后 30min（资金流盘后不再变）。"""
    from quantforge.data.feed.snapshot import is_trade_hours
    return 60 if is_trade_hours() else 1800


def _ff_num(v):
    return None if v in ("", None, "-") else float(v)


def _fund_flow_push2(codes: list[str]) -> dict[str, dict]:
    """东财 push2 ulist 批量(单请求 ≤60 只)。服务器(无代理劫持)可用；本机常被 RST。

    push2 返回 6 位 code，统一映射回调用方传入的原始 code 形式(可能带 SH/SZ 前缀)。
    """
    out: dict[str, dict] = {}
    by6 = {_em6_for_ff(c): c for c in codes}     # 6位 → 原始输入 code
    secids = [_em_secid(c) for c in codes]
    for i in range(0, len(secids), 60):
        chunk = secids[i:i + 60]
        url = (
            "https://push2.eastmoney.com/api/qt/ulist.np/get"
            f"?fltt=2&secids={','.join(chunk)}&fields={_FF_FIELDS}"
        )
        try:
            req = _urlreq.Request(url, headers={"User-Agent": _SINA_UA, "Referer": "https://quote.eastmoney.com/"})
            raw = _urlreq.urlopen(req, timeout=8).read().decode("utf-8", "replace")
            diff = ((json.loads(raw) or {}).get("data") or {}).get("diff") or []
        except Exception as e:
            logger.debug(f"fund-flow push2 chunk failed: {e}")
            continue
        for row in diff:
            code6 = str(row.get("f12") or "").upper()
            if not code6:
                continue
            code = by6.get(code6, code6)
            out[code] = {
                "main_net":   _ff_num(row.get("f62")),
                "main_pct":   _ff_num(row.get("f184")),
                "super_net":  _ff_num(row.get("f66")),
                "super_pct":  _ff_num(row.get("f69")),
                "big_net":    _ff_num(row.get("f72")),
                "big_pct":    _ff_num(row.get("f75")),
                "mid_net":    _ff_num(row.get("f78")),
                "small_net":  _ff_num(row.get("f84")),
                "src": "em",
            }
    return out


def _fund_flow_sina_one(code: str) -> dict | None:
    """新浪个股资金流(最近交易日)。本机 python 可直连；逐只请求。

    字段：netamount 主力净额(元)、ratioamount 主力净占比(小数)、r0_net 超大单净额、
    r0_ratio 超大单净占比(小数)。无大/中/小单细分(留空)。
    """
    sym = _qq_prefixed(code)   # 形如 sh600519
    url = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"MoneyFlow.ssl_qsfx_zjlrqs?page=1&num=1&sort=opendate&asc=0&daima={sym}"
    )
    try:
        req = _urlreq.Request(url, headers={"User-Agent": _SINA_UA, "Referer": "https://finance.sina.com.cn/"})
        raw = _urlreq.urlopen(req, timeout=8).read().decode("utf-8", "replace")
        rows = json.loads(raw) or []
    except Exception as e:
        logger.debug(f"fund-flow sina {code} failed: {e}")
        return None
    if not rows:
        return None
    r = rows[0]
    main_pct = _ff_num(r.get("ratioamount"))
    super_pct = _ff_num(r.get("r0_ratio"))
    return {
        "main_net":  _ff_num(r.get("netamount")),
        "main_pct":  round(main_pct * 100, 2) if main_pct is not None else None,
        "super_net": _ff_num(r.get("r0_net")),
        "super_pct": round(super_pct * 100, 2) if super_pct is not None else None,
        "big_net": None, "big_pct": None, "mid_net": None, "small_net": None,
        "src": "sina", "date": r.get("opendate"),
    }


def _fund_flow_fetch(codes: list[str]) -> dict[str, dict]:
    """主力资金流多源：先试东财 push2 批量，缺失的逐只回退新浪。

    设计意图：线上百度云服务器无代理劫持→push2 一次批量拿全(实时盘中)；本机
    push2 被 RST→自动落到新浪(最近交易日，逐只并发)。两环境都能出数据。
    """
    codes = [c.strip().upper() for c in codes if c.strip()]
    out = _fund_flow_push2(codes)
    missing = [c for c in codes if c not in out]
    if missing:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as ex:
            for c, res in zip(missing, ex.map(_fund_flow_sina_one, missing)):
                if res:
                    out[c] = res
    return out


def _em6_for_ff(code: str) -> str:
    """push2 返回的是 6 位 code；自选 code 可能带前缀，统一比对用。"""
    c = code.strip().upper()
    for p in ("SH", "SZ", "BJ"):
        if c.startswith(p):
            return c[2:]
    return c


async def fund_flow_map(codes: list[str]) -> dict[str, dict]:
    """带进程内缓存的批量资金流(供自选 overview / 端点共用)。"""
    codes = [c.strip().upper() for c in codes if c.strip()]
    if not codes:
        return {}
    now = time.time()
    ttl = _ff_ttl()
    fresh = {c: v for c in codes
             for ts, v in [_ff_cache.get(c, (0, None))] if v is not None and now - ts <= ttl}
    missing = [c for c in codes if c not in fresh]
    if missing:
        fetched = await asyncio.to_thread(_fund_flow_fetch, missing)
        for c, v in fetched.items():
            _ff_cache[c] = (now, v)
            fresh[c] = v
    return {c: fresh[c] for c in codes if c in fresh}


class FundFlowRequest(BaseModel):
    codes: List[str]


@router.post("/fund-flow")
async def get_fund_flow(req: FundFlowRequest):
    """批量主力资金流(自选列用)。返回 {code:{main_net,main_pct,super_net,...}}。"""
    data = await fund_flow_map([c for c in (req.codes or [])][:200])
    return {"count": len(data), "data": data}


async def _seed_all_stocks_into_quote() -> int:
    """Cold-start fallback: if ``stock_quote`` is empty, do a one-shot snapshot
    refresh in the background so the next request is served from SQL."""
    from quantforge.data.feed import snapshot
    asyncio.create_task(snapshot.refresh_once())
    return 0


@router.get("/all-stocks")
async def get_all_stocks(
    sort_by: str = "code",            # code, name, change_pct, price, turnover, ...
    order: str = "asc",               # asc, desc
    page: int = 1,
    page_size: int = 50,
    filter_type: str | None = None,   # gainers, losers
    search: str | None = None,        # code/name substring
):
    """All A-shares served from the local ``stock_quote`` snapshot.

    Sorting / filtering / search / pagination are done SQL-side over indexed
    columns, so this returns in <1s regardless of universe size and never blocks
    on upstream APIs (the snapshot is refreshed by a background task).
    """
    rows, total = await asyncio.to_thread(
        _db.quote_query,
        sort_by=sort_by, order=order, filter_type=filter_type,
        search=search, page=page, page_size=page_size,
    )

    warming = False
    if total == 0 and _db.quote_count() == 0:
        # Cold start — table not populated yet. Trigger a background refresh and
        # serve whatever Sina can give us this once so the page isn't empty.
        warming = True
        await _seed_all_stocks_into_quote()
        legacy = await _sina_all_stocks()
        if legacy:
            if filter_type in ("gainers", "losers"):
                legacy = [s for s in legacy if s.get("change_pct") is not None]
                legacy.sort(key=lambda x: x.get("change_pct") or 0,
                            reverse=(filter_type == "gainers"))
            total = len(legacy)
            start = (max(1, page) - 1) * page_size
            rows = legacy[start:start + page_size]

    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "stocks": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "updated_at": _db.quote_max_updated(),
        "warming": warming,
    }


# ── Market overview endpoints ─────────────────────────────────────────────────

# 指数列表：(display_name, out_code, source, raw_code)
# - source="tx" 走腾讯 qt.gtimg.cn；source="sina" 走新浪 hq.sinajs.cn
# 注意：东财(efinance)在本环境被代理劫持不可用，改用腾讯/新浪行情。
# A股+港美股腾讯可取；日经/韩股腾讯无数据，改用新浪 znb_ 前缀。
_INDEX_LIST = [
    ("上证指数", "000001", "tx", "sh000001"),
    ("深证成指", "399001", "tx", "sz399001"),
    ("创业板指", "399006", "tx", "sz399006"),
    ("科创50",   "000688", "tx", "sh000688"),
    ("北证50",   "899050", "tx", "bj899050"),
    ("沪深300",  "000300", "tx", "sh000300"),
    ("中证500",  "000905", "tx", "sh000905"),
    ("中证1000", "000852", "tx", "sh000852"),
    ("道琼斯",   "DJI",    "tx", "usDJI"),
    ("纳斯达克", "IXIC",   "tx", "usIXIC"),
    ("标普500",  "INX",    "tx", "usINX"),
    ("恒生指数", "HSI",    "tx", "hkHSI"),
    ("日经225",  "N225",   "sina", "znb_NKY"),
    ("韩国综合", "KOSPI",  "sina", "znb_KOSPI"),
]


def _http_get(url: str, *, referer: str, encoding: str = "gbk") -> str:
    """单次 GET，双 scheme 回退 + 短超时，避免上游不可用时挂住请求线程。"""
    import urllib.request

    for scheme in ("http", "https"):
        try:
            full = url if url.startswith("http") else f"{scheme}://{url}"
            req = urllib.request.Request(full)
            req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
            req.add_header("Referer", referer)
            data = urllib.request.urlopen(req, timeout=5).read().decode(encoding, "replace")
            if data:
                return data
        except Exception:
            continue
    return ""


def _fetch_index_quotes() -> dict[str, dict]:
    """拉取所有指数行情。返回 {raw_code: {price, change_amt, change_pct}}。

    A股/港美股走腾讯(qt.gtimg.cn)，日经/韩股走新浪(hq.sinajs.cn)；两源各一次
    批量请求，任一源失败只影响该组指数，不阻塞其余。
    """
    out: dict[str, dict] = {}

    # ── 腾讯组 ──────────────────────────────────────────────────────────
    tx_codes = [raw for _, _, src, raw in _INDEX_LIST if src == "tx"]
    if tx_codes:
        data = _http_get("qt.gtimg.cn/q=" + ",".join(tx_codes), referer="https://gu.qq.com/")
        for line in data.strip().split(";"):
            if not line.strip() or "=" not in line or '"' not in line:
                continue
            key = line.split("=")[0].split("_")[-1]   # v_sh000001 -> sh000001
            vals = line.split('"')[1].split("~")
            if len(vals) < 33:
                continue
            out[key] = {
                "price": float(vals[3]) if vals[3] else None,
                "change_amt": float(vals[31]) if vals[31] else None,
                "change_pct": float(vals[32]) if vals[32] else None,
            }

    # ── 新浪组（日经/韩股）──────────────────────────────────────────────
    # 格式: hq_str_znb_NKY="名称,现价,涨跌额,涨跌幅,..."
    sina_codes = [raw for _, _, src, raw in _INDEX_LIST if src == "sina"]
    if sina_codes:
        data = _http_get("hq.sinajs.cn/list=" + ",".join(sina_codes),
                         referer="https://finance.sina.com.cn")
        for line in data.strip().split(";"):
            if "hq_str_" not in line or '"' not in line:
                continue
            key = line.split("=")[0].replace("var hq_str_", "").strip()
            vals = line.split('"')[1].split(",")
            if len(vals) < 4:
                continue
            try:
                out[key] = {
                    "price": float(vals[1]) if vals[1] else None,
                    "change_amt": float(vals[2]) if vals[2] else None,
                    "change_pct": float(vals[3]) if vals[3] else None,
                }
            except ValueError:
                continue
    return out


def _index_chart_caps(src: str, raw: str) -> tuple[str | None, bool, bool]:
    """指数详情图能力: (chart_code, 分时可用, 分钟K可用)。

    实测(2026-06): A股指数腾讯分时/分钟K/日K全有; 恒指有分时+日K但 mkline
    报 param error; 美指日K要 usfqkline、分时只回 1 个点; 日经/韩指(新浪
    znb_)无任何 K 线源。chart_code=None 表示前端不可点开详情。
    """
    if src != "tx":
        return None, False, False
    if raw.startswith(("sh", "sz", "bj")):
        return raw, True, True
    if raw.startswith("hk"):
        return raw, True, False
    return raw, False, False    # us*


@router.get("/indices")
async def get_market_indices():
    """Return latest quotes for major A-share indices (腾讯源；东财被劫持不可用)。"""
    quotes = await asyncio.to_thread(_fetch_index_quotes)
    results = []
    for name, out_code, src, raw in _INDEX_LIST:
        q = quotes.get(raw) or {}
        chart_code, chart_minute, chart_mkline = _index_chart_caps(src, raw)
        results.append({
            "code": out_code, "name": name,
            "price": q.get("price"),
            "change_pct": q.get("change_pct"),
            "change": q.get("change_amt"),
            "chart_code": chart_code,
            "chart_minute": chart_minute,
            "chart_mkline": chart_mkline,
        })
    return {"indices": results}


@router.get("/breadth")
async def get_market_breadth():
    """全市场宽度(涨/跌/平、涨跌停、涨跌比)。

    数据走本地 Sina 全市场快照(stock_quote 表 SQL 聚合，<50ms)，不再现拉
    efinance 全市场——后者在本环境直连东财被劫持不可用。快照由后台刷新器维护。
    冷启动快照为空时回退到 efinance(一次性，可能失败)。
    """
    dist = await asyncio.to_thread(_db.quote_distribution)
    if dist:
        return {
            "up_count": dist["up_count"], "down_count": dist["down_count"],
            "flat_count": dist["flat_count"], "limit_up": dist["limit_up"],
            "limit_down": dist["limit_down"], "total": dist["total"],
            "advance_decline_ratio": dist["advance_decline_ratio"],
        }
    # 冷启动兜底
    try:
        import efinance as ef
        df = await asyncio.to_thread(ef.stock.get_realtime_quotes)
        if df is None or df.empty:
            raise HTTPException(status_code=503, detail="No realtime data")
        import numpy as np
        change_vals = []
        for v in df.iloc[:, 2]:
            try:
                change_vals.append(float(v))
            except (TypeError, ValueError):
                pass
        vals = np.array(change_vals)
        up_count   = int((vals > 0.05).sum())
        down_count = int((vals < -0.05).sum())
        flat_count = int(((vals >= -0.05) & (vals <= 0.05)).sum())
        return {
            "up_count": up_count, "down_count": down_count, "flat_count": flat_count,
            "limit_up": int((vals >= 9.9).sum()), "limit_down": int((vals <= -9.9).sum()),
            "total": up_count + down_count + flat_count,
            "advance_decline_ratio": round(up_count / down_count, 2) if down_count else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/distribution")
async def get_market_distribution():
    """全市场涨跌幅分布直方图(按涨跌幅分桶的家数)。

    用于大盘首页"涨跌分布"柱状图：一眼看清今日是普涨/普跌/分化，比单纯的
    三段宽度条信息量大得多。走本地快照 SQL 聚合。
    """
    dist = await asyncio.to_thread(_db.quote_distribution)
    if not dist:
        raise HTTPException(status_code=503, detail="行情快照尚未就绪，请稍后重试")
    return dist


# ── 两市成交额 / 量能(从腾讯指数行情取，vals[37]=成交额(万元))──────────────

def _fetch_market_turnover() -> dict:
    """沪深两市成交额(亿元)+ 较昨日量能比。

    腾讯 qt.gtimg.cn 单次批量取上证/深成成交额(vals[37]，单位万元)。两市
    合计成交额是 A 股交易者判断量能最直接的指标。失败返回空 dict。
    """
    out: dict = {}
    data = _http_get("qt.gtimg.cn/q=sh000001,sz399001", referer="https://gu.qq.com/")
    sh_amt = sz_amt = None
    for line in data.strip().split(";"):
        if '"' not in line or "=" not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 38:
            continue
        try:
            amt = float(vals[37])  # 成交额，万元
        except (ValueError, IndexError):
            continue
        if key == "sh000001":
            sh_amt = amt
        elif key == "sz399001":
            sz_amt = amt
    if sh_amt is not None and sz_amt is not None:
        total_yi = round((sh_amt + sz_amt) / 1e4, 1)   # 万元 → 亿元
        out = {
            "sh_amount": round(sh_amt / 1e4, 1),
            "sz_amount": round(sz_amt / 1e4, 1),
            "total_amount": total_yi,
        }
    return out


@router.get("/turnover")
async def get_market_turnover():
    """沪深两市成交额(亿元)。短缓存 60s。"""
    ck = "market:turnover"
    cached = await asyncio.to_thread(_db.get, ck, 60)
    if cached:
        return cached
    data = await asyncio.to_thread(_fetch_market_turnover)
    if not data:
        stale = await asyncio.to_thread(_db.get_stale, ck)
        if stale:
            return stale
        raise HTTPException(status_code=503, detail="成交额获取失败")
    await asyncio.to_thread(_db.set, ck, data, 120, "market")
    return data


# ── 涨停池 / 连板梯队 / 炸板率(akshare 涨停池，走代理可用)────────────────────

def _fetch_limit_pool() -> dict:
    """连板梯队 + 炸板率。akshare 涨停池/炸板池(本环境可用)。

    - 涨停池: 按"连板数"分梯队(1板/2板/3板...)，统计每档家数+龙头股。
    - 炸板池: 曾涨停后开板的家数，用于算封板率=涨停/(涨停+炸板)。
    休市/盘前可能无数据，返回空结构由上层兜底缓存。
    """
    import datetime as _dt
    import akshare as ak

    d = _dt.date.today().strftime("%Y%m%d")
    out: dict = {"date": d, "ladders": [], "zt_count": 0, "zb_count": 0,
                 "seal_rate": None, "top": []}
    try:
        zt = ak.stock_zt_pool_em(date=d)
    except Exception as e:
        logger.warning(f"涨停池获取失败: {e}")
        zt = None
    if zt is None or zt.empty:
        return out

    # 列名按位置取，避开中文列名编码问题。akshare 涨停池列序固定：
    # 0序号 1代码 2名称 3涨跌幅 4最新价 5成交额 6流通市值 7总市值 8换手率
    # 9封板资金 10首次封板时间 11最后封板时间 12炸板次数 13涨停统计 14连板数 15所属行业
    def _col(df, idx, default=None):
        try:
            return df.iloc[:, idx]
        except Exception:
            return [default] * len(df)

    codes  = _col(zt, 1)
    names  = _col(zt, 2)
    pcts   = _col(zt, 3)
    lianban = _col(zt, 14)
    industry = _col(zt, 15)

    rows = []
    for i in range(len(zt)):
        try:
            rows.append({
                "code": str(codes.iloc[i]).zfill(6),
                "name": str(names.iloc[i]),
                "change_pct": float(pcts.iloc[i]),
                "lianban": int(lianban.iloc[i]) if lianban.iloc[i] == lianban.iloc[i] else 1,
                "industry": str(industry.iloc[i]) if industry.iloc[i] == industry.iloc[i] else "",
            })
        except (ValueError, TypeError, IndexError):
            continue

    # 分梯队
    from collections import defaultdict
    by_lb: dict[int, list] = defaultdict(list)
    for r in rows:
        by_lb[r["lianban"]].append(r)
    ladders = []
    for lb in sorted(by_lb.keys(), reverse=True):
        members = sorted(by_lb[lb], key=lambda x: x["change_pct"], reverse=True)
        ladders.append({
            "lianban": lb,
            "count": len(members),
            "stocks": members[:12],   # 每档最多展示 12 只
        })

    out["zt_count"] = len(rows)
    out["ladders"] = ladders
    # 最高连板梯队 = 市场情绪高度
    out["top_height"] = max(by_lb.keys()) if by_lb else 0

    # 炸板池
    try:
        zb = ak.stock_zt_pool_zbgc_em(date=d)
        out["zb_count"] = int(len(zb)) if zb is not None else 0
    except Exception as e:
        logger.debug(f"炸板池获取失败: {e}")
        out["zb_count"] = 0

    denom = out["zt_count"] + out["zb_count"]
    out["seal_rate"] = round(out["zt_count"] / denom * 100, 1) if denom else None
    return out


@router.get("/limit-pool")
async def get_limit_pool():
    """连板梯队 + 炸板率 + 封板率(A股短线情绪核心)。缓存 60s。"""
    ck = "market:limit_pool"
    cached = await asyncio.to_thread(_db.get, ck, 60)
    if cached:
        return cached
    data = await asyncio.to_thread(_fetch_limit_pool)
    if data.get("zt_count"):
        await asyncio.to_thread(_db.set, ck, data, 300, "market")
        return data
    stale = await asyncio.to_thread(_db.get_stale, ck)
    if stale:
        return stale
    return data   # 休市无涨停时返回空结构，前端显示"暂无涨停"


# ── 沪深港通资金(北向实时已停披露，保留南向+成交额)──────────────────────────

def _fetch_hsgt() -> dict:
    """沪深港通资金概览。

    注意：北向(陆股通)实时净买额自 2024-08 起已停止披露(成交净买额恒为 0)，
    故只有南向(港股通)有真实净流入。这里如实返回各通道的净买额，前端对北向
    标注"实时已停披露"，避免误导。
    """
    import akshare as ak
    out: dict = {"channels": []}
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
    except Exception as e:
        logger.warning(f"沪深港通资金获取失败: {e}")
        return out
    if df is None or df.empty:
        return out
    # 列：0交易日 1类型 2板块 3资金方向 4交易状态 5成交净买额 6资金净流入 ...
    for _, row in df.iterrows():
        try:
            direction = str(row.iloc[3])      # 北向 / 南向
            board     = str(row.iloc[2])      # 沪股通/深股通/港股通(沪)...
            net_buy   = float(row.iloc[5]) if row.iloc[5] == row.iloc[5] else None
            out["channels"].append({
                "direction": direction, "board": board,
                "net_buy": net_buy,     # 亿元
                "available": direction != "北向",   # 北向实时已停披露
            })
        except (ValueError, TypeError, IndexError):
            continue
    return out


@router.get("/hsgt")
async def get_hsgt():
    """沪深港通资金概览(南向实时净流入；北向已停披露标注)。缓存 60s。"""
    ck = "market:hsgt"
    cached = await asyncio.to_thread(_db.get, ck, 60)
    if cached:
        return cached
    data = await asyncio.to_thread(_fetch_hsgt)
    if data.get("channels"):
        await asyncio.to_thread(_db.set, ck, data, 180, "market")
        return data
    stale = await asyncio.to_thread(_db.get_stale, ck)
    return stale or data


@router.get("/movers")
async def get_market_movers(top: int = 20):
    """涨跌榜(涨幅榜 top + 跌幅榜 top)。

    走本地 Sina 全市场快照(stock_quote 表 SQL 排序)，不再现拉 efinance 全市场
    ——后者直连东财在本环境被劫持，盘后/非交易时段必 503。快照由后台刷新器维护。
    冷启动快照为空时回退 efinance(一次性，可能失败)。
    """
    gainers, _ = await asyncio.to_thread(
        _db.quote_query, sort_by="change_pct", order="desc",
        filter_type="gainers", page=1, page_size=top,
    )
    losers, _ = await asyncio.to_thread(
        _db.quote_query, sort_by="change_pct", order="asc",
        filter_type="losers", page=1, page_size=top,
    )
    if gainers or losers:
        combined = {s["code"]: s for s in (gainers + losers) if s.get("code")}
        return {"stocks": list(combined.values())}

    # 冷启动兜底
    try:
        import efinance as ef
        df = await asyncio.to_thread(ef.stock.get_realtime_quotes)
        if df is None or df.empty:
            raise HTTPException(status_code=503, detail="No realtime data")
        stocks = []
        for _, row in df.iterrows():
            try:
                stocks.append({
                    "name": str(row.iloc[0]), "code": str(row.iloc[1]),
                    "change_pct": float(row.iloc[2]), "price": float(row.iloc[3]),
                })
            except (TypeError, ValueError):
                continue
        stocks.sort(key=lambda x: x["change_pct"], reverse=True)
        combined = {s["code"]: s for s in stocks[:top] + stocks[-top:]}
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


# ── 跨市场搜索 ──────────────────────────────────────────────────────────────

@router.get("/search-global")
async def search_global(q: str = "", limit: int = 20):
    """腾讯 smartbox 跨市场股票搜索（A股/ETF/指数/港股/美股），支持拼音缩写。

    返回列表 [{code, name, market, exchange, price?, change_pct?}]：
    - A股/ETF/指数 code 为 6 位纯数字（会从本地快照补现价/涨跌幅）
    - 港股 code 为 HK + 5 位（如 HK00700）
    - 美股 code 为 US + 大写代码（如 USAAPL）

    smartbox 原生支持拼音缩写检索（如 GZMT → 贵州茅台），是 A股 拼音搜索的引擎。
    """
    q = (q or "").strip()
    if not q:
        return {"items": []}
    try:
        from quantforge.data.feed.mootdx_feed import _tencent_smartbox_search
        items = await asyncio.to_thread(_tencent_smartbox_search, q, min(limit, 40))
        # 用本地快照补 A股/ETF/指数（纯数字代码）的现价与涨跌幅，便于直接展示
        cn_codes = [it["code"] for it in items if str(it.get("code", "")).isdigit()]
        if cn_codes:
            qmap = await asyncio.to_thread(_db.quote_get_many, cn_codes)
            for it in items:
                row = qmap.get(it["code"])
                if row:
                    it["price"] = row.get("price")
                    it["change_pct"] = row.get("change_pct")
                    if not it.get("exchange"):
                        it["exchange"] = row.get("exchange")
        return {"items": items, "query": q}
    except Exception as e:
        logger.debug(f"search-global failed: {e}")
        return {"items": [], "query": q}
