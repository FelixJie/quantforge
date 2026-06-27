"""Individual stock analysis endpoints.

Endpoints:
  GET  /api/stock-analysis/{symbol}/overview     — quote + basic info
  GET  /api/stock-analysis/{symbol}/technical    — bars + indicators
  GET  /api/stock-analysis/{symbol}/momentum     — momentum score + buy/sell points
  GET  /api/stock-analysis/{symbol}/fundamental  — financials + holders
  POST /api/stock-analysis/{symbol}/ai           — AI comprehensive analysis
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import math
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from loguru import logger

from quantforge.data.storage import db_cache as _db
from quantforge.api.routes.auth import get_optional_user

router = APIRouter(prefix="/stock-analysis", tags=["stock-analysis"])

_CACHE_DIR    = Path("data/cache/stock_analysis")
_CACHE_TTL    = 86400          # 24 hours — refreshed on explicit user request
_CACHE_QUOTE  = 5 * 60        # 5 min for real-time quote (overview)
_HISTORY_FILE = Path("data/cache/stock_analysis_history.json")


# ── Stale-while-revalidate (DB-backed) ─────────────────────────────────────────
# 落 cache_entries 表：先返回本地已有（即便过期也立刻给），过期则后台静默刷新，
# 下次访问即新鲜。天级别数据（基本面）给长一点的新鲜窗口。

_inflight: set[str] = set()


def _swr_key(kind: str, symbol: str, suffix: str = "") -> str:
    return f"sa:{kind}:{str(symbol).strip().upper()}{suffix}"


async def _revalidate(key: str, fetch_fn, ttl: int, category: str) -> None:
    if key in _inflight:
        return
    _inflight.add(key)
    try:
        data = await asyncio.to_thread(fetch_fn)
        if data:
            await asyncio.to_thread(_db.set, key, data, ttl, category)
    except Exception as e:
        logger.debug(f"SWR revalidate {key} failed: {e}")
    finally:
        _inflight.discard(key)


async def _serve_swr(key: str, fetch_fn, ttl: int, category: str, refresh: bool) -> dict:
    """先本地后刷新：命中新鲜→直接返回；有陈旧→返回陈旧并后台刷新；
    都没有或强制刷新→现拉并落库。"""
    if not refresh:
        fresh = await asyncio.to_thread(_db.get, key, ttl)
        if fresh is not None:
            return fresh
        stale = await asyncio.to_thread(_db.get_stale, key)
        if stale is not None:
            asyncio.create_task(_revalidate(key, fetch_fn, ttl, category))
            return {**stale, "_stale": True}
    data = await asyncio.to_thread(fetch_fn)
    await asyncio.to_thread(_db.set, key, data, ttl, category)
    return data


# ── Query history ──────────────────────────────────────────────────────────────

def _load_history() -> list[dict]:
    if _HISTORY_FILE.exists():
        try:
            return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_to_history(symbol: str, name: str):
    """Save a query to history (dedup by symbol, keep last 20)."""
    history = _load_history()
    history = [h for h in history if h.get("symbol") != symbol]
    history.insert(0, {
        "symbol": symbol,
        "name": name,
        "queried_at": _dt.datetime.now().isoformat(timespec="seconds"),
    })
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HISTORY_FILE.write_text(
            json.dumps(history[:20], ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


# ── efinance helpers (positional indexing due to Windows encoding) ─────────────

def _load_bars_parquet(symbol: str, days: int) -> list[dict]:
    """Load bars from local parquet storage (fast path)."""
    try:
        from quantforge.api.deps import get_backtest_engine
        from quantforge.core.constants import Interval
        import datetime as _dt2

        engine = get_backtest_engine()
        end_dt = _dt2.datetime.now()
        start_dt = end_dt - _dt2.timedelta(days=days + 90)  # buffer for MA60
        df = engine._data_manager.load_bars(symbol, Interval("1d"), start_dt, end_dt)
        if df is None or df.empty:
            return []

        bars = []
        for _, row in df.iterrows():
            try:
                close = float(row["close"])
                prev_close = float(df.loc[df.index[df.index.get_loc(_) - 1], "close"]) if _ > 0 else close
                chg = round((close / prev_close - 1) * 100, 2) if prev_close else 0
                bars.append({
                    "date":       str(row["datetime"])[:10],
                    "open":       round(float(row["open"]), 3),
                    "close":      round(close, 3),
                    "high":       round(float(row["high"]), 3),
                    "low":        round(float(row["low"]), 3),
                    "volume":     float(row["volume"]),
                    "change_pct": chg,
                })
            except Exception:
                continue
        return bars[-days:]
    except Exception as e:
        logger.debug(f"Parquet load failed for {symbol}: {e}")
        return []


def _load_bars_db(symbol: str, days: int) -> list[dict]:
    """日 K 线：走 stock_kline 表（DB 优先 + 增量更新，腾讯前复权）。

    历史不变，刷新只补最近少量几根；返回最近 ``days`` 根并补算 change_pct。
    这是技术面 K 线的主路径，取代被劫持的 efinance/push2his。
    """
    try:
        from quantforge.data.storage import db_cache as _db
        from quantforge.api.routes.market import (
            _kline_fetch, _kline_meta_key, _kline_read_ttl,
        )
    except Exception:
        return []

    sym = str(symbol).strip().upper()
    existing = _db.kline_load(sym, "day")
    fresh = _db.get(_kline_meta_key(sym, "day"), _kline_read_ttl())
    if not (existing and fresh):
        fetch_count = max(days + 90, 320) if not existing else 8  # 首次拉满(留MA60余量)，之后增量
        try:
            bars = _kline_fetch(sym, "day", fetch_count)
        except Exception as e:
            logger.warning(f"db kline fetch failed for {symbol}: {e}")
            bars = []
        if bars:
            _db.kline_upsert(sym, "day", bars)
            _db.set(_kline_meta_key(sym, "day"), {"ok": 1}, 86400, "market_kline_meta")
            existing = _db.kline_load(sym, "day")

    if not existing:
        return []

    # 补算 change_pct（表里不存，按收盘价序列现算）
    out = []
    prev = None
    for b in existing:
        close = b.get("close")
        chg = round((close / prev - 1) * 100, 2) if (prev and close) else 0
        prev = close if close else prev
        out.append({
            "date":       str(b.get("date") or b.get("datetime"))[:10],
            "open":       b.get("open"),
            "close":      close,
            "high":       b.get("high"),
            "low":        b.get("low"),
            "volume":     b.get("volume"),
            "change_pct": chg,
        })
    return out[-days:]


def _load_bars_efinance(symbol: str, days: int) -> list[dict]:
    """Load bars from efinance (slow fallback when no local parquet)."""
    try:
        import efinance as ef
        end = _dt.date.today()
        start = end - _dt.timedelta(days=days + 90)
        df = ef.stock.get_quote_history(
            symbol,
            beg=start.strftime("%Y%m%d"),
            end=end.strftime("%Y%m%d"),
            klt=101,
        )
        if df is None or df.empty:
            return []
        bars = []
        for _, row in df.iterrows():
            try:
                bars.append({
                    "date":       str(row.iloc[2])[:10],
                    "open":       _safe_float(row.iloc[3]),
                    "close":      _safe_float(row.iloc[4]),
                    "high":       _safe_float(row.iloc[5]),
                    "low":        _safe_float(row.iloc[6]),
                    "volume":     _safe_float(row.iloc[7]),
                    "change_pct": _safe_float(row.iloc[10]),
                })
            except Exception:
                continue
        return bars[-days:]
    except Exception as e:
        logger.warning(f"efinance technical fetch failed for {symbol}: {e}")
        return []


def _fetch_finance_indicators(symbol: str) -> dict:
    """从东方财富 datacenter 拉 ROE(加权) / 销售毛利率。

    push2 的 get_base_info（ROE/毛利率来源）在本环境被服务器侧 RST，但
    datacenter-web.eastmoney.com 可用（十大股东也走它），故从 F10 主要财务
    指标补这两项。
    """
    import requests

    c = str(symbol).strip()
    if c.startswith(("6", "9")):
        secu = f"{c}.SH"
    elif c.startswith("8"):
        secu = f"{c}.BJ"
    else:
        secu = f"{c}.SZ"
    try:
        r = requests.get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            params={
                "reportName": "RPT_F10_FINANCE_MAINFINADATA",
                "columns": "SECUCODE,REPORT_DATE,ROEJQ,XSMLL",
                "filter": f'(SECUCODE="{secu}")',
                "sortColumns": "REPORT_DATE", "sortTypes": "-1",
                "pageSize": "1", "source": "HSF10", "client": "PC",
            },
            headers={"User-Agent": "Mozilla/5.0",
                     "Referer": "https://emweb.securities.eastmoney.com/"},
            timeout=8,
        )
        data = (r.json().get("result") or {}).get("data") or []
        if data:
            row = data[0]
            return {
                "roe": _safe_float(row.get("ROEJQ")),
                "gross_margin": _safe_float(row.get("XSMLL")),
            }
    except Exception as e:
        logger.warning(f"datacenter finance indicators failed for {symbol}: {e}")
    return {}


def _secu_code(symbol: str) -> str:
    """A股代码 → 带交易所后缀的 SECUCODE（600519 → 600519.SH）。"""
    c = str(symbol).strip()
    if c.startswith(("6", "9")):
        return f"{c}.SH"
    if c.startswith("8"):
        return f"{c}.BJ"
    return f"{c}.SZ"


def _fetch_financials(symbol: str, years: int = 3) -> list[dict]:
    """从东方财富 datacenter 拉近 N 年年报关键财务指标。

    供 AI 一页纸「第八章 财务数据分析」使用。push2/get_base_info 在本环境被
    服务器侧 RST，但 datacenter-web.eastmoney.com 可用，故走 F10 主要财务指标表。
    返回按报告期降序的列表，每项含营收/归母净利润/同比/毛利率/ROE/资产负债率/EPS。
    """
    import requests

    secu = _secu_code(symbol)
    try:
        r = requests.get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            params={
                "reportName": "RPT_F10_FINANCE_MAINFINADATA",
                "columns": ("SECUCODE,REPORT_DATE,REPORT_DATE_NAME,REPORT_TYPE,"
                            "TOTALOPERATEREVE,PARENTNETPROFIT,TOTALOPERATEREVETZ,"
                            "PARENTNETPROFITTZ,XSMLL,ROEJQ,ZCFZL,EPSJB"),
                # 只取年报，按报告期降序
                "filter": f'(SECUCODE="{secu}")(REPORT_TYPE="年报")',
                "sortColumns": "REPORT_DATE", "sortTypes": "-1",
                "pageSize": str(max(years, 1)), "source": "HSF10", "client": "PC",
            },
            headers={"User-Agent": "Mozilla/5.0",
                     "Referer": "https://emweb.securities.eastmoney.com/"},
            timeout=10,
        )
        data = (r.json().get("result") or {}).get("data") or []
        out: list[dict] = []
        for row in data[:years]:
            out.append({
                "period":     (row.get("REPORT_DATE_NAME")
                               or str(row.get("REPORT_DATE", ""))[:4]),
                "revenue":    _safe_float(row.get("TOTALOPERATEREVE")),    # 营业总收入(元)
                "net_profit": _safe_float(row.get("PARENTNETPROFIT")),     # 归母净利润(元)
                "revenue_yoy":    _safe_float(row.get("TOTALOPERATEREVETZ")),  # 营收同比%
                "net_profit_yoy": _safe_float(row.get("PARENTNETPROFITTZ")),   # 归母净利同比%
                "gross_margin":   _safe_float(row.get("XSMLL")),    # 销售毛利率%
                "roe":            _safe_float(row.get("ROEJQ")),    # 加权ROE%
                "debt_ratio":     _safe_float(row.get("ZCFZL")),   # 资产负债率%
                "eps":            _safe_float(row.get("EPSJB")),    # 基本EPS
            })
        return out
    except Exception as e:
        logger.warning(f"datacenter financials failed for {symbol}: {e}")
        return []


def _fetch_overview(symbol: str) -> dict:
    """Fetch base info and current quote via efinance."""
    import efinance as ef

    result = {"symbol": symbol, "code": symbol}

    # Base info: [code, name, total_shares, market_cap, circ_cap, industry, pe_ttm, pb, roe, gross_margin, pe_static, sector]
    try:
        info = ef.stock.get_base_info(symbol)
        if info is not None and len(info) >= 6:
            result["name"]          = str(info.iloc[1]) if pd_safe(info.iloc[1]) else ""
            result["total_shares"]  = _safe_float(info.iloc[2])
            result["market_cap"]    = _safe_float(info.iloc[3])
            result["circ_cap"]      = _safe_float(info.iloc[4])
            result["pe_ttm"]        = _safe_float(info.iloc[6]) if len(info) > 6 else None
            result["pb"]            = _safe_float(info.iloc[7]) if len(info) > 7 else None
            result["roe"]           = _safe_float(info.iloc[8]) if len(info) > 8 else None
            result["gross_margin"]  = _safe_float(info.iloc[9]) if len(info) > 9 else None
            result["pe_static"]     = _safe_float(info.iloc[10]) if len(info) > 10 else None
    except Exception as e:
        logger.warning(f"get_base_info failed for {symbol}: {e}")

    # Latest quote: [code, name, change_pct, latest, high, low, open, change_amt, volume, turnover_rate,
    #                dynamic_pe, turnover_amount, ?, yesterday_close, market_cap, circ_cap, market, ...]
    try:
        df = ef.stock.get_latest_quote([symbol])
        if df is not None and not df.empty:
            row = df.iloc[0]
            if not result.get("name"):
                result["name"] = str(row.iloc[1]) if len(row) > 1 else ""
            result["change_pct"]       = _safe_float(row.iloc[2])
            result["price"]            = _safe_float(row.iloc[3])
            result["high"]             = _safe_float(row.iloc[4])
            result["low"]              = _safe_float(row.iloc[5])
            result["open"]             = _safe_float(row.iloc[6])
            result["change_amt"]       = _safe_float(row.iloc[7])
            result["volume"]           = _safe_float(row.iloc[8])   # 手
            result["turnover_rate"]    = _safe_float(row.iloc[9])
            result["turnover_amount"]  = _safe_float(row.iloc[11]) if len(row) > 11 else None
            result["yesterday_close"]  = _safe_float(row.iloc[13]) if len(row) > 13 else None
            if not result.get("market_cap"):
                result["market_cap"]   = _safe_float(row.iloc[14]) if len(row) > 14 else None
            result["market"]           = str(row.iloc[16]) if len(row) > 16 else ""
            result["update_time"]      = str(row.iloc[18]) if len(row) > 18 else ""
    except Exception as e:
        logger.warning(f"get_latest_quote failed for {symbol}: {e}")

    # 东方财富 push2 行情/基础数据服务器常被代理劫持（get_base_info / get_latest_quote
    # 走的就是 push2），导致价格与估值全空。用统一数据源门面（iFinD→腾讯）补齐缺失字段。
    # 腾讯不提供 ROE/毛利率/总股本，这几项仍可能为空。
    if not result.get("price") or not result.get("pe_ttm"):
        try:
            from quantforge.data.feed import datasource
            q = (datasource.quotes([symbol]) or {}).get(symbol)
            if q:
                def _fill(key, val):
                    if val not in (None, 0, 0.0) and not result.get(key):
                        result[key] = val
                if not result.get("name") or result.get("name") == symbol:
                    if q.get("name"):
                        result["name"] = q["name"]
                _fill("price",            q.get("price"))
                _fill("change_pct",       q.get("change_pct"))
                _fill("change_amt",       q.get("change_amt"))
                _fill("open",             q.get("open"))
                _fill("high",             q.get("high"))
                _fill("low",              q.get("low"))
                _fill("yesterday_close",  q.get("last_close"))
                _fill("turnover_rate",    q.get("turnover_pct"))
                _fill("pe_ttm",           q.get("pe_ttm"))
                _fill("pb",               q.get("pb"))
                _fill("pe_static",        q.get("pe_static"))
                # 成交额：腾讯给的是“万元”，统一成“元”
                if q.get("amount_wan") and not result.get("turnover_amount"):
                    result["turnover_amount"] = q["amount_wan"] * 1e4
                # 市值/流通市值：腾讯给的是“亿元”，统一成“元”
                if q.get("mcap_yi") and not result.get("market_cap"):
                    result["market_cap"] = q["mcap_yi"] * 1e8
                if q.get("float_mcap_yi") and not result.get("circ_cap"):
                    result["circ_cap"] = q["float_mcap_yi"] * 1e8
                # 总股本 = 总市值 / 现价（push2 的 get_base_info 拿不到时的近似）
                if not result.get("total_shares") and result.get("market_cap") and result.get("price"):
                    result["total_shares"] = result["market_cap"] / result["price"]
        except Exception as e:
            logger.warning(f"datasource quote fallback failed for {symbol}: {e}")

    # ROE / 毛利率：push2 的 get_base_info 被封时，从 datacenter 财务接口补
    if result.get("roe") is None or result.get("gross_margin") is None:
        fin = _fetch_finance_indicators(symbol)
        if result.get("roe") is None and fin.get("roe") is not None:
            result["roe"] = fin["roe"]
        if result.get("gross_margin") is None and fin.get("gross_margin") is not None:
            result["gross_margin"] = fin["gross_margin"]

    # 补充盘口指标（同花顺常见：振幅/量比/涨跌停价）。腾讯门面已带这些字段，
    # 但上面的回退块只在 price/pe 缺失时才跑，这里无条件补齐缺失项。
    if any(result.get(k) is None for k in ("amplitude", "vol_ratio", "limit_up", "limit_down")):
        try:
            from quantforge.data.feed import datasource
            q = (datasource.quotes([symbol]) or {}).get(symbol)
            if q:
                if result.get("amplitude") is None and q.get("amplitude_pct"):
                    result["amplitude"] = q["amplitude_pct"]
                if result.get("vol_ratio") is None and q.get("vol_ratio"):
                    result["vol_ratio"] = q["vol_ratio"]
                if result.get("limit_up") is None and q.get("limit_up"):
                    result["limit_up"] = q["limit_up"]
                if result.get("limit_down") is None and q.get("limit_down"):
                    result["limit_down"] = q["limit_down"]
        except Exception as e:
            logger.warning(f"datasource board-fields fallback failed for {symbol}: {e}")

    # 均价 = 成交额 / (成交量 × 100)，1 手 = 100 股
    if result.get("avg_price") is None and result.get("turnover_amount") and result.get("volume"):
        try:
            result["avg_price"] = round(result["turnover_amount"] / (result["volume"] * 100.0), 3)
        except (TypeError, ZeroDivisionError):
            pass

    # Fallback name from code prefix
    if not result.get("name"):
        result["name"] = symbol

    return result


def _load_bars(symbol: str, days: int) -> list[dict]:
    """Load daily OHLCV bars with the standard fallback chain.

    Priority: stock_kline DB (incremental, 腾讯前复权) → local parquet → efinance.
    Returns ascending OHLCV dicts (date/open/high/low/close/volume/...).
    """
    bars = _load_bars_db(symbol, days)
    if not bars:
        bars = _load_bars_parquet(symbol, days)
        if bars:
            try:
                latest = _dt.date.fromisoformat(bars[-1]["date"])
                if (_dt.date.today() - latest).days > 7:
                    fresh = _load_bars_efinance(symbol, days)
                    if fresh:
                        bars = fresh
            except Exception:
                pass
        else:
            bars = _load_bars_efinance(symbol, days)
    return bars


def _fetch_technical(symbol: str, days: int = 180) -> dict:
    """Fetch daily bars and compute technical indicators.

    Priority: 1) local parquet if recent, 2) efinance network (always fresh).
    """
    bars = _load_bars(symbol, days)
    if not bars:
        return {"bars": [], "indicators": {}}

    closes = [b["close"] for b in bars]
    highs  = [b["high"]  for b in bars]
    lows   = [b["low"]   for b in bars]

    # Moving averages
    ma5  = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    ma20 = _ma(closes, 20)
    ma60 = _ma(closes, 60)
    boll = _boll(closes)
    rsi  = _rsi(closes, 14)
    macd_data = _macd(closes)

    # Key levels: 20-day high/low (support/resistance proxy)
    recent = closes[-20:] if len(closes) >= 20 else closes
    support    = round(min(lows[-20:]), 2)  if len(lows)  >= 20 else round(min(lows), 2)
    resistance = round(max(highs[-20:]), 2) if len(highs) >= 20 else round(max(highs), 2)

    # Trend signal (simplified)
    signal = "neutral"
    if len(closes) >= 5 and len(ma5) >= 5 and len(ma20) >= 5:
        if ma5[-1] and ma20[-1] and ma5[-1] > ma20[-1] and closes[-1] > ma20[-1]:
            signal = "bullish"
        elif ma5[-1] and ma20[-1] and ma5[-1] < ma20[-1] and closes[-1] < ma20[-1]:
            signal = "bearish"

    return {
        "bars": bars,
        "ma": {"ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60},
        "boll": boll,
        "rsi": rsi,
        "macd": macd_data,
        "support": support,
        "resistance": resistance,
        "signal": signal,
    }


def _fetch_momentum(symbol: str, days: int = 180) -> dict:
    """Compute rule-based momentum score + ATR-anchored buy/sell levels.

    Reuses the same bars-loading chain as `/technical`; pure-computation
    scoring lives in `quantforge.analysis.momentum.compute_momentum`.
    """
    from quantforge.analysis.momentum import compute_momentum

    bars = _load_bars(symbol, days)
    if not bars:
        return {"score": [], "direction": [], "state": [], "atr": [],
                "signals": [], "current": None}

    result = compute_momentum(bars)
    # expose the bar dates so the frontend can align score/signals to the K-line
    result["dates"] = [b.get("date") for b in bars]

    # 当前价（用于估值风险/目标价上行空间计算）
    last_close = bars[-1].get("close") if bars else None

    # 估值风险 + 研报一致目标价（需外部数据，放在 API 层组装，保持核心模块纯净）
    _enrich_valuation_risk(symbol, result, last_close)
    _enrich_consensus_target(symbol, result, last_close)
    return result


# 估值风险阈值（A 股常见经验值；非银行/周期股可后续按行业细化）
_PE_HIGH, _PE_VERY_HIGH = 60.0, 100.0
_PB_HIGH, _PB_VERY_HIGH = 8.0, 15.0


def _enrich_valuation_risk(symbol: str, result: dict, last_close) -> None:
    """补充估值维度风险到 result['risk']（PE/PB 过高、现价超出一致目标价）。"""
    risk = result.get("risk") or {"level": "低", "items": []}
    items = risk.setdefault("items", [])
    try:
        ov = _fetch_overview(symbol)
    except Exception:
        ov = {}
    pe = _safe_float(ov.get("pe_ttm"))
    pb = _safe_float(ov.get("pb"))

    if pe is not None and pe > 0:
        if pe >= _PE_VERY_HIGH:
            items.append({"type": "valuation_pe", "level": "高",
                          "msg": f"PE(TTM) {pe:.0f} 倍处于极高区间，估值透支风险大"})
        elif pe >= _PE_HIGH:
            items.append({"type": "valuation_pe", "level": "中",
                          "msg": f"PE(TTM) {pe:.0f} 倍偏高，需盈利高增长支撑"})
    if pb is not None and pb > 0:
        if pb >= _PB_VERY_HIGH:
            items.append({"type": "valuation_pb", "level": "高",
                          "msg": f"PB {pb:.1f} 倍极高，破位回撤风险大"})
        elif pb >= _PB_HIGH:
            items.append({"type": "valuation_pb", "level": "中",
                          "msg": f"PB {pb:.1f} 倍偏高"})

    risk["valuation"] = {"pe_ttm": pe, "pb": pb, "roe": _safe_float(ov.get("roe"))}
    # 重算汇总等级
    order = {"低": 0, "中": 1, "高": 2}
    lvl = "低"
    for it in items:
        if order.get(it.get("level"), 0) > order.get(lvl, 0):
            lvl = it["level"]
    risk["level"] = lvl
    result["risk"] = risk


def _load_reports_for_target(symbol: str) -> list[dict]:
    """读研报；本地空库时同步拉一次入库（复用 research 模块的取数逻辑）。

    本函数运行在 _serve_swr 的线程池里，可安全做同步网络/DB 调用。
    """
    from quantforge.data.storage import db_cache as _dbc
    try:
        if _dbc.reports_count(symbol) == 0:
            from quantforge.api.routes.research import _eastmoney_reports, _store_reports
            raw = _eastmoney_reports(symbol, max_pages=3, page_size=100)
            if raw:
                _store_reports(symbol, raw)
    except Exception as e:
        logger.debug(f"reports prefetch for {symbol} failed: {e}")
    try:
        return _dbc.reports_get(symbol, limit=60)
    except Exception:
        return []


def _report_target_price(r: dict) -> float | None:
    """单篇研报的目标价：优先明确 target_price，否则 EPS×预测PE 反推。

    东财个股研报列表接口现已普遍不返回 indvAimPrice（目标价字段为空），
    但 EPS/PE 预测齐全，故用 eps_next×pe_next（次年优先，回退当年）反推。
    """
    tp = _safe_float(r.get("target_price"))
    if tp and tp > 0:
        return tp, "研报"
    for eps_k, pe_k in (("eps_next", "pe_next"), ("eps_this", "pe_this")):
        eps = _safe_float(r.get(eps_k))
        pe = _safe_float(r.get(pe_k))
        if eps and pe and eps > 0 and pe > 0:
            return eps * pe, "EPS×PE反推"
    return None, None


def _enrich_consensus_target(symbol: str, result: dict, last_close) -> None:
    """聚合券商研报一致目标价 → result['target']，并与技术目标价对照。"""
    tech = result.get("tech_target") or {}
    target: dict = {
        "tech_target": tech.get("target"),
        "tech_method": tech.get("method"),
        "tech_upside_pct": tech.get("upside_pct"),
        "consensus": None,
    }
    reps = _load_reports_for_target(symbol)

    # 近 180 天内的研报；目标价优先用明确值，否则 EPS×PE 反推
    cutoff = (_dt.date.today() - _dt.timedelta(days=180)).isoformat()
    entries, ratings = [], {}
    derived_any = False
    for r in reps:
        pdate = str(r.get("publish_date") or "")[:10]
        rt = (r.get("rating") or "").strip()
        if rt:
            ratings[rt] = ratings.get(rt, 0) + 1
        if pdate < cutoff:
            continue
        tp, src = _report_target_price(r)
        if tp and tp > 0:
            if src != "研报":
                derived_any = True
            entries.append({"org": r.get("org"), "target": round(tp, 2),
                            "rating": r.get("rating"), "date": pdate, "src": src})

    if entries:
        prices = sorted(e["target"] for e in entries)
        n = len(prices)
        median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2
        lc = _safe_float(last_close)
        upside = ((median - lc) / lc * 100) if lc else None
        target["consensus"] = {
            "count": n,
            "low": round(prices[0], 2),
            "high": round(prices[-1], 2),
            "median": round(median, 2),
            "upside_pct": round(upside, 2) if upside is not None else None,
            "ratings": ratings,
            "recent": entries[:5],
            "derived": derived_any,   # 是否含 EPS×PE 反推（前端可标注口径）
        }
        # 现价超出一致目标价 → 估值风险
        if lc and median and lc > median:
            risk = result.setdefault("risk", {"level": "低", "items": []})
            risk.setdefault("items", []).append({
                "type": "above_target", "level": "中",
                "msg": f"现价已高于机构一致目标价中位数 {median:.2f}，上行空间有限"})
            order = {"低": 0, "中": 1, "高": 2}
            if order.get("中", 0) > order.get(risk.get("level", "低"), 0):
                risk["level"] = "中"

    result["target"] = target


def _fetch_fundamental(symbol: str, with_billboard: bool = True) -> dict:
    """Fetch financial fundamentals and top holders.

    ``with_billboard=False`` 跳过龙虎榜（get_daily_billboard 要下载整个市场再过滤，
    很慢）——冷启动先快速返回股东，龙虎榜由后台 revalidate 补上。
    """
    import efinance as ef

    result: dict = {"billboard": []}

    # Top 10 holders
    try:
        df = ef.stock.get_top10_stock_holder_info(symbol, top=2)
        if df is not None and not df.empty:
            # 列: [0]股票代码 [1]公告日期 [2]股东代码 [3]股东名称 [4]持股数(带亿/万)
            #     [5]持股比例(带%) [6]变动 [7]变动比
            holders = []
            for _, row in df.iterrows():
                try:
                    holders.append({
                        "report_date": str(row.iloc[1])[:10],
                        "name":        str(row.iloc[3]),
                        "type":        "",  # 该 efinance 版本无股东性质列
                        "shares":      _parse_cn_amount(row.iloc[4]),  # → 股
                        "pct":         _parse_cn_amount(row.iloc[5]),  # → %
                        "change":      str(row.iloc[6]),
                    })
                except Exception:
                    continue
            result["holders"] = holders[:20]  # latest 20 entries (top10 × 2 reports)
    except Exception as e:
        logger.warning(f"get_top10_stock_holder_info failed: {e}")
        result["holders"] = []

    # Daily billboard (龙虎榜) — last 30 days（慢，冷启动时跳过）
    if not with_billboard:
        return result
    try:
        end = _dt.date.today().strftime("%Y-%m-%d")
        start = (_dt.date.today() - _dt.timedelta(days=30)).strftime("%Y-%m-%d")
        bb = ef.stock.get_daily_billboard(start, end)
        if bb is not None and not bb.empty:
            # Filter by symbol (col 0 = code)
            sym_rows = bb[bb.iloc[:, 0] == symbol]
            billboard = []
            for _, row in sym_rows.iterrows():
                try:
                    billboard.append({
                        "date":       str(row.iloc[2])[:10] if len(row) > 2 else "",
                        "close":      _safe_float(row.iloc[3]) if len(row) > 3 else None,
                        "change_pct": _safe_float(row.iloc[4]) if len(row) > 4 else None,
                        "reason":     str(row.iloc[15]) if len(row) > 15 else "",
                    })
                except Exception:
                    continue
            result["billboard"] = billboard
        else:
            result["billboard"] = []
    except Exception as e:
        logger.debug(f"get_daily_billboard failed: {e}")
        result["billboard"] = []

    return result


# ── Technical indicator math ───────────────────────────────────────────────────

def _ma(data: list, period: int) -> list:
    result = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(round(sum(data[i - period + 1:i + 1]) / period, 3))
    return result


def _boll(data: list, period: int = 20, k: float = 2.0) -> dict:
    mid, upper, lower = [], [], []
    for i in range(len(data)):
        if i < period - 1:
            mid.append(None); upper.append(None); lower.append(None)
        else:
            sl = data[i - period + 1:i + 1]
            mean = sum(sl) / period
            std = math.sqrt(sum((v - mean) ** 2 for v in sl) / period)
            mid.append(round(mean, 3))
            upper.append(round(mean + k * std, 3))
            lower.append(round(mean - k * std, 3))
    return {"upper": upper, "mid": mid, "lower": lower}


def _rsi(data: list, period: int = 14) -> list:
    result = [None] * len(data)
    if len(data) < period + 1:
        return result
    gains, losses = [], []
    for i in range(1, len(data)):
        diff = data[i] - data[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(data)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 100
        result[i] = round(100 - 100 / (1 + rs), 2)
    return result


def _ema(data: list, period: int) -> list:
    k = 2 / (period + 1)
    result = [None] * len(data)
    for i in range(len(data)):
        if data[i] is None:
            continue
        if result[i - 1] is None:
            result[i] = data[i]
        else:
            result[i] = data[i] * k + result[i - 1] * (1 - k)
    return [round(v, 4) if v is not None else None for v in result]


def _macd(data: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    ema_fast = _ema(data, fast)
    ema_slow = _ema(data, slow)
    dif = [
        round(f - s, 4) if f is not None and s is not None else None
        for f, s in zip(ema_fast, ema_slow)
    ]
    dea = _ema(dif, signal)
    hist = [
        round((d - e) * 2, 4) if d is not None and e is not None else None
        for d, e in zip(dif, dea)
    ]
    return {"dif": dif, "dea": dea, "hist": hist}


def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    except Exception:
        return None


def pd_safe(v) -> bool:
    try:
        return str(v) not in ("nan", "None", "")
    except Exception:
        return False


def _parse_cn_amount(v) -> float | None:
    """解析带中文单位的数字字符串 → 基础单位数值。

    '6.813亿'→681300000, '368.42万'→3684200, '54.23%'→54.23, '1234'→1234。
    """
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "--", "nan", "None"):
        return None
    pct = s.endswith("%")
    s = s.rstrip("%")
    mult = 1.0
    if s.endswith("亿"):
        mult, s = 1e8, s[:-1]
    elif s.endswith("万"):
        mult, s = 1e4, s[:-1]
    try:
        n = float(s) * mult
        return round(n, 4) if pct else n
    except Exception:
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/history")
async def get_history():
    """Return recent query history (last 20 symbols)."""
    return {"history": _load_history()}


@router.get("/{symbol}/overview")
async def get_overview(symbol: str, refresh: bool = False):
    # 概览含实时价：新鲜窗口 5min；过期则返回陈旧并后台刷新
    key = _swr_key("overview", symbol)
    try:
        data = await _serve_swr(
            key, lambda: _fetch_overview(symbol), _CACHE_QUOTE, "sa_overview", refresh
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
    _save_to_history(symbol, data.get("name", symbol))
    return data


@router.get("/{symbol}/technical")
async def get_technical(symbol: str, days: int = 180, refresh: bool = False):
    # K 线本身已 DB 增量；这里缓存算好的指标，新鲜窗口随交易时段(2min/1h)
    from quantforge.api.routes.market import _kline_read_ttl
    key = _swr_key("technical", symbol, f":{days}")
    try:
        return await _serve_swr(
            key, lambda: _fetch_technical(symbol, days), _kline_read_ttl(), "sa_technical", refresh
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/{symbol}/momentum")
async def get_momentum(symbol: str, days: int = 180, refresh: bool = False):
    """Rule-based momentum analysis → buy/sell point estimation.

    Returns per-bar momentum score/direction/state, ATR-anchored
    buy/stop/target levels (`current`), and historical buy/sell `signals`.
    Cache freshness follows the K-line read TTL (2min intraday / 1h after-hours).
    """
    from quantforge.api.routes.market import _kline_read_ttl
    key = _swr_key("momentum", symbol, f":{days}")
    try:
        return await _serve_swr(
            key, lambda: _fetch_momentum(symbol, days), _kline_read_ttl(), "sa_momentum", refresh
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/{symbol}/fundamental")
async def get_fundamental(symbol: str, refresh: bool = False):
    # 基本面天级别更新：新鲜窗口 12h。冷启动先返回股东（快），龙虎榜（慢，要下载
    # 整个市场再过滤）放到后台 revalidate 补上，下次访问即完整。
    key = _swr_key("fundamental", symbol)
    ttl, cat = 12 * 3600, "sa_fundamental"
    full = lambda: _fetch_fundamental(symbol, with_billboard=True)
    if not refresh:
        fresh = await asyncio.to_thread(_db.get, key, ttl)
        if fresh is not None:
            return fresh
        stale = await asyncio.to_thread(_db.get_stale, key)
        if stale is not None:
            asyncio.create_task(_revalidate(key, full, ttl, cat))
            return {**stale, "_stale": True}
    try:
        data = await asyncio.to_thread(_fetch_fundamental, symbol, False)  # 仅股东，快
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
    await asyncio.to_thread(_db.set, key, data, ttl, cat)
    asyncio.create_task(_revalidate(key, full, ttl, cat))  # 后台补龙虎榜
    return data


class AiAnalysisRequest(BaseModel):
    extra_prompt: Optional[str] = None


@router.post("/{symbol}/ai")
async def ai_analysis(
    symbol: str,
    body: Optional[AiAnalysisRequest] = None,
    current_user: dict | None = Depends(get_optional_user),
):
    """Comprehensive AI analysis combining technical, fundamental, and news data.

    个股分析按账号计费：带登录态时 token 用量记到该账号名下（后台模块可见）。
    """
    from quantforge.api.ai_client import chat
    import requests

    account = current_user["username"] if current_user else None

    # Gather data in parallel
    overview_task    = asyncio.to_thread(_fetch_overview,    symbol)
    technical_task   = asyncio.to_thread(_fetch_technical,  symbol, 90)
    fundamental_task = asyncio.to_thread(_fetch_fundamental, symbol)

    overview, technical, fundamental = await asyncio.gather(
        overview_task, technical_task, fundamental_task, return_exceptions=True
    )

    # Fetch recent news
    news_items: list = []
    try:
        from quantforge.api.routes.news import _fetch_announcements, _format_item
        raw = await asyncio.to_thread(_fetch_announcements, symbol, 1, 10, "A")
        news_items = [_format_item(it) for it in raw]
    except Exception:
        pass

    # Build context text
    ctx_lines = [f"【{symbol}个股综合分析】\n"]

    # Overview section
    if isinstance(overview, dict):
        name = overview.get("name", symbol)
        price = overview.get("price") or overview.get("yesterday_close") or "N/A"
        chg   = overview.get("change_pct")
        chg_s = f"{chg:+.2f}%" if chg is not None else "N/A"
        ctx_lines.append(f"基本信息: {name}({symbol})")
        ctx_lines.append(f"最新价: {price}  涨跌幅: {chg_s}")
        ctx_lines.append(f"市值: {_fmt_billion(overview.get('market_cap'))}  流通市值: {_fmt_billion(overview.get('circ_cap'))}")
        ctx_lines.append(f"PE(TTM): {overview.get('pe_ttm') or 'N/A'}  PB: {overview.get('pb') or 'N/A'}  ROE: {overview.get('roe') or 'N/A'}%")

    # Technical section
    if isinstance(technical, dict):
        bars = technical.get("bars", [])
        if bars:
            last5 = bars[-5:]
            trend = technical.get("signal", "neutral")
            rsi_vals = [v for v in (technical.get("rsi") or []) if v is not None]
            macd_hist = [v for v in (technical.get("macd", {}).get("hist") or []) if v is not None]
            ctx_lines.append(f"\n技术面:")
            ctx_lines.append(f"趋势信号: {trend}")
            ctx_lines.append(f"近5日收盘: {[b['close'] for b in last5]}")
            ctx_lines.append(f"支撑位: {technical.get('support')}  压力位: {technical.get('resistance')}")
            if rsi_vals:
                ctx_lines.append(f"RSI(14): {rsi_vals[-1]:.1f}")
            if macd_hist:
                ctx_lines.append(f"MACD柱: {'正' if macd_hist[-1] > 0 else '负'} ({macd_hist[-1]:.4f})")

    # News section
    if news_items:
        ctx_lines.append(f"\n近期公告（{len(news_items)}条）:")
        for it in news_items[:8]:
            ctx_lines.append(f"  [{it['date']}] {it['title']}")

    # Holders
    if isinstance(fundamental, dict) and fundamental.get("billboard"):
        ctx_lines.append(f"\n近期龙虎榜: {len(fundamental['billboard'])}次上榜")

    context = "\n".join(ctx_lines)

    system = """你是一名专业A股分析师，擅长综合消息面、技术面、基本面进行个股研究。
请严格以JSON格式回答，不要有任何其他文字，格式如下：
{"verdicts":{"news":"利好","tech":"看涨","fundamental":"合理","overall":"关注"},"analysis":"详细分析内容"}
verdicts各字段选项：
- news: 利好 / 利空 / 中性
- tech: 看涨 / 看跌 / 震荡
- fundamental: 低估 / 合理 / 高估
- overall: 买入 / 关注 / 观望 / 减仓
analysis字段：四个维度的详细分析，400字以内，注意：这只是参考分析，不构成投资建议。"""

    user_msg = f"""{context}

请从以下四个维度给出综合分析：
1. 消息面 — 近期公告解读，利好/利空判断
2. 技术面 — 趋势、支撑压力、RSI/MACD信号解读
3. 基本面 — 估值水平（PE/PB/ROE）分析
4. 综合结论 — 短期操作建议及风险提示"""

    if body and body.extra_prompt:
        user_msg = body.extra_prompt
        system = "你是一名专业A股分析师。用中文回答，结构清晰，控制在300字以内。"

    try:
        raw = await chat(system, user_msg, max_tokens=1024, caller="stock_analysis",
                         account=account)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI分析失败: {e}")

    # Parse structured JSON response
    import json as _json, re as _re
    verdicts = {}
    analysis = raw
    if not (body and body.extra_prompt):
        try:
            m = _re.search(r'\{.*\}', raw, _re.DOTALL)
            if m:
                parsed = _json.loads(m.group())
                verdicts = parsed.get("verdicts", {})
                analysis = parsed.get("analysis", raw)
        except Exception:
            pass

    return {
        "symbol":      symbol,
        "name":        overview.get("name", symbol) if isinstance(overview, dict) else symbol,
        "analysis":    analysis,
        "verdicts":    verdicts,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "context": {
            "price":      overview.get("price") if isinstance(overview, dict) else None,
            "change_pct": overview.get("change_pct") if isinstance(overview, dict) else None,
            "signal":     technical.get("signal") if isinstance(technical, dict) else None,
            "rsi":        ([v for v in (technical.get("rsi") or []) if v is not None] or [None])[-1]
                          if isinstance(technical, dict) else None,
        },
    }


def _fmt_billion(v) -> str:
    if v is None:
        return "N/A"
    b = v / 1e8
    return f"{b:.1f}亿"


# ── 信息栏（行业/概念 + 核心竞争力 + 风险点）──────────────────────────────────────
# 个股详情页「动能分析」上方的速览卡：行业/所属概念、最相关概念、3 句核心竞争力、
# 3 句风险点。轻量 AI 产出 JSON，按 symbol+当天日期落库缓存（跨天更新）。

_PROFILE_SYSTEM = """你是一名资深A股研究员。基于给定素材，为一家上市公司输出极简「速览卡」。
严格只输出 JSON（不要任何额外文字、不要 markdown 围栏），结构如下：
{"industry":"所属行业(如:半导体)","concepts":["概念1","概念2","概念3"],
 "top_concept":"最核心/最相关的一个概念","top_concept_reason":"一句话说明为何与该概念最相关",
 "strengths":["核心竞争力句1","句2","句3"],"risks":["风险点句1","句2","句3"]}
要求：
- concepts 给 2-5 个；若素材提供了「所属概念板块」候选，优先从中挑选，top_concept 必须取自 concepts。
- strengths 恰好 3 句、risks 恰好 3 句，每句不超过 40 字，具体、有信息量，不要套话，不杜撰具体数字。
- 全部用简体中文。"""


def _profile_context(symbol: str) -> tuple[str, list[str]]:
    """汇总个股速览素材 + 概念候选列表。返回 (context_text, concept_candidates)。"""
    from quantforge.data.storage import db_cache as _dbc

    try:
        ov = _fetch_overview(symbol)
    except Exception:
        ov = {}
    name = ov.get("name") or symbol

    # 概念候选：反查已落库的同花顺概念成分（可能为空）
    try:
        concepts = _dbc.boards_of_code(symbol, "concept")[:8]
    except Exception:
        concepts = []

    lines = [f"公司：{name}（{symbol}）"]
    if ov.get("industry"):
        lines.append(f"行业：{ov['industry']}")
    lines.append(f"最新价 {ov.get('price') or ov.get('yesterday_close') or 'N/A'}　"
                 f"PE(TTM) {ov.get('pe_ttm') or 'N/A'}　PB {ov.get('pb') or 'N/A'}　"
                 f"ROE {ov.get('roe') or 'N/A'}%　毛利率 {ov.get('gross_margin') or 'N/A'}%　"
                 f"总市值 {_fmt_billion(ov.get('market_cap'))}")
    if concepts:
        lines.append("所属概念板块（候选）：" + "、".join(concepts))

    # 近 3 年财务，给基本面判断
    try:
        fins = _fetch_financials(symbol, years=3)
    except Exception:
        fins = []
    for f in fins:
        def _yi(v):
            return f"{v / 1e8:.2f}亿" if isinstance(v, (int, float)) else "—"
        def _pct(v):
            return f"{v:+.1f}%" if isinstance(v, (int, float)) else "—"
        lines.append(f"{f['period']}：营收 {_yi(f['revenue'])}({_pct(f['revenue_yoy'])})　"
                     f"归母净利 {_yi(f['net_profit'])}({_pct(f['net_profit_yoy'])})　"
                     f"毛利率 {_pct(f['gross_margin'])}　ROE {_pct(f['roe'])}")

    # 研报标题（含逻辑/赛道线索）
    try:
        reps = _dbc.reports_get(symbol, limit=12)
    except Exception:
        reps = []
    if reps:
        lines.append("近期机构研报标题：")
        for r in reps[:12]:
            lines.append(f"  - {r.get('org', '')} | {r.get('title', '')}")

    return "\n".join(lines), concepts


def _profile_key(symbol: str) -> str:
    day = _dt.date.today().isoformat()
    return f"sa:profile:{str(symbol).strip().upper()}:{day}"


@router.get("/{symbol}/profile")
async def get_profile(
    symbol: str,
    refresh: bool = False,
    current_user: dict | None = Depends(get_optional_user),
):
    """信息栏速览：行业/概念、最相关概念、3 句核心竞争力、3 句风险点。

    轻量 AI 产出，按 symbol+当天日期落库缓存（跨天更新）。带登录态时计费归该账号。
    """
    from quantforge.api.ai_client import chat
    import json as _json
    import re as _re

    key = _profile_key(symbol)
    if not refresh:
        cached = await asyncio.to_thread(_db.get, key, 86400)
        if cached:
            return {**cached, "cached": True}

    account = current_user["username"] if current_user else None
    context, concepts = await asyncio.to_thread(_profile_context, symbol)

    try:
        raw = await chat(_PROFILE_SYSTEM, context, max_tokens=900,
                         caller="stock_profile", account=account, timeout=60)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"信息栏生成失败: {e}")

    data: dict = {}
    try:
        m = _re.search(r"\{.*\}", raw or "", _re.DOTALL)
        if m:
            data = _json.loads(m.group())
    except Exception:
        data = {}

    def _strlist(v, n):
        out = [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []
        return out[:n]

    result = {
        "symbol":       symbol,
        "industry":     (data.get("industry") or "").strip(),
        "concepts":     _strlist(data.get("concepts"), 5) or concepts[:5],
        "top_concept":  (data.get("top_concept") or "").strip(),
        "top_concept_reason": (data.get("top_concept_reason") or "").strip(),
        "strengths":    _strlist(data.get("strengths"), 3),
        "risks":        _strlist(data.get("risks"), 3),
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    if not (result["strengths"] or result["risks"]):
        raise HTTPException(status_code=503, detail="信息栏返回为空")
    await asyncio.to_thread(_db.set, key, result, 86400, "sa_profile")
    return {**result, "cached": False}


# ── 公司一页纸（买方视角深度投研报告）─────────────────────────────────────────────
# 个股详情页「AI 深度分析」Tab：点开才触发，按 symbol+日期落库缓存，跨天自动更新。
# 一次性生成整篇 markdown（含表格 / Mermaid 图），max_tokens 拉高、超时放宽。

_ONEPAGER_SYSTEM = """你是一名顶尖买方（机构）投研分析师，为基金经理撰写「公司一页纸」快速投研报告，
目标是在最短时间内抓住一家公司最重要的投资信息。语言直接、去伪存真，杜绝卖方式过度包装。

严格按下面 11 个章节组织，输出 **Markdown**：

# 一、公司近况跟踪
1-2 句总结公司最新变化与经营进展（订单/渠道/新品/业务结构/技术突破等），如有机构拍过市值空间一并给出。

# 二、核心投资逻辑
## 短期逻辑（1-3 个月）
题材/事件炒作逻辑、催化时间节点、订单销量价格、资本运作。**硬性要求：事件发生时间必须在近三个月以内。**
## 长期逻辑（1-3 年）
不超过 3 点关键增长驱动力，落到供需分析（需求爆发/供给收缩）、政策与下游客户、变化幅度，最终落到比竞对更强的盈利能力、稀缺性与卡位。
## 催化事件时间表
表格输出（时间｜事件｜影响），按时间升序，总数不超过 8 个（过去≥2、未来≥2），尽量定位对收入利润影响幅度。

# 三、核心竞争力与护城河
最多 2 条最核心优势，每条含：竞争优势分析（优势类型/结构性 vs 阶段性/盈利变现路径/持续性展望）+ 可验证证据（1-2 个数据，对比同行）。
若无结构性优势，明确指出「该公司目前缺乏显著护城河，业绩增长主要源于行业β红利或短期事件驱动」。
本章末尾附一张 Mermaid flowchart 展示竞争优势的形成逻辑与传导链条。

# 四、公司业务拆分
业务边际变化、各板块收费模式/技术路线/收入占比/毛利率、当前经营周期位置；标注占比最大、增速最快、毛利率最高的业务。
附「分板块业务情况」表格（板块｜过去 3 年收入｜占比｜毛利率｜未来 1-2 年预测）。

# 五、产销链分析
主要客户（比例/集中度/公司地位）、订单（在手/新签/驱动因素）、新客户拓展、主要供应商（表格：变化/集中度/成本结构）、经销商情况。

# 六、管理层与公司治理
股权结构（实控人/持股稳定性/国资背景）、激励机制（股权激励/考核目标）、信用记录（忽悠式重组/激进跨界/频繁减持/财务洗澡）。附一张 Mermaid flowchart 股权架构图。

# 七、资本配置与效率
现金流去向（再投资/并购/股东回报）、投入产出比（ROIC 趋势）、产能周期（资本开支期/爬坡期/折旧结束利润释放期）。

# 八、公司财务数据分析
过去 3 年关键财务指标表格（收入/净利润/毛利率/负债等及异常变化）、最新年份同比、财务健康评估、ROE 拆分与趋势。

# 九、公司调研大纲
市场关注的核心问题 / 调研该问什么（含分歧、风险与机遇两面），收敛到确定性问题层面，按提问普遍性倒序。

# 十、盈利预测与估值
如有卖方盈利预测整理为表格（列为年份，预测年加「E」），文字整理一致预期；无预测则结合年报判断行业向好/承压。

# 十一、风险提示
可能造成业绩大幅不及预期的因素（经营/财务/股本/宏观/产业），并给出需重点关注什么 + 操作建议（观望/转变态度）。

格式规范：
- 定量数据一律用 Markdown 表格；**每张表格后必须有一个空行**。
- 关键定性判断和重要数字**加粗**；营收/净利润用「亿元」，百分比加「%」，文字数字转精确数字（如「增加五个百分点」→「+5%」）。
- Mermaid 图用 ```mermaid 代码块包裹，节点文字简短、不含特殊字符。
- 数据不足时如实标注「资料缺失」，**绝不杜撰具体数字**。直接输出报告正文，不要任何前后缀说明。"""


def _onepager_context(symbol: str) -> str:
    """汇总个股的 overview / 技术面 / 财务指标 / 研报一致预期 / 近期公告，拼成 LLM 上下文。"""
    from quantforge.data.storage import db_cache as _dbc

    lines: list[str] = [f"【{symbol} 投研素材】采集时间 {_dt.date.today().isoformat()}\n"]

    # 概览 + 估值/财务指标
    try:
        ov = _fetch_overview(symbol)
    except Exception:
        ov = {}
    name = ov.get("name") or symbol
    lines.append(f"## 基本信息")
    lines.append(f"名称: {name}（{symbol}）")
    lines.append(f"最新价: {ov.get('price') or ov.get('yesterday_close') or 'N/A'}  涨跌幅: "
                 f"{ov.get('change_pct')}%  行业: {ov.get('industry') or 'N/A'}")
    lines.append(f"总市值: {_fmt_billion(ov.get('market_cap'))}  流通市值: {_fmt_billion(ov.get('circ_cap'))}")
    lines.append(f"PE(TTM): {ov.get('pe_ttm') or 'N/A'}  PE(静): {ov.get('pe_static') or 'N/A'}  "
                 f"PB: {ov.get('pb') or 'N/A'}  ROE: {ov.get('roe') or 'N/A'}%  毛利率: {ov.get('gross_margin') or 'N/A'}%")

    # 近 3 年年报关键财务（供第八章财务分析；缺失则该章如实标注）
    try:
        fins = _fetch_financials(symbol, years=3)
    except Exception:
        fins = []
    if fins:
        lines.append(f"\n## 近 3 年年报财务（来源：东方财富 F10）")
        lines.append("报告期 | 营业总收入(亿) | 同比 | 归母净利润(亿) | 同比 | 毛利率 | ROE(加权) | 资产负债率 | EPS")
        for f in fins:
            def _yi(v):  # 元 → 亿元
                return f"{v / 1e8:.2f}" if isinstance(v, (int, float)) else "—"
            def _pct(v):
                return f"{v:+.1f}%" if isinstance(v, (int, float)) else "—"
            lines.append(
                f"{f['period']} | {_yi(f['revenue'])} | {_pct(f['revenue_yoy'])} | "
                f"{_yi(f['net_profit'])} | {_pct(f['net_profit_yoy'])} | "
                f"{_pct(f['gross_margin'])} | {_pct(f['roe'])} | "
                f"{_pct(f['debt_ratio'])} | "
                f"{f['eps'] if f['eps'] is not None else '—'}"
            )

    # 技术面（趋势/支撑压力/近况）
    try:
        tech = _fetch_technical(symbol, 120)
    except Exception:
        tech = {}
    bars = tech.get("bars") or []
    if bars:
        last = bars[-1]
        lines.append(f"\n## 技术面")
        lines.append(f"趋势信号: {tech.get('signal', 'neutral')}  支撑: {tech.get('support')}  压力: {tech.get('resistance')}")
        lines.append(f"最新收盘: {last.get('close')}  近 120 日区间: "
                     f"{min(b['low'] for b in bars):.2f} ~ {max(b['high'] for b in bars):.2f}")

    # 研报一致预期（评级分布 / 目标价 / EPS·PE）
    try:
        summary = _dbc.reports_summary(symbol)
    except Exception:
        summary = {}
    if summary.get("count"):
        lines.append(f"\n## 机构研报一致预期（近一年 {summary['count']} 篇）")
        if summary.get("ratings"):
            lines.append("评级分布: " + "、".join(f"{k} {v}家" for k, v in summary["ratings"].items()))
        tgt = summary.get("target")
        if tgt:
            lines.append(f"一致目标价: {tgt.get('avg')}（区间 {tgt.get('low')}~{tgt.get('high')}，{tgt.get('count')} 家）")
        eps_pe = []
        for yk, ek, pk in (("今年", "eps_this", "pe_this"), ("明年", "eps_next", "pe_next"),
                           ("后年", "eps_next2", "pe_next2")):
            if summary.get(ek) is not None:
                eps_pe.append(f"{yk} EPS {summary[ek]}/PE {summary.get(pk)}")
        if eps_pe:
            lines.append("一致预期: " + "；".join(eps_pe))

    # 研报标题清单（供 AI 判断逻辑/催化/分歧）
    try:
        reps = _dbc.reports_get(symbol, limit=30)
    except Exception:
        reps = []
    if reps:
        lines.append(f"\n## 近期机构研报标题")
        for r in reps[:30]:
            tp = r.get("target_price")
            lines.append(f"[{r.get('publish_date', '')}] {r.get('org', '')} | "
                         f"{r.get('rating', '')}{f' 目标价{tp}' if tp else ''} | {r.get('title', '')}")

    # 近期公告 / 动态
    try:
        from quantforge.api.routes.news import _fetch_announcements, _format_announcement
        raw = _fetch_announcements(symbol, page_size=20)
        anns = [_format_announcement(it) for it in raw]
    except Exception:
        anns = []
    if anns:
        lines.append(f"\n## 近期公告（{len(anns)} 条）")
        for it in anns[:15]:
            lines.append(f"[{it.get('date', '')}] {it.get('category', '')} | {it.get('title', '')}")

    return "\n".join(lines)


def _onepager_key(symbol: str) -> str:
    """缓存键：含日期 → 跨天自动失效（同日命中，次日重算）。"""
    day = _dt.date.today().isoformat()
    return f"sa:onepager:{str(symbol).strip().upper()}:{day}"


@router.get("/{symbol}/onepager")
async def get_onepager(
    symbol: str,
    refresh: bool = False,
    cached_only: bool = False,
    current_user: dict | None = Depends(get_optional_user),
):
    """公司一页纸（买方视角深度投研报告）。

    点开「AI 深度分析」Tab 才触发；按 symbol+当天日期落库缓存，跨天自动更新。
    单次 LLM 产出整篇 markdown（含表格 / Mermaid），故 max_tokens 与超时都放宽。
    带登录态时 token 用量记到该账号名下。

    ``cached_only=true``：只查当天缓存、命中即返回、未命中返回空（不触发生成）。
    供详情页打开时静默预载——若今天已生成过，无需再点 Tab 即可即时可看。
    """
    from quantforge.api.ai_client import chat

    key = _onepager_key(symbol)
    if not refresh:
        cached = await asyncio.to_thread(_db.get, key, 86400)
        if cached:
            return {**cached, "cached": True}
    if cached_only:
        return {"symbol": symbol, "report": "", "cached": False, "generated_at": ""}

    account = current_user["username"] if current_user else None

    context = await asyncio.to_thread(_onepager_context, symbol)
    try:
        report = await chat(
            _ONEPAGER_SYSTEM, context,
            max_tokens=8192, caller="stock_onepager",
            account=account, timeout=300,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI 深度分析失败: {e}")

    report = (report or "").strip()
    # 去掉模型偶发包裹的 ```markdown 围栏
    if report.startswith("```"):
        report = report.split("\n", 1)[-1]
        if report.endswith("```"):
            report = report[: report.rfind("```")]
        report = report.strip()

    if not report:
        raise HTTPException(status_code=503, detail="AI 深度分析返回为空")

    result = {
        "symbol":       symbol,
        "report":       report,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    await asyncio.to_thread(_db.set, key, result, 86400, "sa_onepager")
    return {**result, "cached": False}


# ── 个股详情预热（自选股 + 高频访问股）───────────────────────────────────────────
# 个股详情页 overview/technical/momentum/fundamental 走的是 SWR 按需缓存——只有被
# 访问过的股票才在库里有缓存，所以「从没人点过的股票」首访要现场串行拉上游(efinance/
# 腾讯/datacenter/研报聚合)，这就是慢的根源。这里把「自选股 + 最近查询过的股」提前
# 预热落库，让它们首屏即从 cache_entries 秒出；冷门股仍首访现拉，但会被纳入下次预热。
#
# 复用各接口同款 _fetch_* + TTL/category，与 watchlist_kline_warmer 一致挂 lifespan。
# 低并发(防上游限流、防饿死请求线程)，盘中 5min / 盘后 30min 循环。

_DETAIL_WARM_CONCURRENCY = 3      # 并发：压低防 efinance/腾讯/datacenter 限流


def _detail_warm_codes() -> list[str]:
    """预热代码集 = 自选股 ∪ 最近查询历史（去重，保序：自选优先）。"""
    codes: list[str] = []
    seen: set[str] = set()
    try:
        for c in _db.watchlist_all_codes() or []:
            cu = str(c).strip().upper()
            if cu and cu not in seen:
                seen.add(cu); codes.append(cu)
    except Exception as e:
        logger.debug(f"detail warm: watchlist codes failed: {e}")
    for h in _load_history():
        cu = str(h.get("symbol") or "").strip().upper()
        if cu and cu not in seen:
            seen.add(cu); codes.append(cu)
    return codes


async def _warm_one_detail(symbol: str) -> None:
    """预热单只个股的 overview/technical/momentum/fundamental，结果落 SWR 缓存。

    只在缓存缺失或已过期时才真正现拉(命中新鲜则各 _serve_swr 直接返回、零外呼)，
    所以稳态下每轮很轻。momentum 最重(含 _fetch_overview + 研报目标价聚合)，但同样
    走缓存，预热一次后页面即从库读。
    """
    from quantforge.api.routes.market import _kline_read_ttl
    kt = _kline_read_ttl()
    # overview（5min 新鲜窗口）
    try:
        await _serve_swr(_swr_key("overview", symbol),
                         lambda: _fetch_overview(symbol), _CACHE_QUOTE, "sa_overview", False)
    except Exception as e:
        logger.debug(f"detail warm overview {symbol}: {e}")
    # technical / momentum（随交易时段 2min/1h）
    for kind, fn in (("technical", lambda: _fetch_technical(symbol, 180)),
                     ("momentum",  lambda: _fetch_momentum(symbol, 180))):
        try:
            await _serve_swr(_swr_key(kind, symbol, ":180"), fn, kt, f"sa_{kind}", False)
        except Exception as e:
            logger.debug(f"detail warm {kind} {symbol}: {e}")
    # fundamental（12h；预热只取股东快路径，龙虎榜由访问时后台补）
    try:
        fkey = _swr_key("fundamental", symbol)
        if await asyncio.to_thread(_db.get, fkey, 12 * 3600) is None:
            data = await asyncio.to_thread(_fetch_fundamental, symbol, False)
            await asyncio.to_thread(_db.set, fkey, data, 12 * 3600, "sa_fundamental")
    except Exception as e:
        logger.debug(f"detail warm fundamental {symbol}: {e}")


async def prewarm_stock_details() -> int:
    """预热自选+高频访问股的个股详情接口缓存。返回预热的代码数。"""
    codes = await asyncio.to_thread(_detail_warm_codes)
    if not codes:
        return 0
    sem = asyncio.Semaphore(_DETAIL_WARM_CONCURRENCY)

    async def _one(c: str):
        async with sem:
            await _warm_one_detail(c)

    await asyncio.gather(*[_one(c) for c in codes])
    return len(codes)


async def stock_detail_warmer() -> None:
    """后台循环：周期性预热个股详情（交易时段 5min，盘后 30min）。"""
    from quantforge.data.feed.snapshot import is_trade_hours
    logger.info("stock_analysis.stock_detail_warmer: starting detail prewarmer")
    while True:
        try:
            n = await prewarm_stock_details()
            if n:
                logger.info(f"stock detail warmer: prewarmed {n} codes")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"stock detail warmer error: {e}")
        await asyncio.sleep(300 if is_trade_hours() else 1800)
