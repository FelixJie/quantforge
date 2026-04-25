"""ML model training and prediction pipeline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from loguru import logger

from quantforge.factor.analysis import add_forward_returns
from quantforge.factor.engine import FactorEngine
from quantforge.factor.library.technical import get_default_factors
from quantforge.model.base import BaseModel
from quantforge.model.evaluation import compute_model_metrics
from quantforge.model.feature import build_feature_matrix


class ModelEngine:
    """Orchestrates the full ML pipeline:

    bar_data → factor computation → feature engineering
    → model training → prediction → evaluation

    Usage:
        me = ModelEngine()
        me.set_model(LightGBMModel())
        me.train(bar_df, target_horizon=1)
        predictions = me.predict(bar_df)
    """

    def __init__(self, model_dir: str = "data/models"):
        self._model: BaseModel | None = None
        self._factor_engine = FactorEngine()
        self._factor_engine.add_factors(get_default_factors())
        self._feature_cols: list[str] = []
        self._model_dir = Path(model_dir)
        self._model_dir.mkdir(parents=True, exist_ok=True)

    def set_model(self, model: BaseModel) -> None:
        """Set the ML model to use."""
        self._model = model

    def set_factors(self, factors: list) -> None:
        """Replace default factor set."""
        engine = FactorEngine()
        engine.add_factors(factors)
        self._factor_engine = engine

    def train(
        self,
        bar_df: pd.DataFrame,
        target_horizon: int = 1,
        winsorize_pct: float = 0.01,
        add_lags: bool = True,
    ) -> dict:
        """Train the model on bar data.

        Args:
            bar_df: OHLCV DataFrame sorted ascending by datetime.
            target_horizon: Forward return period (in bars) to predict.
            winsorize_pct: Winsorization percentile for factor values.
            add_lags: Whether to add lagged factor features.

        Returns:
            dict of in-sample metrics.
        """
        if self._model is None:
            raise RuntimeError("No model set. Call set_model() first.")

        logger.info(f"Training {self._model.name} | horizon={target_horizon}d | {len(bar_df)} bars")

        # Compute factors
        factor_df = self._factor_engine.compute(bar_df)
        factor_df = add_forward_returns(factor_df, horizons=[target_horizon])
        target_col = f"fwd_return_{target_horizon}d"

        self._feature_cols = self._factor_engine.get_feature_names()

        # Build feature matrix
        X, y = build_feature_matrix(
            factor_df,
            self._feature_cols,
            target_col=target_col,
            add_lags=add_lags,
            winsorize_pct=winsorize_pct,
        )

        if len(X) < 50:
            raise ValueError(f"Insufficient training samples: {len(X)}")

        self._model.fit(X, y)

        # In-sample evaluation
        preds = self._model.predict(X)
        metrics = compute_model_metrics(preds, y)
        logger.info(f"Training complete | IC={metrics.get('IC', 0):.4f} | samples={len(X)}")

        return metrics

    def predict(
        self,
        bar_df: pd.DataFrame,
        add_lags: bool = True,
        winsorize_pct: float = 0.01,
    ) -> pd.Series:
        """Generate alpha predictions for bar data.

        Returns:
            pd.Series of prediction scores (higher = more bullish).
        """
        if self._model is None or not self._model.is_fitted():
            raise RuntimeError("Model not trained. Call train() first.")

        from quantforge.model.feature import add_lag_features, winsorize, standardize

        factor_df = self._factor_engine.compute(bar_df)
        result = factor_df.copy()

        result = winsorize(result, self._feature_cols, winsorize_pct, 1 - winsorize_pct)

        if add_lags:
            result = add_lag_features(result, self._feature_cols, [1, 2, 5])

        all_cols = [
            c for c in result.columns
            if c in self._feature_cols
            or any(c.startswith(f"{fc}_lag") for fc in self._feature_cols)
        ]
        result = standardize(result, all_cols)

        X = result[all_cols].fillna(0)
        return self._model.predict(X)

    def save(self, name: str = "model") -> Path:
        """Save the trained model to disk."""
        if self._model is None:
            raise RuntimeError("No model to save.")
        path = self._model_dir / f"{name}.pkl"
        self._model.save(path)
        return path

    def load(self, name: str = "model") -> None:
        """Load a saved model from disk."""
        if self._model is None:
            raise RuntimeError("Set a model instance first with set_model().")
        path = self._model_dir / f"{name}.pkl"
        self._model.load(path)

    def get_feature_importance(self) -> pd.Series | None:
        if self._model:
            return self._model.get_feature_importance()
        return None
