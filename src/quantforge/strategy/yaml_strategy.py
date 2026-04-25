"""YAML-defined natural-language strategy engine.

Borrowing from daily_stock_analysis: strategies are defined in human-readable
YAML files. An LLM agent interprets the strategy rules against live market data
and returns buy/sell/hold signals with reasoning.

Flow:
  1. Load strategy YAML from strategies/yaml/ directory
  2. Fetch recent bars for the target symbol
  3. Call LLM with: strategy definition + market data → signal JSON
  4. Return structured signal with action, reasoning, confidence

Endpoints (API):
  GET  /api/yaml-strategy/list          → list available YAML strategies
  POST /api/yaml-strategy/analyze       → run strategy against a symbol
  GET  /api/yaml-strategy/{name}        → get strategy definition
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

_YAML_DIR = Path("strategies/yaml")

_SIGNAL_SYSTEM_PROMPT = """你是一位专业的A股量化交易分析师。
你将收到一个策略定义（包含进场条件、出场条件和参数）以及目标股票的近期行情数据（OHLCV + 技术指标）。
请严格按照策略规则分析当前市场数据，给出操作信号。

输出格式：严格返回JSON，不要任何markdown，格式如下：
{
  "signal": "BUY" | "SELL" | "HOLD",
  "confidence": 置信度0-100的整数,
  "reasoning": "详细分析过程，说明满足/不满足哪些条件",
  "entry_conditions_met": ["已满足的进场条件列表"],
  "entry_conditions_missing": ["未满足的进场条件列表"],
  "suggested_buy_price": 建议买入价(如果signal是BUY),
  "suggested_stop_price": 建议止损价(如果signal是BUY),
  "suggested_target_price": 建议目标价(如果signal是BUY),
  "risk_warning": "风险提示（如有）"
}
"""


def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    except Exception:
        return None


def list_strategies() -> list[dict]:
    """Return metadata for all available YAML strategies."""
    strategies = []
    if not _YAML_DIR.exists():
        return strategies
    for f in sorted(_YAML_DIR.glob("*.yaml")):
        try:
            content = yaml.safe_load(f.read_text(encoding="utf-8"))
            strategies.append({
                "name":         content.get("name", f.stem),
                "display_name": content.get("display_name", f.stem),
                "description":  content.get("description", "").strip()[:200],
                "file":         f.name,
            })
        except Exception:
            continue
    return strategies


def load_strategy(name: str) -> dict | None:
    """Load a strategy YAML by name or filename stem."""
    if not _YAML_DIR.exists():
        return None
    for f in _YAML_DIR.glob("*.yaml"):
        content = yaml.safe_load(f.read_text(encoding="utf-8"))
        if content.get("name") == name or f.stem == name:
            return content
    return None


async def _fetch_bars(symbol: str, limit: int = 60) -> list[dict]:
    """Fetch recent daily bars for symbol via efinance."""
    try:
        import efinance as ef
        import pandas as pd

        def _get():
            df = ef.stock.get_quote_history(symbol, klt=101)  # daily
            return df.tail(limit)

        df = await asyncio.to_thread(_get)
        bars = []
        for _, row in df.iterrows():
            bars.append({
                "date":   str(row.get("日期", "")),
                "open":   _safe_float(row.get("开盘")),
                "high":   _safe_float(row.get("最高")),
                "low":    _safe_float(row.get("最低")),
                "close":  _safe_float(row.get("收盘")),
                "volume": _safe_float(row.get("成交量")),
            })
        return bars
    except Exception as e:
        logger.warning(f"yaml_strategy: fetch bars failed for {symbol}: {e}")
        return []


def _compute_indicators(bars: list[dict]) -> dict:
    """Compute MA5/MA10/MA20/volume_ratio from raw bars."""
    if len(bars) < 5:
        return {}
    try:
        import pandas as pd
        df = pd.DataFrame(bars)
        close  = df["close"].astype(float)
        volume = df["volume"].astype(float)
        result: dict[str, Any] = {
            "latest_close":   round(float(close.iloc[-1]), 2),
            "latest_volume":  round(float(volume.iloc[-1]), 0),
            "high_20d":       round(float(df["high"].astype(float).tail(20).max()), 2),
            "low_20d":        round(float(df["low"].astype(float).tail(20).min()), 2),
        }
        if len(close) >= 5:
            result["ma5"]  = round(float(close.tail(20).rolling(5).mean().iloc[-1]), 2)
        if len(close) >= 10:
            result["ma10"] = round(float(close.tail(20).rolling(10).mean().iloc[-1]), 2)
        if len(close) >= 20:
            result["ma20"] = round(float(close.tail(25).rolling(20).mean().iloc[-1]), 2)
        if len(volume) >= 10:
            avg_vol = float(volume.tail(11).iloc[:-1].mean())
            if avg_vol > 0:
                result["volume_ratio"] = round(float(volume.iloc[-1]) / avg_vol, 2)
        # Trend
        if "ma5" in result and "ma10" in result and "ma20" in result:
            result["bull_stack"] = result["ma5"] > result["ma10"] > result["ma20"]
        return result
    except Exception as e:
        logger.debug(f"yaml_strategy: indicator compute failed: {e}")
        return {}


def _build_analysis_prompt(strategy: dict, symbol: str, bars: list[dict], indicators: dict) -> str:
    strategy_yaml = yaml.dump(strategy, allow_unicode=True, default_flow_style=False)
    lines = [
        f"目标股票代码：{symbol}",
        "",
        "=== 策略定义 ===",
        strategy_yaml,
        "",
        "=== 技术指标（最新） ===",
    ]
    for k, v in indicators.items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("=== 近期K线数据（最新20根） ===")
    for bar in bars[-20:]:
        lines.append(
            f"  {bar['date']}  开:{bar['open']}  高:{bar['high']}  "
            f"低:{bar['low']}  收:{bar['close']}  量:{bar['volume']}"
        )
    lines.append("")
    lines.append("请根据以上策略条件和市场数据，给出操作信号。")
    return "\n".join(lines)


async def analyze(symbol: str, strategy_name: str) -> dict:
    """Run a YAML strategy against a symbol and return the LLM signal.

    Returns a dict with keys: signal, confidence, reasoning, entry_conditions_met,
    entry_conditions_missing, suggested_buy_price, suggested_stop_price,
    suggested_target_price, risk_warning, strategy_name, symbol.
    """
    strategy = load_strategy(strategy_name)
    if not strategy:
        return {"error": f"Strategy '{strategy_name}' not found"}

    bars = await _fetch_bars(symbol)
    if not bars:
        return {"error": f"No market data for {symbol}"}

    indicators = _compute_indicators(bars)
    user_prompt = _build_analysis_prompt(strategy, symbol, bars, indicators)

    try:
        from quantforge.api.ai_client import chat
        raw = await chat(
            system=_SIGNAL_SYSTEM_PROMPT,
            user=user_prompt,
            max_tokens=2000,
            caller="yaml_strategy",
        )
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        if text.endswith("```"):
            text = text[:text.rfind("```")].strip()

        result = json.loads(text)
        result["strategy_name"] = strategy_name
        result["strategy_display"] = strategy.get("display_name", strategy_name)
        result["symbol"] = symbol
        result["indicators"] = indicators
        return result
    except Exception as e:
        logger.warning(f"yaml_strategy: LLM analysis failed: {e}")
        return {"error": str(e), "strategy_name": strategy_name, "symbol": symbol}
