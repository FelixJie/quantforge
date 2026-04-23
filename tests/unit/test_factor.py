"""Unit tests for factor engine and technical indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantforge.factor.engine import FactorEngine
from quantforge.factor.library.technical import (
    ATRFactor,
    BollingerPositionFactor,
    BollingerWidthFactor,
    MomentumFactor,
    RSIFactor,
    SMAFactor,
    VolumeRatioFactor,
    ZScoreFactor,
    get_default_factors,
)


def make_bar_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame for testing."""
    np.random.seed(seed)
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    close = 10.0 * np.exp(np.cumsum(np.random.normal(0.0, 0.015, n)))
    return pd.DataFrame({
        "datetime": dates,
        "open": close * (1 + np.random.uniform(-0.005, 0.005, n)),
        "high": close * (1 + np.random.uniform(0, 0.02, n)),
        "low": close * (1 - np.random.uniform(0, 0.02, n)),
        "close": close,
        "volume": np.random.randint(1_000_000, 5_000_000, n).astype(float),
        "turnover": np.random.randint(10_000_000, 50_000_000, n).astype(float),
    })


class TestTechnicalFactors:
    def test_sma_length(self):
        df = make_bar_df(50)
        factor = SMAFactor(window=10)
        result = factor.compute(df)
        assert len(result) == 50
        assert result.iloc[:9].isna().all()
        assert result.iloc[10:].notna().all()

    def test_rsi_range(self):
        df = make_bar_df(100)
        factor = RSIFactor(window=14)
        result = factor.compute(df)
        valid = result.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_momentum_values(self):
        df = make_bar_df(30)
        factor = MomentumFactor(window=5)
        result = factor.compute(df)
        # momentum[i] = close[i] / close[i-5] - 1
        expected_idx = 10
        expected = df["close"].iloc[expected_idx] / df["close"].iloc[expected_idx - 5] - 1
        assert abs(result.iloc[expected_idx] - expected) < 1e-9

    def test_zscore_finite(self):
        df = make_bar_df(100)
        factor = ZScoreFactor(window=20)
        result = factor.compute(df).dropna()
        # Z-scores should be finite and have reasonable magnitude
        assert result.notna().all()
        assert (result.abs() < 5).mean() > 0.95  # >95% within ±5σ

    def test_bollinger_position_range(self):
        df = make_bar_df(100)
        factor = BollingerPositionFactor(window=20)
        result = factor.compute(df).dropna()
        # Most values should be within [0, 1]
        in_range = ((result >= -0.5) & (result <= 1.5)).mean()
        assert in_range > 0.95

    def test_atr_positive(self):
        df = make_bar_df(50)
        factor = ATRFactor(window=14)
        result = factor.compute(df).dropna()
        assert (result > 0).all()

    def test_volume_ratio_positive(self):
        df = make_bar_df(50)
        factor = VolumeRatioFactor(window=10)
        result = factor.compute(df).dropna()
        assert (result > 0).all()


class TestFactorEngine:
    def test_compute_adds_columns(self):
        df = make_bar_df(60)
        engine = FactorEngine()
        engine.add_factor(SMAFactor(10))
        engine.add_factor(RSIFactor(14))
        result = engine.compute(df)
        assert "sma_10" in result.columns
        assert "rsi_14" in result.columns
        assert len(result) == len(df)

    def test_compute_drop_na(self):
        df = make_bar_df(60)
        engine = FactorEngine()
        engine.add_factor(SMAFactor(10))
        engine.add_factor(RSIFactor(14))
        result = engine.compute(df, drop_na=True)
        # All factor columns should be non-null
        assert result["sma_10"].notna().all()
        assert result["rsi_14"].notna().all()
        assert len(result) < len(df)

    def test_get_feature_names(self):
        engine = FactorEngine()
        engine.add_factor(SMAFactor(5))
        engine.add_factor(MomentumFactor(10))
        assert engine.get_feature_names() == ["sma_5", "momentum_10"]

    def test_required_lookback(self):
        engine = FactorEngine()
        engine.add_factor(SMAFactor(5))
        engine.add_factor(RSIFactor(14))
        assert engine.required_lookback() == 14

    def test_default_factors_all_compute(self):
        df = make_bar_df(100)
        engine = FactorEngine()
        engine.add_factors(get_default_factors())
        result = engine.compute(df)
        # All factor columns should be present
        for f in get_default_factors():
            assert f.name in result.columns, f"Missing: {f.name}"

    def test_chaining(self):
        engine = (
            FactorEngine()
            .add_factor(SMAFactor(5))
            .add_factor(RSIFactor(14))
        )
        assert len(engine.factors) == 2
