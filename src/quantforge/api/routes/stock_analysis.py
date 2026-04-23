"""Individual stock analysis endpoints.

Endpoints:
  GET  /api/stock-analysis/{symbol}/overview     — quote + basic info
  GET  /api/stock-analysis/{symbol}/technical    — bars + indicators
  GET  /api/stock-analysis/{symbol}/fundamental  — financials + holders
  POST /api/stock-analysis/{symbol}/ai           — AI comprehensive analysis
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import math
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from loguru import logger

router = APIRouter(prefix="/stock-analysis", tags=["stock-analysis"])

_CACHE_DIR    = Path("data/cache/stock_analysis")
_CACHE_TTL    = 86400          # 24 hours — refreshed on explicit user request
_CACHE_QUOTE  = 5 * 60        # 5 min for real-time quote (overview)
_HISTORY_FILE = Path("data/cache/stock_analysis_history.json")


# ── Cache ──────────────────────────────────────────────────────────────────────

def _cache_load(key: str, ttl: int = _CACHE_TTL) -> dict | None:
    f = _CACHE_DIR / f"{key}.json"
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        ts = _dt.datetime.fromisoformat(d.get("_ts", "2000-01-01"))
        if (_dt.datetime.now() - ts).total_seconds() > ttl:
            return None
        return d
    except Exception:
        return None


def _cache_save(key: str, data: dict):
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data["_ts"] = _dt.datetime.now().isoformat()
        (_CACHE_DIR / f"{key}.json").write_text(
            json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception:
        pass


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

    # Fallback name from code prefix
    if not result.get("name"):
        result["name"] = symbol

    return result


def _fetch_technical(symbol: str, days: int = 180) -> dict:
    """Fetch daily bars and compute technical indicators.

    Priority: 1) local parquet if recent, 2) efinance network (always fresh).
    """
    bars = _load_bars_parquet(symbol, days)
    if bars:
        # If parquet data is stale (>7 days behind today), fetch fresh data from efinance
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


def _fetch_fundamental(symbol: str) -> dict:
    """Fetch financial fundamentals and top holders."""
    import efinance as ef

    result: dict = {}

    # Top 10 holders
    try:
        df = ef.stock.get_top10_stock_holder_info(symbol, top=2)
        if df is not None and not df.empty:
            holders = []
            for _, row in df.iterrows():
                try:
                    holders.append({
                        "report_date": str(row.iloc[1])[:10],
                        "name":        str(row.iloc[2]),
                        "type":        str(row.iloc[3]),
                        "shares":      _safe_float(row.iloc[4]),
                        "pct":         _safe_float(row.iloc[5]),
                        "change":      str(row.iloc[6]),
                    })
                except Exception:
                    continue
            result["holders"] = holders[:20]  # latest 20 entries (top10 × 2 reports)
    except Exception as e:
        logger.warning(f"get_top10_stock_holder_info failed: {e}")
        result["holders"] = []

    # Daily billboard (龙虎榜) — last 30 days
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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/history")
async def get_history():
    """Return recent query history (last 20 symbols)."""
    return {"history": _load_history()}


@router.get("/{symbol}/overview")
async def get_overview(symbol: str, refresh: bool = False):
    ck = f"overview_{symbol}"
    if not refresh:
        cached = _cache_load(ck, ttl=_CACHE_QUOTE)
        if cached:
            return cached

    try:
        data = await asyncio.to_thread(_fetch_overview, symbol)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    _cache_save(ck, data)
    # Save to query history
    _save_to_history(symbol, data.get("name", symbol))
    return data


@router.get("/{symbol}/technical")
async def get_technical(symbol: str, days: int = 180, refresh: bool = False):
    ck = f"technical_{symbol}_{days}"
    if not refresh:
        cached = _cache_load(ck, ttl=_CACHE_TTL)
        if cached:
            return cached

    try:
        data = await asyncio.to_thread(_fetch_technical, symbol, days)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    _cache_save(ck, data)
    return data


@router.get("/{symbol}/fundamental")
async def get_fundamental(symbol: str, refresh: bool = False):
    ck = f"fundamental_{symbol}"
    if not refresh:
        cached = _cache_load(ck, ttl=_CACHE_TTL)
        if cached:
            return cached

    try:
        data = await asyncio.to_thread(_fetch_fundamental, symbol)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    _cache_save(ck, data)
    return data


class AiAnalysisRequest(BaseModel):
    extra_prompt: Optional[str] = None


@router.post("/{symbol}/ai")
async def ai_analysis(symbol: str, body: Optional[AiAnalysisRequest] = None):
    """Comprehensive AI analysis combining technical, fundamental, and news data."""
    from quantforge.api.ai_client import chat
    import requests

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
        raw = await chat(system, user_msg, max_tokens=1024, caller="stock_analysis")
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
