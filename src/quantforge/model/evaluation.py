"""Model evaluation metrics for alpha models."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def prediction_ic(predictions: pd.Series, actual_returns: pd.Series) -> float:
    """Rank IC between model predictions and actual forward returns."""
    mask = predictions.notna() & actual_returns.notna()
    if mask.sum() < 5:
        return float("nan")
    ic, _ = stats.spearmanr(predictions[mask], actual_returns[mask])
    return float(ic)


def compute_model_metrics(
    predictions: pd.Series,
    actual_returns: pd.Series,
    threshold: float = 0.0,
) -> dict:
    """Compute a comprehensive set of model performance metrics.

    Args:
        predictions: Model output scores.
        actual_returns: Realized forward returns.
        threshold: Boundary for binary classification (positive/negative).

    Returns:
        dict with IC, direction_accuracy, long_return, short_return, long_short_spread.
    """
    mask = predictions.notna() & actual_returns.notna()
    pred = predictions[mask]
    ret = actual_returns[mask]

    if len(pred) < 5:
        return {}

    # IC
    ic, _ = stats.spearmanr(pred, ret)

    # Direction accuracy
    correct = (np.sign(pred - threshold) == np.sign(ret)).mean()

    # Long/Short return (top/bottom quartile)
    q75 = pred.quantile(0.75)
    q25 = pred.quantile(0.25)
    long_ret = float(ret[pred >= q75].mean()) if (pred >= q75).any() else 0.0
    short_ret = float(ret[pred <= q25].mean()) if (pred <= q25).any() else 0.0

    return {
        "IC": float(ic),
        "direction_accuracy": float(correct),
        "long_return": long_ret,
        "short_return": short_ret,
        "long_short_spread": long_ret - short_ret,
        "n_samples": int(len(pred)),
    }


def walk_forward_evaluate(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    model_cls,
    train_periods: int = 250,
    test_periods: int = 60,
    n_splits: int = 5,
) -> pd.DataFrame:
    """Walk-forward evaluation (out-of-sample IC estimation).

    Splits data into train/test windows rolling forward in time.
    Trains model on each train window, evaluates on each test window.

    Returns:
        DataFrame with columns [split, train_end, test_start, test_end, IC, direction_accuracy]
    """
    records = []
    n = len(df)
    start = train_periods

    for i in range(n_splits):
        train_end_idx = start + i * test_periods
        test_start_idx = train_end_idx
        test_end_idx = min(test_start_idx + test_periods, n)

        if train_end_idx > n or test_end_idx > n:
            break

        train_df = df.iloc[train_end_idx - train_periods: train_end_idx]
        test_df = df.iloc[test_start_idx: test_end_idx]

        X_train = train_df[feature_cols].dropna()
        y_train = train_df.loc[X_train.index, target_col].dropna()
        common_idx = X_train.index.intersection(y_train.index)
        X_train, y_train = X_train.loc[common_idx], y_train.loc[common_idx]

        X_test = test_df[feature_cols].dropna()
        y_test = test_df.loc[X_test.index, target_col].dropna()
        common_idx_test = X_test.index.intersection(y_test.index)
        X_test, y_test = X_test.loc[common_idx_test], y_test.loc[common_idx_test]

        if len(X_train) < 50 or len(X_test) < 5:
            continue

        model = model_cls()
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        metrics = compute_model_metrics(preds, y_test)

        records.append({
            "split": i + 1,
            "train_end": train_df["datetime"].iloc[-1] if "datetime" in train_df.columns else train_end_idx,
            "test_start": test_df["datetime"].iloc[0] if "datetime" in test_df.columns else test_start_idx,
            "test_end": test_df["datetime"].iloc[-1] if "datetime" in test_df.columns else test_end_idx,
            **metrics,
        })

    return pd.DataFrame(records)
