"""Factor analysis utilities: IC, decay, correlation, and turnover."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def information_coefficient(
    factor_values: pd.Series,
    forward_returns: pd.Series,
    method: str = "spearman",
) -> float:
    """Compute the Information Coefficient (IC) between factor and forward returns.

    IC is the rank correlation between factor values today and
    stock returns over the next N days.

    Args:
        factor_values: Factor values at time t.
        forward_returns: Returns from t to t+N (same index).
        method: "spearman" (rank) or "pearson" (linear).

    Returns:
        IC as float in [-1, 1].
    """
    mask = factor_values.notna() & forward_returns.notna()
    if mask.sum() < 5:
        return float("nan")

    f = factor_values[mask]
    r = forward_returns[mask]

    if method == "spearman":
        ic, _ = stats.spearmanr(f, r)
    else:
        ic, _ = stats.pearsonr(f, r)

    return float(ic)


def rolling_ic(
    factor_df: pd.DataFrame,
    factor_col: str,
    return_col: str,
    window: int = 20,
    method: str = "spearman",
) -> pd.Series:
    """Compute rolling IC over a window of dates.

    Assumes factor_df has a 'datetime' or date index and columns for
    the factor and forward return.

    Returns:
        pd.Series of IC values indexed by date.
    """
    results = {}
    dates = factor_df.index if not isinstance(factor_df.index, pd.RangeIndex) else factor_df.get("datetime", factor_df.index)

    for i in range(window, len(factor_df)):
        window_df = factor_df.iloc[i - window: i]
        ic = information_coefficient(
            window_df[factor_col],
            window_df[return_col],
            method=method,
        )
        results[factor_df.index[i]] = ic

    return pd.Series(results, name=f"IC_{factor_col}")


def ic_summary(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    forward_return_col: str = "fwd_return_1d",
    method: str = "spearman",
) -> pd.DataFrame:
    """Compute IC statistics for multiple factors.

    Returns a DataFrame with columns:
        IC_mean, IC_std, ICIR (IC / std), positive_pct
    """
    records = []
    dates = factor_df["datetime"].unique() if "datetime" in factor_df.columns else []

    for col in factor_cols:
        if col not in factor_df.columns:
            continue

        ics = []
        for date in dates:
            day = factor_df[factor_df["datetime"] == date]
            ic = information_coefficient(day[col], day[forward_return_col], method)
            if not np.isnan(ic):
                ics.append(ic)

        if not ics:
            continue

        ic_series = pd.Series(ics)
        records.append({
            "factor": col,
            "IC_mean": ic_series.mean(),
            "IC_std": ic_series.std(),
            "ICIR": ic_series.mean() / ic_series.std() if ic_series.std() > 0 else 0,
            "positive_pct": (ic_series > 0).mean(),
            "abs_IC_mean": ic_series.abs().mean(),
        })

    return pd.DataFrame(records).set_index("factor") if records else pd.DataFrame()


def factor_correlation_matrix(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    method: str = "spearman",
) -> pd.DataFrame:
    """Compute the cross-correlation matrix between factors.

    High correlation (>0.7) suggests factors are redundant.
    """
    subset = factor_df[factor_cols].dropna()
    if method == "spearman":
        return subset.rank().corr()
    return subset.corr()


def factor_decay(
    factor_df: pd.DataFrame,
    factor_col: str,
    horizons: list[int] | None = None,
    return_col_prefix: str = "fwd_return",
    method: str = "spearman",
) -> pd.DataFrame:
    """Analyse how IC decays over different forward return horizons.

    Returns DataFrame with columns [horizon, IC_mean, ICIR].
    """
    horizons = horizons or [1, 3, 5, 10, 20]
    records = []

    for h in horizons:
        col = f"{return_col_prefix}_{h}d"
        if col not in factor_df.columns:
            continue
        ic = information_coefficient(factor_df[factor_col], factor_df[col], method)
        records.append({"horizon": h, "IC": ic})

    return pd.DataFrame(records)


def add_forward_returns(
    df: pd.DataFrame,
    horizons: list[int] | None = None,
    price_col: str = "close",
) -> pd.DataFrame:
    """Add forward return columns to a bar DataFrame.

    Args:
        df: Bar DataFrame sorted ascending by datetime.
        horizons: List of forward periods in bars (e.g. [1, 5, 10]).
        price_col: Column to use for return calculation.

    Returns:
        df with added columns fwd_return_1d, fwd_return_5d, etc.
    """
    horizons = horizons or [1, 5, 10, 20]
    result = df.copy()
    for h in horizons:
        result[f"fwd_return_{h}d"] = result[price_col].pct_change(h).shift(-h)
    return result
