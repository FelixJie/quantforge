"""Abstract Factor interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Factor(ABC):
    """Base class for all alpha factors.

    A factor takes a DataFrame of OHLCV bars and returns a Series of values,
    one per bar (aligned to the same index).

    Usage:
        factor = MomentumFactor(window=20)
        values = factor.compute(df)
    """

    name: str = ""
    description: str = ""
    category: str = ""      # "technical", "fundamental", "alternative"
    window: int = 0         # Required lookback period (minimum bars needed)

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """Compute factor values.

        Args:
            df: DataFrame with columns [datetime, open, high, low, close, volume, turnover]
                Sorted ascending by datetime.

        Returns:
            pd.Series aligned to df.index with float values.
            NaN for rows where insufficient lookback data is available.
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, window={self.window})"
