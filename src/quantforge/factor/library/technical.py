"""Technical analysis factors.

All factors accept a standard OHLCV DataFrame and return a pd.Series.
No external TA-Lib dependency — implemented with pandas/numpy only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantforge.factor.base import Factor


# ── Trend / Moving Average ──────────────────────────────────────────────────

class SMAFactor(Factor):
    """Simple Moving Average of close price."""
    category = "technical"

    def __init__(self, window: int = 20):
        self.window = window
        self.name = f"sma_{window}"
        self.description = f"Simple Moving Average ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].rolling(self.window).mean()


class EMAFactor(Factor):
    """Exponential Moving Average of close price."""
    category = "technical"

    def __init__(self, window: int = 20):
        self.window = window
        self.name = f"ema_{window}"
        self.description = f"Exponential Moving Average ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].ewm(span=self.window, adjust=False).mean()


class MACDFactor(Factor):
    """MACD histogram (fast_ema - slow_ema - signal)."""
    category = "technical"

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.window = slow + signal
        self.name = f"macd_{fast}_{slow}_{signal}"
        self.description = f"MACD histogram ({fast},{slow},{signal})"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.signal, adjust=False).mean()
        return macd_line - signal_line  # histogram


class MACrossSignalFactor(Factor):
    """MA crossover signal: +1 (fast > slow), -1 (fast < slow), 0 (equal)."""
    category = "technical"

    def __init__(self, fast: int = 10, slow: int = 30):
        self.fast = fast
        self.slow = slow
        self.window = slow
        self.name = f"ma_cross_{fast}_{slow}"
        self.description = f"MA crossover signal ({fast}/{slow})"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        fast_ma = close.rolling(self.fast).mean()
        slow_ma = close.rolling(self.slow).mean()
        return np.sign(fast_ma - slow_ma)


# ── Momentum ─────────────────────────────────────────────────────────────────

class ROCFactor(Factor):
    """Rate of Change: (close_t - close_{t-n}) / close_{t-n}."""
    category = "technical"

    def __init__(self, window: int = 10):
        self.window = window
        self.name = f"roc_{window}"
        self.description = f"Rate of Change ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        return close.pct_change(self.window)


class RSIFactor(Factor):
    """Relative Strength Index."""
    category = "technical"

    def __init__(self, window: int = 14):
        self.window = window
        self.name = f"rsi_{window}"
        self.description = f"RSI ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(self.window).mean()
        loss = (-delta.clip(upper=0)).rolling(self.window).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))


class MomentumFactor(Factor):
    """Raw price momentum: close / close_{t-n} - 1."""
    category = "technical"

    def __init__(self, window: int = 20):
        self.window = window
        self.name = f"momentum_{window}"
        self.description = f"Price momentum ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"] / df["close"].shift(self.window) - 1


class StochasticFactor(Factor):
    """Stochastic %K oscillator."""
    category = "technical"

    def __init__(self, window: int = 14):
        self.window = window
        self.name = f"stoch_{window}"
        self.description = f"Stochastic %K ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        low_min = df["low"].rolling(self.window).min()
        high_max = df["high"].rolling(self.window).max()
        denom = high_max - low_min
        return ((df["close"] - low_min) / denom.replace(0, np.nan)) * 100


# ── Volatility ────────────────────────────────────────────────────────────────

class ATRFactor(Factor):
    """Average True Range — measures volatility."""
    category = "technical"

    def __init__(self, window: int = 14):
        self.window = window
        self.name = f"atr_{window}"
        self.description = f"ATR ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        high, low, close = df["high"], df["low"], df["close"]
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(self.window).mean()


class ATRPctFactor(Factor):
    """ATR as percentage of close price (normalised volatility)."""
    category = "technical"

    def __init__(self, window: int = 14):
        self.window = window
        self.name = f"atr_pct_{window}"
        self.description = f"ATR% ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        atr = ATRFactor(self.window).compute(df)
        return atr / df["close"]


class BollingerWidthFactor(Factor):
    """Bollinger Band width: (upper - lower) / middle."""
    category = "technical"

    def __init__(self, window: int = 20, std_dev: float = 2.0):
        self.window = window
        self.std_dev = std_dev
        self.name = f"bb_width_{window}"
        self.description = f"Bollinger Band Width ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        middle = close.rolling(self.window).mean()
        std = close.rolling(self.window).std()
        upper = middle + self.std_dev * std
        lower = middle - self.std_dev * std
        return (upper - lower) / middle.replace(0, np.nan)


class BollingerPositionFactor(Factor):
    """%B: position within Bollinger Bands. 0=lower, 0.5=middle, 1=upper."""
    category = "technical"

    def __init__(self, window: int = 20, std_dev: float = 2.0):
        self.window = window
        self.std_dev = std_dev
        self.name = f"bb_pos_{window}"
        self.description = f"Bollinger %B ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        middle = close.rolling(self.window).mean()
        std = close.rolling(self.window).std()
        upper = middle + self.std_dev * std
        lower = middle - self.std_dev * std
        denom = upper - lower
        return (close - lower) / denom.replace(0, np.nan)


# ── Volume ────────────────────────────────────────────────────────────────────

class VolumeRatioFactor(Factor):
    """Volume ratio: today's volume / N-day average volume."""
    category = "technical"

    def __init__(self, window: int = 20):
        self.window = window
        self.name = f"vol_ratio_{window}"
        self.description = f"Volume ratio ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        vol_ma = df["volume"].rolling(self.window).mean()
        return df["volume"] / vol_ma.replace(0, np.nan)


class OBVFactor(Factor):
    """On-Balance Volume (cumulative)."""
    category = "technical"
    window = 1

    def __init__(self):
        self.name = "obv"
        self.description = "On-Balance Volume"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        direction = np.sign(df["close"].diff())
        direction.iloc[0] = 0
        return (direction * df["volume"]).cumsum()


class TurnoverRateFactor(Factor):
    """Turnover rate: turnover amount normalised by N-day average."""
    category = "technical"

    def __init__(self, window: int = 20):
        self.window = window
        self.name = f"turnover_rate_{window}"
        self.description = f"Turnover rate ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "turnover" if "turnover" in df.columns else "volume"
        ma = df[col].rolling(self.window).mean()
        return df[col] / ma.replace(0, np.nan)


# ── Mean Reversion ────────────────────────────────────────────────────────────

class ZScoreFactor(Factor):
    """Z-score of close relative to rolling mean (mean-reversion signal)."""
    category = "technical"

    def __init__(self, window: int = 20):
        self.window = window
        self.name = f"zscore_{window}"
        self.description = f"Price Z-score ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        mu = close.rolling(self.window).mean()
        sigma = close.rolling(self.window).std()
        return (close - mu) / sigma.replace(0, np.nan)


class DistanceFromMAFactor(Factor):
    """Percentage distance of close from moving average."""
    category = "technical"

    def __init__(self, window: int = 20):
        self.window = window
        self.name = f"dist_ma_{window}"
        self.description = f"Distance from MA ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        ma = df["close"].rolling(self.window).mean()
        return (df["close"] - ma) / ma.replace(0, np.nan)


# ── Price / Structure ──────────────────────────────────────────────────────────

class HighLowRangeFactor(Factor):
    """N-day high-low range as % of close."""
    category = "technical"

    def __init__(self, window: int = 20):
        self.window = window
        self.name = f"hl_range_{window}"
        self.description = f"High-Low range ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        high = df["high"].rolling(self.window).max()
        low = df["low"].rolling(self.window).min()
        return (high - low) / df["close"]


class CloseToHighFactor(Factor):
    """Distance of close from N-day high (0=at high, -1=at low)."""
    category = "technical"

    def __init__(self, window: int = 20):
        self.window = window
        self.name = f"close_to_high_{window}"
        self.description = f"Close-to-high ratio ({window}d)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        high = df["high"].rolling(self.window).max()
        low = df["low"].rolling(self.window).min()
        denom = high - low
        return (df["close"] - high) / denom.replace(0, np.nan)


class BodyRatioFactor(Factor):
    """Candle body ratio: |close-open| / (high-low)."""
    category = "technical"
    window = 1
    name = "body_ratio"
    description = "Candle body ratio"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        body = (df["close"] - df["open"]).abs()
        wick = (df["high"] - df["low"]).replace(0, np.nan)
        return body / wick


# ── Registry ──────────────────────────────────────────────────────────────────

ALL_FACTORS: list[type[Factor]] = [
    SMAFactor, EMAFactor, MACDFactor, MACrossSignalFactor,
    ROCFactor, RSIFactor, MomentumFactor, StochasticFactor,
    ATRFactor, ATRPctFactor, BollingerWidthFactor, BollingerPositionFactor,
    VolumeRatioFactor, OBVFactor, TurnoverRateFactor,
    ZScoreFactor, DistanceFromMAFactor,
    HighLowRangeFactor, CloseToHighFactor, BodyRatioFactor,
]


def get_default_factors() -> list[Factor]:
    """Return a standard set of technical factors for feature engineering."""
    return [
        MomentumFactor(5), MomentumFactor(10), MomentumFactor(20),
        RSIFactor(14),
        MACDFactor(),
        ATRPctFactor(14),
        BollingerPositionFactor(20),
        BollingerWidthFactor(20),
        VolumeRatioFactor(20),
        TurnoverRateFactor(20),
        ZScoreFactor(20),
        DistanceFromMAFactor(5), DistanceFromMAFactor(20),
        HighLowRangeFactor(20),
        BodyRatioFactor(),
    ]
