"""Pring KST analysis → 中长线周期买卖点 (rule-based, explainable).

实现马丁·普林格(Martin Pring)的 KST(Know Sure Thing) 动量指标与"六阶段
市场周期"判定。纯计算模块：无 IO、无网络，给一组 OHLCV bars，产出最新一根的
KST / 信号线 / 直方差、长周期 KST 方向、所处周期阶段、买卖点状态，以及
ATR 锚定的买入/止损/目标价。

KST 由四段不同周期的 ROC(变动率) 分别平滑(SMA)后按权重(1/2/3/4)加权合成，
过滤短期噪音、捕捉中期主趋势。最佳买点：KST 上穿其信号线(金叉)，且发生在
零轴下方或附近(周期底部/回升初期)，而非高位追涨。

与 ``momentum.py`` 输出结构对齐(score/state/direction/buy_price/...)，方便
ai_picks 在两套策略间无缝切换。

Self-test:
    python -m quantforge.analysis.pring
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PringConfig:
    """KST 四段 ROC 周期/平滑/权重 + 趋势确认参数(普林格经典日线参数)。"""

    roc1_period: int = 10
    roc1_sma: int = 10
    roc1_weight: float = 1.0
    roc2_period: int = 15
    roc2_sma: int = 10
    roc2_weight: float = 2.0
    roc3_period: int = 20
    roc3_sma: int = 10
    roc3_weight: float = 3.0
    roc4_period: int = 30
    roc4_sma: int = 15
    roc4_weight: float = 4.0

    signal_period: int = 9      # KST 信号线 SMA 周期
    long_kst_sma: int = 21      # 长周期 KST(对 KST 再平滑)用于判中期主趋势方向
    ma_trend_period: int = 50   # 趋势同步确认均线

    # 价位锚定(与 ai_picks 约定一致)
    atr_window: int = 14
    k_stop: float = 2.0
    k_target: float = 3.0
    max_stop_pct: float = 8.0
    sr_window: int = 20

    # 金叉"接近零轴"的容差：KST 不高于 zero_band * 近一年KST幅度 时视为低位金叉
    zero_band_frac: float = 0.25


# ── helpers ──────────────────────────────────────────────────────────────────

def _safe(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _round(v, n: int = 2):
    f = _safe(v)
    return None if f is None else round(f, n)


def _to_frame(bars: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _roc(close: pd.Series, n: int) -> pd.Series:
    return (close / close.shift(n) - 1.0) * 100.0


def _atr(df: pd.DataFrame, window: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(window, min_periods=1).mean()


# ── core ─────────────────────────────────────────────────────────────────────

def compute_kst(df: pd.DataFrame, cfg: PringConfig) -> pd.DataFrame:
    """返回带 kst / kst_signal / kst_long 列的 DataFrame。"""
    close = df["close"]
    r1 = _roc(close, cfg.roc1_period).rolling(cfg.roc1_sma, min_periods=1).mean()
    r2 = _roc(close, cfg.roc2_period).rolling(cfg.roc2_sma, min_periods=1).mean()
    r3 = _roc(close, cfg.roc3_period).rolling(cfg.roc3_sma, min_periods=1).mean()
    r4 = _roc(close, cfg.roc4_period).rolling(cfg.roc4_sma, min_periods=1).mean()
    kst = (r1 * cfg.roc1_weight + r2 * cfg.roc2_weight
           + r3 * cfg.roc3_weight + r4 * cfg.roc4_weight)
    df = df.copy()
    df["kst"] = kst
    df["kst_signal"] = kst.rolling(cfg.signal_period, min_periods=1).mean()
    df["kst_long"] = kst.rolling(cfg.long_kst_sma, min_periods=1).mean()
    return df


# 普林格六阶段(简化版，仅用单只个股的 KST 形态近似定位，不引宏观利率)：
#   1 见底回升  2 加速上行  3 上行趋缓(高位)  4 见顶回落  5 加速下行  6 下行趋缓(底部)
_STAGE_CN = {
    1: "阶段一·见底回升", 2: "阶段二·加速上行", 3: "阶段三·上行趋缓",
    4: "阶段四·见顶回落", 5: "阶段五·加速下行", 6: "阶段六·下行筑底",
}


def _classify_stage(kst: float, kst_slope: float, long_slope: float, zero_band: float) -> int:
    """按 KST 位置(零轴上/下)与短/长周期斜率方向近似落到六阶段之一。"""
    below_zero = kst < 0
    near_zero = abs(kst) <= zero_band
    rising = kst_slope > 0
    long_up = long_slope >= 0
    if below_zero:
        if rising and long_up:
            return 1                     # 零下回升、长周期转好 → 见底回升
        if rising:
            return 6                     # 零下回升但长周期仍弱 → 下行筑底
        return 5                         # 零下且仍在跌 → 加速下行
    # 零轴上方
    if rising and long_up:
        return 2 if not near_zero else 1  # 零上加速上行(刚过零轴算回升尾段)
    if not rising and long_up:
        return 3                         # 零上但短线趋缓、长周期仍多 → 上行趋缓
    return 4                             # 零上且转头向下 → 见顶回落


def analyze(bars: list[dict], cfg: PringConfig | None = None) -> dict | None:
    """对一只个股的日线 bars 计算普林格 KST 周期买卖点。

    返回结构与 momentum.compute 的 ``current`` 对齐：
        {score, state, direction, kst, kst_signal, stage, stage_label,
         golden_cross, buy_price, stop_price, target_price,
         stop_pct, target_pct, rr, support, resistance, ma50, last_signal}
    bars 不足以计算时返回 None。
    """
    cfg = cfg or PringConfig()
    if not bars or len(bars) < cfg.roc4_period + cfg.roc4_sma + 10:
        return None
    df = _to_frame(bars)
    if df["close"].isna().all():
        return None

    df = compute_kst(df, cfg)
    df["ma_trend"] = df["close"].rolling(cfg.ma_trend_period, min_periods=1).mean()
    df["atr"] = _atr(df, cfg.atr_window)

    if df["kst"].isna().all():
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last

    kst = _safe(last["kst"])
    sig = _safe(last["kst_signal"])
    if kst is None or sig is None:
        return None
    kst_prev = _safe(prev["kst"])
    sig_prev = _safe(prev["kst_signal"])
    long_now = _safe(last["kst_long"])
    long_prev = _safe(prev["kst_long"])

    # KST 幅度(近一年绝对值的稳健尺度)→ 用于零轴附近容差
    span = df["kst"].abs().tail(250)
    band = _safe(span.quantile(0.6)) or 0.0
    zero_band = band * cfg.zero_band_frac

    kst_slope = (kst - kst_prev) if kst_prev is not None else 0.0
    long_slope = (long_now - long_prev) if (long_now is not None and long_prev is not None) else 0.0

    # 金叉/死叉：KST 与信号线的穿越
    golden = (kst_prev is not None and sig_prev is not None
              and kst_prev <= sig_prev and kst > sig)
    death = (kst_prev is not None and sig_prev is not None
             and kst_prev >= sig_prev and kst < sig)
    above_sig = kst > sig
    low_position = kst <= zero_band          # 零轴下方或附近(优质金叉区)

    close = _safe(last["close"])
    ma50 = _safe(last["ma_trend"])
    price_above_ma = close is not None and ma50 is not None and close >= ma50
    ma50_up = ma50 is not None and _safe(prev["ma_trend"]) is not None and ma50 >= _safe(prev["ma_trend"])

    stage = _classify_stage(kst, kst_slope, long_slope, zero_band)

    # state：明确买点 = 低位金叉 + 长周期方向向上 + 站上MA50。
    # 高位金叉(零上偏高)只算 hold(趋势中可持有但非新买点)。
    if golden and low_position and long_slope >= 0 and price_above_ma:
        state = "buy"
    elif death and kst > zero_band:
        state = "sell"                       # 高位死叉 → 卖点
    elif death:
        state = "reduce"
    elif above_sig and long_slope >= 0:
        state = "hold"
    elif kst_slope < 0 and long_slope < 0:
        state = "sell"
    else:
        state = "hold"

    direction = ("accelerating" if kst_slope > 0 and long_slope > 0
                 else "rising" if kst_slope > 0
                 else "falling" if kst_slope < 0
                 else "flat")

    # 0–100 评分：金叉 + 低位 + 长周期多头 + 站上MA50 综合加分，便于和动能排序对齐
    score = 50.0
    if above_sig:
        score += 12
    if golden:
        score += 10
    if low_position and above_sig:
        score += 12          # 低位金叉最优质
    if long_slope >= 0:
        score += 8
    if price_above_ma:
        score += 6
    if ma50_up:
        score += 4
    if kst < 0 and kst_slope > 0:
        score += 6           # 零下转头向上
    if state in ("sell", "reduce"):
        score -= 25
    score = max(0.0, min(100.0, score))

    # ATR 锚定价位
    atr = _safe(last["atr"])
    buy_price = stop_price = target_price = stop_pct = target_pct = rr = None
    if close and atr and atr > 0:
        buy_price = round(close, 2)
        raw_stop = close - cfg.k_stop * atr
        # 限制最大止损幅度
        min_stop = close * (1 - cfg.max_stop_pct / 100)
        stop_price = round(max(raw_stop, min_stop), 2)
        target_price = round(close + cfg.k_target * atr, 2)
        stop_pct = round((close - stop_price) / close * 100, 1)
        target_pct = round((target_price - close) / close * 100, 1)
        risk = close - stop_price
        rr = round((target_price - close) / risk, 2) if risk > 0 else None

    win = df.tail(cfg.sr_window)
    support = _round(win["low"].min())
    resistance = _round(win["high"].max())

    return {
        "score": round(score, 1),
        "state": state,
        "direction": direction,
        "kst": _round(kst, 2),
        "kst_signal": _round(sig, 2),
        "kst_long": _round(long_now, 2),
        "stage": stage,
        "stage_label": _STAGE_CN.get(stage, ""),
        "golden_cross": bool(golden),
        "low_position": bool(low_position),
        "buy_price": buy_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "stop_pct": stop_pct,
        "target_pct": target_pct,
        "rr": rr,
        "support": support,
        "resistance": resistance,
        "ma50": _round(ma50, 2),
        "last_signal": {"type": "golden" if golden else "death" if death else "none"},
    }


if __name__ == "__main__":  # pragma: no cover
    import random
    random.seed(7)
    price = 10.0
    bars = []
    for i in range(200):
        price *= 1 + random.uniform(-0.03, 0.035)
        bars.append({
            "open": price * 0.99, "high": price * 1.02,
            "low": price * 0.98, "close": price, "volume": 1e6,
        })
    out = analyze(bars)
    import json
    print(json.dumps(out, ensure_ascii=False, indent=2))
