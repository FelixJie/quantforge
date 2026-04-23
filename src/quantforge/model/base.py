"""Abstract ML model interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd


class BaseModel(ABC):
    """Abstract base for all ML alpha models.

    Subclasses implement fit/predict; the engine handles
    data preparation, cross-validation, and persistence.
    """

    name: str = ""
    description: str = ""

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> None:
        """Train the model on features X and target y."""
        ...

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Return predictions aligned to X's index."""
        ...

    @abstractmethod
    def save(self, path: Path) -> None:
        """Persist the trained model to disk."""
        ...

    @abstractmethod
    def load(self, path: Path) -> None:
        """Load a previously saved model from disk."""
        ...

    def get_feature_importance(self) -> pd.Series | None:
        """Return feature importance if the model supports it."""
        return None

    def is_fitted(self) -> bool:
        """Return True if the model has been trained."""
        return False
