"""Momentum analysis → buy/sell point estimation (rule-based, explainable).

Pure-computation module: no IO, no network. Given a list of OHLCV bars it
produces a 0–100 momentum score per bar, a direction/state classification,
ATR-anchored buy/stop/target levels, and a sequence of historical buy/sell
signals (for K-line annotation and backtest verification).

Reuses the existing factor library (no re-implementation):
  ATRFactor / RSIFactor / MACDFactor / ROCFactor / MomentumFactor /
  VolumeRatioFactor / BollingerPositionFactor — see
  ``quantforge.factor.library.technical``.

Self-test:
    python -m quantforge.analysis.momentum
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quantforge.factor.library.technical import (
    ATRFactor,
    ATRPctFactor,
    BollingerPositionFactor,
    MACDFactor,
    MomentumFactor,
    ROCFactor,
    RSIFactor,
    VolumeRatioFactor,
)


# ── Config ───────────────────────────────────────────────────────────────────

@dataclass
class MomentumConfig:
    """Tunable weights / windows for momentum scoring and level estimation.

    Weights are applied to bounded sub-scores in [-1, 1]; the weighted sum is
    scaled to roughly ±50 around a neutral midpoint of 50.
    """

    # sub-factor windows
    rsi_window: int = 14
    roc_window: int = 10
    mom_window: int = 20
    vol_window: int = 20
    boll_window: int = 20
    atr_window: int = 14

    # sub-score weights (relative; normalised internally)
    w_trend: float = 1.0      # MACD histogram sign + slope
    w_strength: float = 1.0   # RSI around 50
    w_price_mom: float = 1.0  # ROC / Momentum
    w_volume: float = 0.6     # volume ratio confirmation
    w_position: float = 0.5   # Bollinger %B — penalise extremes (anti-chase)

    # ── 四维动能框架 ────────────────────────────────────────────────────────
    # 动能评分不再只看「当下强弱」，而是从四个相互独立的维度交叉印证：
    #   维度1 动能 vs 自身历史 —— 当前动能相对它自己过去的水位（z 分），过热回拉。
    #   维度2 动能 vs 价格      —— 动能与价格谁领先：动能领先=蓄势/确认，价格领先=顶背离。
    #   维度3 动能 vs 大盘/板块 —— 相对强弱：个股区间收益减基准收益，跑赢才算真强。
    #   维度4 反向动能          —— 衰竭/反转压力（超买、动能掉头、放量长上影、MACD 收敛），作减分。
    # 各维度子分均在 [-1, 1]（维度4 为 [-1, 0] 的纯压力项），加权合成后映射到 0–100。
    w_self_history: float = 1.0   # 维度1 权重
    w_mom_vs_price: float = 1.0   # 维度2 权重
    w_relative: float = 1.0       # 维度3 权重（无基准时自动退出加权）
    w_reverse: float = 0.8        # 维度4 权重（反向压力减分）

    sh_window: int = 60           # 维度1：自身历史回看窗口
    div_window: int = 20          # 维度2：动能-价格背离比较窗口
    rs_window: int = 20           # 维度3：相对强弱区间窗口
    rev_window: int = 10          # 维度4：反向动能短期掉头窗口
    overheat_z: float = 2.5       # 维度1：自身历史 z 超过此值视为过热、向中性回拉

    # score → state thresholds
    buy_threshold: float = 62.0
    sell_threshold: float = 38.0
    reduce_threshold: float = 50.0
    rsi_overheat: float = 78.0   # block fresh buy when RSI too hot

    # ATR-anchored level multipliers
    k_stop: float = 2.0
    k_target: float = 3.0
    max_stop_pct: float = 8.0    # cap stop risk (AI-Picks convention)
    sr_window: int = 20          # support/resistance lookback

    # ── risk-warning thresholds (technical / volatility) ──
    rsi_overbought: float = 72.0     # 高位超买
    atr_pct_high: float = 5.0        # ATR/价 高于此判为高波动 (%)
    drawdown_warn: float = 12.0      # 距近高回撤超过此值预警 (%)
    drawdown_window: int = 60        # 回撤参照的高点窗口
    bb_pos_high: float = 0.95        # %B 接近上轨 → 净值回落风险
    vol_spike_ratio: float = 2.0     # 放量阈值 (量比)

    weights: tuple = field(default=(), repr=False)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _clip01(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _safe(v) -> float | None:
    """Return a JSON-safe float (None for NaN/inf)."""
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


# ── Core ─────────────────────────────────────────────────────────────────────

def _to_frame(bars: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ── 四维动能：连续动能线与子维度 ─────────────────────────────────────────────────

def _momentum_line(df: pd.DataFrame, cfg: MomentumConfig) -> pd.Series:
    """连续动能线 = ROC + 归一化 MACD 柱 + RSI 偏离 50。

    这是一条「无量纲的动能强弱时间序列」，维度1（与自身历史比）、维度2（与价格比）
    都以它为标的——保证四个维度衡量的是同一个「动能」对象，只是参照系不同。
    """
    close = df["close"].replace(0, np.nan)
    roc = ROCFactor(cfg.roc_window).compute(df).fillna(0.0)
    macd_hist = MACDFactor().compute(df)
    macd_n = (macd_hist / close).fillna(0.0)
    rsi = RSIFactor(cfg.rsi_window).compute(df)
    rsi_c = ((rsi - 50) / 50.0).fillna(0.0)
    return roc * 1.0 + macd_n * 1.0 + rsi_c * 0.5


def _zscore(s: pd.Series, win: int) -> pd.Series:
    """滚动标准分：当前值相对最近 ``win`` 根的均值/标准差。"""
    mp = max(5, win // 2)
    mean = s.rolling(win, min_periods=mp).mean()
    std = s.rolling(win, min_periods=mp).std().replace(0, np.nan)
    return (s - mean) / std


def _dim_self_history(line: pd.Series, cfg: MomentumConfig) -> pd.Series:
    """维度1 · 动能 vs 自身历史：动能的绝对强弱，并以「相对自身历史水位」修正。

    主体是动能线本身的强度（tanh 压缩）——动能强→正、弱→负，保证趋势股得分够高。
    再以相对自身常态的 z 分做两点修正：①高于/低于自身常态时温和加/减分（确认）；
    ②超过 ``overheat_z`` 的极端过热向下回拉，避免追在「动能已冲到自身极值」的顶部。
    """
    strength = np.tanh(line * 3.0)                          # 绝对动能强度（主体）
    z = _zscore(line, cfg.sh_window)
    confirm = np.tanh(z / 3.0) * 0.25                       # 相对自身常态的确认/背离
    over = (z - cfg.overheat_z).clip(lower=0)               # 仅上方极端过热
    taper = np.tanh(over) * 0.4
    return (strength + confirm - taper).clip(-1, 1).fillna(0.0)


def _dim_mom_vs_price(line: pd.Series, close: pd.Series, cfg: MomentumConfig) -> pd.Series:
    """维度2 · 动能 vs 价格：价格与动能是否同步（背离检测）。

    默认中性，仅在「真背离」时给强信号——健康的稳步上行（价涨、动能高位走平）不该被
    当成背离误杀：
      · 顶背离(偏空)：价格创窗口新高，但动能近期掉头向下 → 强负。
      · 底背离(偏多)：价格创窗口新低，但动能近期掉头向上 → 强正。
      · 其余：以动能自身方向给一个温和的确认分（动能为正→小幅确认价格）。
    """
    w = cfg.div_window
    base = np.tanh(line * 1.5) * 0.3                        # 温和确认（动能方向）

    pc = close.pct_change(w)                                # 区间价格净变化
    ms = line.diff(w)                                       # 区间动能净变化（平滑，抗噪）

    # 顶背离：价格净涨 但 动能净降——惩罚 ∝ 动能下滑幅度（健康的高位走平≈0，不误杀）
    bear = ((pc > 0.01) & (ms < 0)).astype(float)
    bear_mag = (np.tanh((-ms) * 3.0).clip(0, 1)) * bear
    # 底背离：价格净跌 但 动能净升——蓄势反转（偏多）
    bull = ((pc < -0.01) & (ms > 0)).astype(float)
    bull_mag = (np.tanh(ms * 3.0).clip(0, 1)) * bull

    out = base - bear_mag * 0.9 + bull_mag * 0.7
    return out.clip(-1, 1).fillna(0.0)


def _dim_relative(close: pd.Series, bench: pd.Series | None, cfg: MomentumConfig) -> pd.Series:
    """维度3 · 动能 vs 大盘/板块：区间相对强弱 = 个股收益 − 基准收益。

    >0 跑赢基准（真强），<0 跑输（随大流甚至更弱）。无基准（bench=None）时返回全 0，
    由 ``_score_series`` 把该维度权重退出加权，优雅降级。
    """
    if bench is None:
        return pd.Series(0.0, index=close.index)
    bench = bench.reindex(close.index).ffill()
    if bench.dropna().empty:
        return pd.Series(0.0, index=close.index)
    w = cfg.rs_window
    stock_ret = close / close.shift(w) - 1.0
    bench_ret = bench / bench.shift(w) - 1.0
    rs = (stock_ret - bench_ret).fillna(0.0)
    return np.tanh(rs * 6.0).clip(-1, 1)


def _dim_reverse(df: pd.DataFrame, line: pd.Series, rsi: pd.Series,
                 cfg: MomentumConfig) -> pd.Series:
    """维度4 · 反向动能：衰竭/反转压力（返回 [-1, 0]，压力越大越负，作减分）。

    汇集四类反向信号：①RSI 超买；②动能线近 ``rev_window`` 掉头向下；
    ③放量长上影（冲高回落出货）；④MACD 柱由强转弱（动能收敛）。
    """
    close = df["close"]
    pressure = pd.Series(0.0, index=df.index)

    # ① 超买：RSI 高于 70 的部分（0~1）
    pressure = pressure + ((rsi - 70.0) / 30.0).clip(lower=0).fillna(0.0)

    # ② 动能掉头：动能线近 rev_window 的净变化为负
    mom_turn = (-line.diff(cfg.rev_window)).clip(lower=0)
    pressure = pressure + np.tanh(mom_turn * 4.0)

    # ③ 放量长上影：量比偏高 且 收盘远离当日最高（冲高回落）
    vr = VolumeRatioFactor(cfg.vol_window).compute(df).fillna(1.0)
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    upper_frac = ((df["high"] - close) / rng).clip(0, 1).fillna(0.0)
    blowoff = (vr - 1.5).clip(lower=0) * upper_frac
    pressure = pressure + np.tanh(blowoff).clip(0, 1)

    # ④ MACD 柱收敛：柱较前一根走弱（按价格归一）
    macd_hist = MACDFactor().compute(df)
    hist_fall = (-macd_hist.diff()).clip(lower=0) / close.replace(0, np.nan)
    pressure = pressure + np.tanh(hist_fall.fillna(0.0) * 50.0) * 0.5

    pressure = pressure.clip(0, 2)
    return (-np.tanh(pressure)).clip(-1, 0)


def _score_series(df: pd.DataFrame, cfg: MomentumConfig,
                  bench: pd.Series | None = None) -> tuple[pd.Series, pd.DataFrame]:
    """四维动能合成每根 K 线的 0–100 评分。

    返回 ``(score, dims)``：``dims`` 为四列子维度序列（self/price/market/reverse），
    各列已在 [-1, 1]（reverse 在 [-1, 0]），供快照读取最新一根做可解释展示。
    """
    close = df["close"]
    rsi = RSIFactor(cfg.rsi_window).compute(df)
    line = _momentum_line(df, cfg)

    d_self = _dim_self_history(line, cfg)
    d_price = _dim_mom_vs_price(line, close, cfg)
    d_market = _dim_relative(close, bench, cfg)
    d_reverse = _dim_reverse(df, line, rsi, cfg)

    # 无基准时把维度3 的权重退出加权（避免被恒 0 稀释总分）
    w_market = cfg.w_relative if bench is not None and not d_market.eq(0).all() else 0.0
    wsum = (cfg.w_self_history + cfg.w_mom_vs_price + w_market + cfg.w_reverse) or 1.0

    contrib = (
        cfg.w_self_history * d_self
        + cfg.w_mom_vs_price * d_price
        + w_market * d_market
        + cfg.w_reverse * d_reverse
    ) / wsum

    score = (50 + contrib * 50).clip(0, 100)
    dims = pd.DataFrame({
        "self": d_self,
        "price": d_price,
        "market": d_market,
        "reverse": d_reverse,
    })
    return score, dims


def _dim_readout(dims: pd.DataFrame, bench_available: bool, bench_label: str = "大盘") -> dict:
    """把最新一根的四维子分整理成可读快照（数值 + 档位标签 + 一句话解读）。

    子分原始范围 [-1, 1]，展示时放大到 [-100, 100] 便于阅读；维度4 用 0–100 的
    「衰竭压力」表达（压力越大越偏空）。
    """
    if dims.empty:
        return {}
    last = dims.iloc[-1]

    def _val(x):
        f = _safe(x)
        return None if f is None else round(f * 100, 0)

    def _band(v, pos, neg):
        if v is None:
            return "—"
        if v >= 35:
            return pos[0]
        if v <= -35:
            return neg[0]
        if v >= 12:
            return pos[1]
        if v <= -12:
            return neg[1]
        return "中性"

    s = _val(last["self"])
    p = _val(last["price"])
    m = _val(last["market"]) if bench_available else None
    rev_pressure = _val(-last["reverse"])   # [-1,0] → 0~100 压力

    self_band = _band(s, ("强势扩张", "温和走强"), ("明显走弱", "略弱于常态"))
    price_band = _band(p, ("动能领先", "小幅领先"), ("顶背离", "动能略滞后"))
    market_band = _band(m, ("显著跑赢", "小幅跑赢"), ("明显跑输", "略跑输")) if m is not None else "无基准"
    rev_band = ("高" if (rev_pressure or 0) >= 55 else
                "中" if (rev_pressure or 0) >= 25 else "低")

    return {
        "self_history": {
            "score": s, "label": self_band,
            "desc": "当前动能相对自身历史水位",
        },
        "mom_vs_price": {
            "score": p, "label": price_band,
            "desc": "动能与价格谁领先（>0蓄势/<0顶背离）",
        },
        "vs_market": {
            "score": m, "label": market_band, "benchmark": bench_label if bench_available else None,
            "desc": f"相对{bench_label}的区间强弱" if bench_available else "缺基准，未计入",
        },
        "reverse": {
            "score": rev_pressure, "label": rev_band,
            "desc": "反向/衰竭压力（超买·掉头·放量长上影·MACD收敛）",
        },
    }


def _classify_direction(score: pd.Series) -> list[str | None]:
    """accelerating | rising | flat | falling from score first/second diff."""
    d1 = score.diff()
    d2 = d1.diff()
    out: list[str | None] = []
    for i in range(len(score)):
        s1 = d1.iloc[i]
        s2 = d2.iloc[i]
        if pd.isna(s1):
            out.append(None)
        elif s1 > 0.5 and (not pd.isna(s2) and s2 > 0):
            out.append("accelerating")
        elif s1 > 0.3:
            out.append("rising")
        elif s1 < -0.3:
            out.append("falling")
        else:
            out.append("flat")
    return out


def _classify_state(score: pd.Series, rsi: pd.Series, cfg: MomentumConfig) -> list[str | None]:
    """buy | hold | reduce | sell per bar (with RSI overheat protection)."""
    out: list[str | None] = []
    for i in range(len(score)):
        s = score.iloc[i]
        r = rsi.iloc[i]
        if pd.isna(s):
            out.append(None)
        elif s >= cfg.buy_threshold and not (not pd.isna(r) and r >= cfg.rsi_overheat):
            out.append("buy")
        elif s <= cfg.sell_threshold:
            out.append("sell")
        elif s < cfg.reduce_threshold:
            out.append("reduce")
        else:
            out.append("hold")
    return out


def _extract_signals(df: pd.DataFrame, score: pd.Series, state: list) -> list[dict]:
    """Mark bars where state transitions into buy / sell."""
    signals: list[dict] = []
    prev = None
    for i in range(len(df)):
        st = state[i]
        if st in ("buy", "sell") and st != prev:
            row = df.iloc[i]
            date = row.get("date")
            if date is None and "datetime" in df.columns:
                date = row.get("datetime")
            signals.append({
                "date": str(date) if date is not None else None,
                "price": _round(row["close"]),
                "type": st,
                "score": _round(score.iloc[i], 1),
                "reason": ("动能转强突破阈值" if st == "buy" else "动能转弱跌破阈值"),
            })
        if st in ("buy", "sell"):
            prev = st
        elif st in ("hold", "reduce"):
            # neutral states don't reset; only the opposite extreme flips `prev`
            pass
    return signals


def _estimate_levels(df: pd.DataFrame, atr: pd.Series, cfg: MomentumConfig) -> dict:
    """ATR-anchored buy/stop/target with support/resistance bounds."""
    close = float(df["close"].iloc[-1])
    a = _safe(atr.iloc[-1])
    n = cfg.sr_window
    lows = df["low"].tail(n)
    highs = df["high"].tail(n)
    support = _safe(lows.min())
    resistance = _safe(highs.max())

    buy_price = close
    if a is None or a <= 0:
        return {
            "buy_price": _round(buy_price),
            "stop_price": None, "target_price": None,
            "stop_pct": None, "target_pct": None, "rr": None,
            "atr": _round(a, 3), "support": _round(support), "resistance": _round(resistance),
        }

    stop_price = buy_price - cfg.k_stop * a
    # cap stop risk
    min_stop = buy_price * (1 - cfg.max_stop_pct / 100.0)
    if stop_price < min_stop:
        stop_price = min_stop
    # don't place stop above a recent support if support is below price
    if support is not None and support < buy_price:
        stop_price = min(stop_price, support * 0.995)

    target_price = buy_price + cfg.k_target * a
    if resistance is not None and resistance > buy_price:
        target_price = min(target_price, resistance)

    stop_pct = (buy_price - stop_price) / buy_price * 100 if buy_price else None
    target_pct = (target_price - buy_price) / buy_price * 100 if buy_price else None
    rr = (target_pct / stop_pct) if (stop_pct and stop_pct > 0) else None

    return {
        "buy_price": _round(buy_price),
        "stop_price": _round(stop_price),
        "target_price": _round(target_price),
        "stop_pct": _round(stop_pct),
        "target_pct": _round(target_pct),
        "rr": _round(rr),
        "atr": _round(a, 3),
        "support": _round(support),
        "resistance": _round(resistance),
    }


def _assess_technical_risk(
    df: pd.DataFrame, score: pd.Series, rsi: pd.Series, atr: pd.Series, cfg: MomentumConfig
) -> dict:
    """技术/波动维度的前瞻风险预警（纯计算）。

    返回 {level: 低|中|高, items: [{type, level, msg}], ...metrics}。
    估值/研报维度的风险在 API 层补充（需要外部数据）。
    """
    items: list[dict] = []
    close = df["close"]
    last = float(close.iloc[-1])

    # 1) 高位超买：RSI 过热
    r = _safe(rsi.iloc[-1])
    if r is not None and r >= cfg.rsi_overbought:
        items.append({"type": "overbought", "level": "高" if r >= cfg.rsi_overheat else "中",
                      "msg": f"RSI {r:.0f} 处于超买区，短线回调风险上升"})

    # 2) 高波动：ATR%
    atr_pct = ATRPctFactor(cfg.atr_window).compute(df)
    ap = _safe(atr_pct.iloc[-1])
    ap = ap * 100 if ap is not None else None
    if ap is not None and ap >= cfg.atr_pct_high:
        items.append({"type": "volatility", "level": "中",
                      "msg": f"日均波幅 {ap:.1f}%，波动偏大，注意仓位与止损"})

    # 3) 高位回撤：距近 N 日高点的回撤
    win = min(cfg.drawdown_window, len(close))
    recent_high = float(close.tail(win).max())
    dd = (recent_high - last) / recent_high * 100 if recent_high else 0
    if dd >= cfg.drawdown_warn:
        items.append({"type": "drawdown", "level": "高" if dd >= cfg.drawdown_warn * 1.8 else "中",
                      "msg": f"已自 {win} 日高点回撤 {dd:.1f}%，趋势走弱"})

    # 4) 动能衰竭背离：价创新高但动能分未创新高
    if len(score) >= 10 and len(close) >= 10:
        price_high_now = last >= float(close.tail(win).max()) * 0.995
        s_now = _safe(score.iloc[-1]) or 0
        s_prev_max = _safe(score.tail(win).iloc[:-1].max()) or 0
        if price_high_now and s_now < s_prev_max - 6:
            items.append({"type": "divergence", "level": "中",
                          "msg": "价格接近新高但动能未同步走强，存在顶背离风险"})

    # 5) 净值回落：%B 贴上轨
    bb = BollingerPositionFactor(cfg.boll_window).compute(df)
    bp = _safe(bb.iloc[-1])
    if bp is not None and bp >= cfg.bb_pos_high:
        items.append({"type": "band_extreme", "level": "中",
                      "msg": "价格触及布林上轨，短期超买、均值回落概率升高"})

    # 6) 量价背离：放量滞涨
    vr = VolumeRatioFactor(cfg.vol_window).compute(df)
    v = _safe(vr.iloc[-1])
    chg = (last / float(close.iloc[-2]) - 1) * 100 if len(close) >= 2 and close.iloc[-2] else 0
    if v is not None and v >= cfg.vol_spike_ratio and chg < 0.5:
        items.append({"type": "vol_price", "level": "中",
                      "msg": f"放量({v:.1f}倍)但价格滞涨，可能为高位换手出货"})

    # 汇总等级：取最高
    order = {"低": 0, "中": 1, "高": 2}
    level = "低"
    for it in items:
        if order.get(it["level"], 0) > order.get(level, 0):
            level = it["level"]

    return {
        "level": level,
        "items": items,
        "rsi": _round(r, 1),
        "atr_pct": _round(ap, 2),
        "drawdown_pct": _round(dd, 2),
        "recent_high": _round(recent_high),
    }


def _technical_target(df: pd.DataFrame, atr: pd.Series, cfg: MomentumConfig) -> dict:
    """技术面目标价：ATR 投射 + 近 N 日压力位封顶。"""
    last = float(df["close"].iloc[-1])
    a = _safe(atr.iloc[-1])
    resistance = _safe(df["high"].tail(cfg.sr_window).max())
    if a is None or a <= 0:
        return {"target": _round(resistance), "method": "压力位", "upside_pct": None}
    proj = last + cfg.k_target * a
    target = proj
    method = "ATR投射"
    if resistance is not None and resistance > last:
        target = min(proj, resistance)
        method = "ATR投射(压力位封顶)" if proj > resistance else "ATR投射"
    upside = (target - last) / last * 100 if last else None
    return {"target": _round(target), "method": method, "upside_pct": _round(upside)}


def _align_benchmark(df: pd.DataFrame, benchmark_bars: list[dict] | None) -> pd.Series | None:
    """把基准（大盘/板块）K 线按日期对齐到个股 df 上，返回收盘价序列。

    个股与基准的交易日通常一致，但停牌/新股会缺位——以日期对齐 + 前向填充，
    保证维度3 的相对强弱按同一窗口比较。无基准或无日期列时返回 None。
    """
    if not benchmark_bars or "date" not in df.columns:
        return None
    bmap: dict[str, float] = {}
    for b in benchmark_bars:
        d = b.get("date") or b.get("datetime")
        c = _safe(b.get("close"))
        if d is not None and c is not None:
            bmap[str(d)] = c
    if not bmap:
        return None
    bench = df["date"].astype(str).map(bmap).astype("float64")
    bench = bench.ffill()
    return bench if bench.notna().any() else None


def compute_momentum(bars: list[dict], cfg: MomentumConfig | None = None,
                     benchmark_bars: list[dict] | None = None,
                     benchmark_label: str = "大盘") -> dict:
    """Compute momentum score + buy/sell levels + historical signals.

    评分采用四维动能框架（自身历史 / 与价格 / 与大盘板块 / 反向动能），见
    ``_score_series``。``benchmark_bars`` 为大盘或板块的日 K（如沪深300），用于
    维度3 的相对强弱；缺省时维度3 自动退出加权，其余三维照常工作。

    Args:
        bars: ascending OHLCV dicts, keys ``date/open/high/low/close/volume``
              (``datetime`` also accepted for the date field).
        cfg:  optional MomentumConfig; defaults are used when None.
        benchmark_bars: optional benchmark daily bars for relative-strength.

    Returns:
        dict with per-bar arrays (``score``/``direction``/``state``/``atr``),
        ``signals`` list, and a ``current`` snapshot with executable levels +
        ``dimensions`` (四维动能快照).
    """
    cfg = cfg or MomentumConfig()
    if not bars or len(bars) < 30:
        return {"score": [], "direction": [], "state": [], "atr": [],
                "signals": [], "current": None}

    df = _to_frame(bars)
    bench = _align_benchmark(df, benchmark_bars)
    score, dims = _score_series(df, cfg, bench)
    rsi = RSIFactor(cfg.rsi_window).compute(df)
    atr = ATRFactor(cfg.atr_window).compute(df)

    direction = _classify_direction(score)
    state = _classify_state(score, rsi, cfg)
    signals = _extract_signals(df, score, state)
    levels = _estimate_levels(df, atr, cfg)
    risk = _assess_technical_risk(df, score, rsi, atr, cfg)
    tech_target = _technical_target(df, atr, cfg)
    dimensions = _dim_readout(dims, bench_available=bench is not None,
                              bench_label=benchmark_label)

    current = {
        "score": _round(score.iloc[-1], 1),
        "direction": direction[-1],
        "state": state[-1],
        "rsi": _round(rsi.iloc[-1], 1),
        "dimensions": dimensions,     # 四维动能快照（自身历史/与价格/与大盘/反向）
        **levels,
    }

    return {
        "score": [_round(v, 1) for v in score.tolist()],
        "direction": direction,
        "state": state,
        "atr": [_round(v, 3) for v in atr.tolist()],
        "signals": signals,
        "current": current,
        "risk": risk,                 # 技术/波动维度（API 层补估值维度）
        "tech_target": tech_target,   # 技术面目标价（API 层补研报一致目标价）
        "config": {
            "buy_threshold": cfg.buy_threshold,
            "sell_threshold": cfg.sell_threshold,
        },
    }


# ── Self-test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import random

    # Synthetic: uptrend then pullback — score should rise then fall.
    random.seed(7)
    px = 10.0
    bars: list[dict] = []
    for i in range(120):
        drift = 0.06 if i < 70 else -0.05
        px = max(1.0, px * (1 + drift / 10 + random.uniform(-0.015, 0.015)))
        hi = px * (1 + random.uniform(0, 0.02))
        lo = px * (1 - random.uniform(0, 0.02))
        op = lo + (hi - lo) * random.random()
        bars.append({
            "date": f"2025-{1 + i // 30:02d}-{1 + i % 30:02d}",
            "open": round(op, 2), "high": round(hi, 2),
            "low": round(lo, 2), "close": round(px, 2),
            "volume": int(1e6 * (1 + random.uniform(-0.3, 0.5))),
        })

    # 合成一个「大盘」基准：始终温和上行，便于检验维度3 相对强弱（个股前段跑赢、后段跑输）
    bench: list[dict] = []
    bpx = 100.0
    for i in range(120):
        bpx *= 1 + 0.002 + random.uniform(-0.005, 0.005)
        bench.append({"date": bars[i]["date"], "open": bpx, "high": bpx,
                      "low": bpx, "close": round(bpx, 2), "volume": 1})

    res = compute_momentum(bars, benchmark_bars=bench)
    print("current:", json.dumps(res["current"], ensure_ascii=False, indent=2))
    print("dimensions:", json.dumps(res["current"]["dimensions"], ensure_ascii=False, indent=2))
    print("risk:", json.dumps(res["risk"], ensure_ascii=False, indent=2))
    print("tech_target:", json.dumps(res["tech_target"], ensure_ascii=False))
    print("n_signals:", len(res["signals"]))
    print("first 3 signals:", json.dumps(res["signals"][:3], ensure_ascii=False))
    mid_score = res["score"][60]
    late_score = res["score"][-1]
    print(f"score@60(uptrend)={mid_score}  score@end(pullback)={late_score}")
    assert res["current"] is not None
    assert res["current"]["buy_price"] is not None
    assert res["current"]["dimensions"], "四维动能快照应非空"
    assert mid_score > late_score, "上行段动能应高于回落段"
    # 无基准时维度3 应优雅降级（vs_market 标记无基准）
    res2 = compute_momentum(bars)
    assert res2["current"]["dimensions"]["vs_market"]["score"] is None
    print("OK")
