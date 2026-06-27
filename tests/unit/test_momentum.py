"""动能评分纯函数单元测试（不联网、不读库、不走 LLM）。

聚焦两个无副作用的纯函数：
  · _zscore        —— 滚动标准分，验证边界与方向。
  · _dim_mom_vs_price —— 维度2「动能 vs 价格」背离检测，针对记忆中的坑写回归：
      背离要看「区间净变化」而非「z-level 差」，稳步上行不该被误判为顶背离。
另外用 compute_momentum 对一段构造的上行序列做端到端冒烟，确认评分单调倾向。
"""

import numpy as np
import pandas as pd

from quantforge.analysis.momentum import (
    MomentumConfig,
    _zscore,
    _dim_mom_vs_price,
    _momentum_line,
    _to_frame,
    compute_momentum,
)


def test_zscore_constant_series_is_nan():
    # 验证：常数序列标准差为 0，z-score 退化为 NaN（被 0→NaN 保护，不应是 inf）
    s = pd.Series([5.0] * 30)
    z = _zscore(s, win=20)
    assert z.dropna().empty or z.dropna().abs().max() == 0 or np.isnan(z.iloc[-1])


def test_zscore_sign_follows_deviation():
    # 验证：高于近期均值 → z 为正，低于 → z 为负
    s = pd.Series(list(range(30)), dtype=float)  # 单调上升，最新值高于滚动均值
    z = _zscore(s, win=20)
    assert z.iloc[-1] > 0
    # 末尾突然下探一根，应转负
    s2 = s.copy()
    s2.iloc[-1] = -50.0
    z2 = _zscore(s2, win=20)
    assert z2.iloc[-1] < 0


def _steady_uptrend_frame(n=80, start=10.0, step=0.15):
    # 价格稳步小幅上行；high/low 围绕 close 给个固定带宽
    closes = [start + i * step for i in range(n)]
    bars = []
    for i, c in enumerate(closes):
        bars.append({
            "date": f"2024{(i // 28) + 1:02d}{(i % 28) + 1:02d}",
            "open": c - 0.02, "high": c + 0.05, "low": c - 0.05,
            "close": c, "volume": 1000,
        })
    return _to_frame(bars)


def test_divergence_does_not_false_flag_steady_uptrend():
    # 回归（记忆中的坑）：稳步上行（价涨、动能高位走平）不该被判成顶背离。
    # 若维度2 用「z-level 差」会把高位走平误判为动能下滑 → 强负；正确用「区间净变化」
    # 时，动能净变化≈0 或为正，bear 不触发，维度2 不应给出明显负分。
    cfg = MomentumConfig()
    df = _steady_uptrend_frame()
    line = _momentum_line(df, cfg)
    d_price = _dim_mom_vs_price(line, df["close"], cfg)
    last = float(d_price.iloc[-1])
    # 不该被误杀为顶背离（强负）；允许温和确认（≥0 附近）
    assert last > -0.2, f"稳步上行被误判为背离, 维度2 末值={last}"


def test_top_divergence_is_penalised():
    # 验证：价格创新高但动能掉头向下 → 维度2 给出明显负分（顶背离应被惩罚）
    cfg = MomentumConfig()
    df = _steady_uptrend_frame()
    line = _momentum_line(df, cfg)
    close = df["close"]
    # 人为构造顶背离：close 维持上行，但动能线近窗口净降（末段动能强行压低）
    w = cfg.div_window
    line2 = line.copy()
    line2.iloc[-w:] = line.iloc[-w] - np.linspace(0, 0.5, w)  # 动能区间净降
    d_price = _dim_mom_vs_price(line2, close, cfg)
    assert float(d_price.iloc[-1]) < -0.2


def test_bottom_divergence_is_rewarded():
    # 验证：价格创新低但动能掉头向上 → 维度2 给出正分（底背离偏多）
    cfg = MomentumConfig()
    n = 80
    closes = [20.0 - i * 0.1 for i in range(n)]  # 稳步下行
    bars = [{
        "date": f"2024{(i // 28) + 1:02d}{(i % 28) + 1:02d}",
        "open": c, "high": c + 0.05, "low": c - 0.05, "close": c, "volume": 1000,
    } for i, c in enumerate(closes)]
    df = _to_frame(bars)
    line = _momentum_line(df, cfg)
    w = cfg.div_window
    line2 = line.copy()
    line2.iloc[-w:] = line.iloc[-w] + np.linspace(0, 0.5, w)  # 动能区间净升
    d_price = _dim_mom_vs_price(line2, df["close"], cfg)
    assert float(d_price.iloc[-1]) > 0.0


def test_dim_mom_vs_price_bounded():
    # 验证：维度2 子分恒在 [-1, 1]，且无 NaN（评分映射依赖该有界性）
    cfg = MomentumConfig()
    df = _steady_uptrend_frame()
    line = _momentum_line(df, cfg)
    d = _dim_mom_vs_price(line, df["close"], cfg)
    assert d.min() >= -1.0 and d.max() <= 1.0
    assert not d.isna().any()


def test_compute_momentum_uptrend_scores_above_neutral():
    # 端到端冒烟：一段稳步上行序列，最新动能评分应高于中性 50（趋势股得分够高）
    df = _steady_uptrend_frame(n=80)
    bars = df.to_dict("records")
    res = compute_momentum(bars)
    assert res["current"] is not None
    scores = [s for s in res["score"] if s is not None]
    assert scores, "score 序列不应为空"
    assert scores[-1] > 50.0


def test_compute_momentum_short_input_returns_empty():
    # 验证：K 线不足 30 根时返回空结构（不报错、current=None）
    bars = [{"date": f"2024010{i+1}", "open": 10, "high": 10.1,
             "low": 9.9, "close": 10, "volume": 100} for i in range(10)]
    res = compute_momentum(bars)
    assert res["current"] is None
    assert res["score"] == []
