"""Abstract data feed interface."""

from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd

from quantforge.core.constants import Exchange, Interval


class DataFeed(ABC):
    """Abstract data source for market data."""

    name: str = ""

    @abstractmethod
    async def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        start: datetime,
        end: datetime,
        exchange: Exchange = Exchange.SSE,
    ) -> pd.DataFrame:
        """Fetch historical OHLCV bars.

        Returns DataFrame with columns:
            datetime, open, high, low, close, volume, turnover
        """
        ...

    @abstractmethod
    async def get_symbols(self, exchange: Exchange) -> list[str]:
        """Get all available symbols for an exchange."""
        ...
