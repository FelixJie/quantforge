"""Multi-factor scoring engine.

Pipeline:
  1. Compute each factor series
  2. Z-score normalize (cross-sectionally)
  3. Apply user-defined weights
  4. Sum to composite score
  5. Rank stocks descending
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantforge.screener.factors.fundamental import FACTOR_REGISTRY


def zscore(s: pd.Series) -> pd.Series:
    """Robust z-score, handles NaN and zero-std gracefully."""
    valid = s.dropna()
    if len(valid) < 5:
        return pd.Series(0.0, index=s.index)
    std = valid.std()
    if std == 0:
        return pd.Series(0.0, index=s.index)
    return ((s - valid.mean()) / std).fillna(0)


def score_universe(
    df: pd.DataFrame,
    factor_weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Compute composite factor scores for all stocks in df.

    Args:
        df: Universe DataFrame from universe.fetch_universe()
        factor_weights: {factor_name: weight}.  Defaults to registry defaults.

    Returns:
        df with added columns: factor_<name>, score, rank, score_pct (percentile)
    """
    if df.empty:
        return df

    # Build effective weights (skip zero-weight factors)
    weights = {}
    for name, meta in FACTOR_REGISTRY.items():
        w = (factor_weights or {}).get(name, meta["default_weight"])
        if w and w > 0:
            weights[name] = w

    if not weights:
        df = df.copy()
        df["score"] = 0.0
        df["rank"] = range(1, len(df) + 1)
        return df

    # Normalize weights to sum to 1
    total_w = sum(weights.values())
    weights = {k: v / total_w for k, v in weights.items()}

    result = df.copy()
    composite = pd.Series(0.0, index=df.index)

    for name, w in weights.items():
        meta = FACTOR_REGISTRY[name]
        raw = meta["fn"](df)
        normalized = zscore(raw)
        result[f"factor_{name}"] = normalized
        composite += normalized * w

    result["score"] = composite
    result["rank"] = result["score"].rank(ascending=False, method="first").astype(int)

    # Percentile rank (0–100, higher = better)
    n = len(result)
    result["score_pct"] = ((n - result["rank"]) / n * 100).round(1)

    return result.sort_values("rank").reset_index(drop=True)
