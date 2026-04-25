"""LightGBM model for tabular alpha prediction."""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from quantforge.model.base import BaseModel


class LightGBMModel(BaseModel):
    """LightGBM gradient boosting model.

    Predicts forward returns from factor features.
    Works as a ranking model (rank IC optimisation) or
    a regression model (MSE loss).
    """

    name = "lightgbm"
    description = "LightGBM gradient boosting for alpha prediction"

    def __init__(
        self,
        objective: str = "regression",
        num_leaves: int = 31,
        n_estimators: int = 200,
        learning_rate: float = 0.05,
        min_child_samples: int = 20,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        random_state: int = 42,
        verbose: int = -1,
    ):
        self._params = dict(
            objective=objective,
            num_leaves=num_leaves,
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            min_child_samples=min_child_samples,
            subsample=subsample,
            colsample_bytree=colsample_bytree,
            random_state=random_state,
            verbose=verbose,
        )
        self._model = None
        self._feature_names: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> None:
        """Train on features X and target y."""
        try:
            import lightgbm as lgb
        except ImportError:
            raise ImportError(
                "LightGBM not installed. Run: pip install lightgbm"
            )

        self._feature_names = list(X.columns)

        self._model = lgb.LGBMRegressor(**self._params)
        self._model.fit(
            X, y,
            callbacks=[lgb.log_evaluation(period=0)],
            **kwargs,
        )
        logger.info(
            f"LightGBM trained | samples={len(X)} | features={len(self._feature_names)}"
        )

    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Return prediction scores aligned to X's index."""
        if self._model is None:
            raise RuntimeError("Model not fitted. Call fit() first.")
        preds = self._model.predict(X[self._feature_names])
        return pd.Series(preds, index=X.index, name="prediction")

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"model": self._model, "features": self._feature_names}, f)
        logger.info(f"Model saved to {path}")

    def load(self, path: Path) -> None:
        with open(path, "rb") as f:
            data = pickle.load(f)
        self._model = data["model"]
        self._feature_names = data["features"]
        logger.info(f"Model loaded from {path}")

    def get_feature_importance(self) -> pd.Series | None:
        if self._model is None:
            return None
        imp = self._model.feature_importances_
        return pd.Series(imp, index=self._feature_names, name="importance").sort_values(ascending=False)

    def is_fitted(self) -> bool:
        return self._model is not None
