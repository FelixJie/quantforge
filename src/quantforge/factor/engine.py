"""Factor pipeline engine — batch-computes factors across symbols and dates."""

from __future__ import annotations

import pandas as pd
from loguru import logger

from quantforge.factor.base import Factor


class FactorEngine:
    """Computes a set of factors for one or more symbols and merges the results.

    Usage:
        engine = FactorEngine()
        engine.add_factor(MomentumFactor(10))
        engine.add_factor(RSIFactor(14))

        # Single symbol
        result_df = engine.compute(bar_df)

        # Multi-symbol (returns dict)
        results = engine.compute_multi({"000001": df1, "000002": df2})
    """

    def __init__(self):
        self._factors: list[Factor] = []

    def add_factor(self, factor: Factor) -> "FactorEngine":
        """Add a factor to the pipeline. Returns self for chaining."""
        self._factors.append(factor)
        return self

    def add_factors(self, factors: list[Factor]) -> "FactorEngine":
        for f in factors:
            self.add_factor(f)
        return self

    def remove_factor(self, name: str) -> None:
        self._factors = [f for f in self._factors if f.name != name]

    @property
    def factors(self) -> list[Factor]:
        return list(self._factors)

    def compute(self, df: pd.DataFrame, drop_na: bool = False) -> pd.DataFrame:
        """Compute all factors for a single symbol's bar DataFrame.

        Args:
            df: OHLCV DataFrame sorted ascending by datetime.
            drop_na: If True, drop rows where any factor value is NaN.

        Returns:
            DataFrame with original columns plus one column per factor.
        """
        result = df.copy()

        for factor in self._factors:
            try:
                values = factor.compute(df)
                result[factor.name] = values.values
            except Exception:
                logger.exception(f"Factor computation failed: {factor.name}")
                result[factor.name] = float("nan")

        if drop_na:
            factor_cols = [f.name for f in self._factors]
            result = result.dropna(subset=factor_cols).reset_index(drop=True)

        return result

    def compute_multi(
        self,
        symbol_dfs: dict[str, pd.DataFrame],
        drop_na: bool = False,
    ) -> pd.DataFrame:
        """Compute factors for multiple symbols, returning a combined DataFrame.

        Adds a 'symbol' column and concatenates all results.
        """
        parts = []
        for symbol, df in symbol_dfs.items():
            part = self.compute(df, drop_na=drop_na)
            part["symbol"] = symbol
            parts.append(part)

        if not parts:
            return pd.DataFrame()

        combined = pd.concat(parts, ignore_index=True)
        combined = combined.sort_values(["datetime", "symbol"]).reset_index(drop=True)
        return combined

    def get_feature_names(self) -> list[str]:
        """Return list of factor column names."""
        return [f.name for f in self._factors]

    def required_lookback(self) -> int:
        """Minimum number of bars required before any factor produces valid values."""
        if not self._factors:
            return 0
        return max(f.window for f in self._factors)
