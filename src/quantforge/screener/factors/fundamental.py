"""Fundamental factor extraction for stock screening.

Available columns from efinance get_realtime_quotes():
  name, code, change_pct, price, pe, pb, market_cap, circulating_cap, turnover_rate
  (roe, industry available when enrich_fundamentals=True)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ── Individual factor functions ───────────────────────────────────────────────

def compute_value_factor(df: pd.DataFrame) -> pd.Series:
    """Earnings yield = 1/PE. Higher = cheaper (classic value).

    Used in: Graham Value, GARP, Balanced, Blue-chip Value
    """
    pe = df["pe"].copy() if "pe" in df.columns else pd.Series(np.nan, index=df.index)
    pe = pe.where((pe > 0) & (pe < 300))
    return (1.0 / pe).rename("factor_value")


def compute_pb_factor(df: pd.DataFrame) -> pd.Series:
    """Book-value yield = 1/PB. Higher = cheaper."""
    pb = df["pb"].copy() if "pb" in df.columns else pd.Series(np.nan, index=df.index)
    pb = pb.where((pb > 0) & (pb < 50))
    return (1.0 / pb).rename("factor_pb")


def compute_graham_factor(df: pd.DataFrame) -> pd.Series:
    """Graham composite: 1 / (PE × PB).

    Benjamin Graham's famous safety criterion: PE × PB < 22.5
    Higher score = further from danger zone (better bargain).
    Works best combined with absolute PE/PB filters.

    Used in: Graham Value strategy
    """
    pe = df["pe"].copy() if "pe" in df.columns else pd.Series(np.nan, index=df.index)
    pb = df["pb"].copy() if "pb" in df.columns else pd.Series(np.nan, index=df.index)
    pe = pe.where((pe > 0) & (pe < 200))
    pb = pb.where((pb > 0) & (pb < 30))
    product = pe * pb
    # Clip to avoid huge values from very small PE*PB
    product = product.where(product > 0.5)
    return (1.0 / product).rename("factor_graham")


def compute_value_composite_factor(df: pd.DataFrame) -> pd.Series:
    """Fama-French HML-style value composite = mean of earnings yield + book yield.

    Equal-weight combination of earnings yield (1/PE) and book yield (1/PB),
    each first z-scored independently. More robust than using either alone.

    Used in: Balanced Multi-factor, Quality-Value
    """
    pe = df["pe"].copy() if "pe" in df.columns else pd.Series(np.nan, index=df.index)
    pb = df["pb"].copy() if "pb" in df.columns else pd.Series(np.nan, index=df.index)
    pe = pe.where((pe > 0) & (pe < 300))
    pb = pb.where((pb > 0) & (pb < 50))

    ey = (1.0 / pe)
    by = (1.0 / pb)

    def _z(s):
        valid = s.dropna()
        if len(valid) < 5 or valid.std() == 0:
            return pd.Series(0.0, index=s.index)
        return ((s - valid.mean()) / valid.std()).fillna(0)

    return ((_z(ey) + _z(by)) / 2.0).rename("factor_value_composite")


def compute_momentum_factor(df: pd.DataFrame) -> pd.Series:
    """Short-term price momentum = today's change_pct.

    Positive momentum → upward price pressure.
    Note: A full cross-sectional momentum factor would use 12-1 month returns.
    Since we only have real-time data, this is a 1-day price change proxy.

    Used in: Momentum, Small-cap Growth
    """
    if "change_pct" in df.columns:
        return df["change_pct"].rename("factor_momentum")
    return pd.Series(np.nan, index=df.index, name="factor_momentum")


def compute_size_factor(df: pd.DataFrame) -> pd.Series:
    """Small-cap factor: -log(market_cap). Higher score for smaller caps.

    Fama-French SMB (Small Minus Big) — small caps have historically
    outperformed large caps in A-shares over long horizons.

    Used in: Small-cap Growth, Balanced
    """
    if "market_cap" in df.columns:
        log_cap = np.log1p(df["market_cap"].clip(lower=1))
        return (-log_cap).rename("factor_size")
    return pd.Series(np.nan, index=df.index, name="factor_size")


def compute_large_cap_factor(df: pd.DataFrame) -> pd.Series:
    """Large-cap stability factor: log(market_cap). Higher = bigger = more stable.

    Inverse of size factor. Used in Blue-chip / Defensive strategies
    where large market cap is a quality indicator (harder to manipulate,
    more analyst coverage, more liquid).

    Used in: Blue-chip Value, Defensive Value
    """
    if "market_cap" in df.columns:
        log_cap = np.log1p(df["market_cap"].clip(lower=1))
        return log_cap.rename("factor_large_cap")
    return pd.Series(np.nan, index=df.index, name="factor_large_cap")


def compute_liquidity_factor(df: pd.DataFrame) -> pd.Series:
    """Turnover rate — higher means more actively traded.

    High liquidity reduces execution slippage and market impact.
    Especially important for momentum strategies.

    Used in: Momentum, Sentiment-driven
    """
    if "turnover_rate" in df.columns:
        tr = df["turnover_rate"].copy()
        tr = tr.where(tr > 0)
        return tr.rename("factor_liquidity")
    return pd.Series(np.nan, index=df.index, name="factor_liquidity")


def compute_quality_factor(df: pd.DataFrame) -> pd.Series:
    """ROE quality factor — higher ROE = better shareholder returns.

    Profitability as a quality signal (JoinQuant / RiceQuant standard).
    Best combined with value filters to avoid overpaying for quality.

    Used in: Quality-Value, High-quality Growth, GARP, Balanced
    Requires: enrich_fundamentals=True
    """
    if "roe" in df.columns:
        roe = df["roe"].copy()
        roe = roe.where(roe > -50)  # clip extreme negatives (distressed stocks)
        return roe.rename("factor_quality")
    return pd.Series(np.nan, index=df.index, name="factor_quality")


def compute_float_ratio_factor(df: pd.DataFrame) -> pd.Series:
    """Float ratio = circulating_cap / market_cap.

    High float ratio → more tradeable shares → less likely to be manipulated.
    Low float stocks are susceptible to ramping / pump-and-dump schemes.
    Useful as a quality/safety filter in Chinese A-share market.

    Used in: Blue-chip Value, Defensive Value
    """
    if "market_cap" in df.columns and "circulating_cap" in df.columns:
        mc = df["market_cap"].clip(lower=1)
        cc = df["circulating_cap"].clip(lower=0)
        ratio = (cc / mc).clip(0, 1)
        return ratio.rename("factor_float_ratio")
    return pd.Series(np.nan, index=df.index, name="factor_float_ratio")


# ── Factor registry ───────────────────────────────────────────────────────────

FACTOR_REGISTRY: dict[str, dict] = {
    "value": {
        "fn": compute_value_factor,
        "label": "价值 (低PE)",
        "description": "收益率 = 1/PE，PE越低得分越高。Benjamin Graham、巴菲特最看重的核心指标。",
        "default_weight": 0.30,
        "higher_is_better": True,
        "data_source": "实时行情",
    },
    "pb": {
        "fn": compute_pb_factor,
        "label": "低PB (净资产折价)",
        "description": "净资产收益率 = 1/PB，PB越低说明以低于净资产的价格买到公司。",
        "default_weight": 0.15,
        "higher_is_better": True,
        "data_source": "实时行情",
    },
    "graham": {
        "fn": compute_graham_factor,
        "label": "Graham安全边际",
        "description": "1/(PE×PB)，Graham要求PE×PB<22.5。得分越高说明双重低估，安全边际越大。",
        "default_weight": 0.00,
        "higher_is_better": True,
        "data_source": "实时行情",
    },
    "value_composite": {
        "fn": compute_value_composite_factor,
        "label": "价值合成 (PE+PB)",
        "description": "Fama-French HML风格：综合收益率(1/PE)和账面收益率(1/PB)各50%，比单一指标更稳健。",
        "default_weight": 0.00,
        "higher_is_better": True,
        "data_source": "实时行情",
    },
    "momentum": {
        "fn": compute_momentum_factor,
        "label": "动量 (近期涨跌)",
        "description": "近期价格涨跌幅，正动量趋势得分更高。JoinQuant研究显示A股动量效应显著。",
        "default_weight": 0.20,
        "higher_is_better": True,
        "data_source": "实时行情",
    },
    "size": {
        "fn": compute_size_factor,
        "label": "小市值",
        "description": "市值越小得分越高（Fama-French SMB因子）。A股小盘效应历史上显著，但流动性风险高。",
        "default_weight": 0.10,
        "higher_is_better": True,
        "data_source": "实时行情",
    },
    "large_cap": {
        "fn": compute_large_cap_factor,
        "label": "大市值 (蓝筹)",
        "description": "市值越大得分越高，代表蓝筹股稳定性。分析师覆盖多，信息透明度高，适合防御策略。",
        "default_weight": 0.00,
        "higher_is_better": True,
        "data_source": "实时行情",
    },
    "liquidity": {
        "fn": compute_liquidity_factor,
        "label": "流动性 (换手率)",
        "description": "换手率越高流动性越好，适合主动交易策略。但过高换手率可能意味着投机情绪。",
        "default_weight": 0.10,
        "higher_is_better": True,
        "data_source": "实时行情",
    },
    "quality": {
        "fn": compute_quality_factor,
        "label": "质量 (ROE)",
        "description": "净资产收益率（ROE）越高质量越好。RiceQuant核心因子，需开启基本面数据增强。",
        "default_weight": 0.00,
        "higher_is_better": True,
        "data_source": "基本面增强",
    },
    "float_ratio": {
        "fn": compute_float_ratio_factor,
        "label": "流通比例",
        "description": "流通市值/总市值，比例越高越难被主力操控，适合作为风险控制因子。",
        "default_weight": 0.00,
        "higher_is_better": True,
        "data_source": "实时行情",
    },
}
