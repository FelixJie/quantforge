"""Feature engineering utilities for ML models."""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_lag_features(
    df: pd.DataFrame,
    cols: list[str],
    lags: list[int] | None = None,
) -> pd.DataFrame:
    """Add lagged versions of selected columns.

    Example: lags=[1, 2, 5] for column 'rsi_14' adds
    'rsi_14_lag1', 'rsi_14_lag2', 'rsi_14_lag5'.
    """
    lags = lags or [1, 2, 5]
    result = df.copy()
    for col in cols:
        if col not in df.columns:
            continue
        for lag in lags:
            result[f"{col}_lag{lag}"] = df[col].shift(lag)
    return result


def add_rolling_stats(
    df: pd.DataFrame,
    cols: list[str],
    windows: list[int] | None = None,
) -> pd.DataFrame:
    """Add rolling mean and std for selected columns."""
    windows = windows or [5, 10]
    result = df.copy()
    for col in cols:
        if col not in df.columns:
            continue
        for w in windows:
            result[f"{col}_rmean{w}"] = df[col].rolling(w).mean()
            result[f"{col}_rstd{w}"] = df[col].rolling(w).std()
    return result


def cross_sectional_rank(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Replace each factor value with its cross-sectional rank (0-1) on each date.

    Requires a 'datetime' column in df (for multi-symbol panels).
    If single-symbol, ranks across the time series.
    """
    result = df.copy()
    if "datetime" in df.columns and df["symbol"].nunique() > 1 if "symbol" in df.columns else False:
        for col in cols:
            if col not in df.columns:
                continue
            result[col] = (
                df.groupby("datetime")[col]
                .rank(pct=True, na_option="keep")
            )
    else:
        for col in cols:
            if col not in df.columns:
                continue
            result[col] = df[col].rank(pct=True, na_option="keep")
    return result


def winsorize(
    df: pd.DataFrame,
    cols: list[str],
    lower: float = 0.01,
    upper: float = 0.99,
) -> pd.DataFrame:
    """Clip extreme values at given quantile percentiles."""
    result = df.copy()
    for col in cols:
        if col not in df.columns:
            continue
        lo = df[col].quantile(lower)
        hi = df[col].quantile(upper)
        result[col] = df[col].clip(lo, hi)
    return result


def standardize(
    df: pd.DataFrame,
    cols: list[str],
) -> pd.DataFrame:
    """Z-score standardize selected columns (mean=0, std=1)."""
    result = df.copy()
    for col in cols:
        if col not in df.columns:
            continue
        mu = df[col].mean()
        sigma = df[col].std()
        result[col] = (df[col] - mu) / sigma if sigma > 0 else 0.0
    return result


def build_feature_matrix(
    df: pd.DataFrame,
    factor_cols: list[str],
    target_col: str = "fwd_return_1d",
    add_lags: bool = True,
    lag_list: list[int] | None = None,
    winsorize_pct: float = 0.01,
    standardize_features: bool = True,
    drop_na: bool = True,
) -> tuple[pd.DataFrame, pd.Series]:
    """Full feature engineering pipeline: winsorize → lag → standardize → split X/y.

    Returns:
        (X, y) where X is the feature matrix and y is the target series.
    """
    result = df.copy()

    # Winsorize raw factors
    result = winsorize(result, factor_cols, winsorize_pct, 1 - winsorize_pct)

    # Add lag features
    if add_lags:
        result = add_lag_features(result, factor_cols, lag_list or [1, 2, 5])

    # Collect all feature columns (original + lags)
    all_feature_cols = [
        c for c in result.columns
        if c in factor_cols
        or any(c.startswith(f"{fc}_lag") for fc in factor_cols)
    ]

    # Standardize
    if standardize_features:
        result = standardize(result, all_feature_cols)

    # Split X / y
    if target_col not in result.columns:
        raise ValueError(f"Target column '{target_col}' not found in DataFrame.")

    X = result[all_feature_cols]
    y = result[target_col]

    if drop_na:
        mask = X.notna().all(axis=1) & y.notna()
        X = X[mask]
        y = y[mask]

    return X, y
