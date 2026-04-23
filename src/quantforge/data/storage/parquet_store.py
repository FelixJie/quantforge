"""Parquet-based columnar storage for OHLCV bar data."""

from pathlib import Path

import pandas as pd
from loguru import logger

from quantforge.core.constants import Exchange, Interval


class ParquetStore:
    """Read/write bar data as Parquet files.

    Layout: {data_dir}/parquet/{exchange}/{interval}/{symbol}.parquet
    """

    def __init__(self, data_dir: str | Path = "data"):
        self._base_dir = Path(data_dir) / "parquet"
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str, exchange: Exchange, interval: Interval) -> Path:
        """Get file path for a symbol's bar data."""
        p = self._base_dir / exchange.value / interval.value
        p.mkdir(parents=True, exist_ok=True)
        return p / f"{symbol}.parquet"

    def save(
        self,
        df: pd.DataFrame,
        symbol: str,
        exchange: Exchange,
        interval: Interval,
        append: bool = True,
    ) -> None:
        """Save bars to Parquet. If append=True, merge with existing data."""
        path = self._path(symbol, exchange, interval)

        if append and path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df], ignore_index=True)
            df = df.drop_duplicates(subset=["datetime"], keep="last")
            df = df.sort_values("datetime").reset_index(drop=True)

        df.to_parquet(path, index=False, engine="pyarrow")
        logger.debug(f"Saved {len(df)} bars to {path}")

    def load(
        self,
        symbol: str,
        exchange: Exchange,
        interval: Interval,
        start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """Load bars from Parquet, optionally filtering by date range."""
        path = self._path(symbol, exchange, interval)

        if not path.exists():
            return pd.DataFrame()

        df = pd.read_parquet(path, engine="pyarrow")

        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
            if start is not None:
                df = df[df["datetime"] >= start]
            if end is not None:
                df = df[df["datetime"] <= end]

        return df.reset_index(drop=True)

    def exists(self, symbol: str, exchange: Exchange, interval: Interval) -> bool:
        """Check if data exists for a symbol."""
        return self._path(symbol, exchange, interval).exists()

    def list_symbols(self, exchange: Exchange, interval: Interval) -> list[str]:
        """List all symbols that have stored data."""
        path = self._base_dir / exchange.value / interval.value
        if not path.exists():
            return []
        return [f.stem for f in path.glob("*.parquet")]
