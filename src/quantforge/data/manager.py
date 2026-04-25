"""DataManager — central coordinator for data feeds and storage."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from loguru import logger

from quantforge.core.constants import Exchange, Interval
from quantforge.core.datatypes import BarData
from quantforge.core.errors import DataNotFoundError
from quantforge.data.feed.efinance_feed import EFinanceFeed, detect_exchange
from quantforge.data.feed.akshare_feed import AKShareFeed
from quantforge.data.feed.base import DataFeed
from quantforge.data.storage.parquet_store import ParquetStore


class DataManager:
    """Coordinates data feeds, storage, and caching.

    Exchange is now optional everywhere — it will be auto-detected from
    the stock code prefix when not provided.
    """

    def __init__(self, data_dir: str = "data"):
        self._feeds: dict[str, DataFeed] = {}
        self._store = ParquetStore(data_dir)
        self._default_feed: str = "efinance"

        # Register feeds (efinance preferred, akshare as fallback)
        self.register_feed(EFinanceFeed())
        self.register_feed(AKShareFeed())

    def register_feed(self, feed: DataFeed) -> None:
        self._feeds[feed.name] = feed

    # ── Exchange resolution ───────────────────────────────────────────

    def resolve_exchange(self, symbol: str, exchange: Exchange | None) -> Exchange:
        """Return exchange, auto-detecting from symbol prefix if not given."""
        if exchange is not None:
            return exchange
        return detect_exchange(symbol)

    def find_stored_exchange(self, symbol: str, interval: Interval) -> Exchange | None:
        """Find which exchange has stored data for this symbol."""
        for exc in [Exchange.SSE, Exchange.SZSE, Exchange.BSE]:
            if self._store.exists(symbol, exc, interval):
                return exc
        return None

    # ── Download ──────────────────────────────────────────────────────

    async def download(
        self,
        symbol: str,
        interval: Interval = Interval.DAILY,
        start: datetime | None = None,
        end: datetime | None = None,
        exchange: Exchange | None = None,
        feed_name: str | None = None,
    ) -> pd.DataFrame:
        """Download data from feed and save to storage.

        Tries efinance first; automatically falls back to akshare on failure.
        """
        start = start or datetime(2020, 1, 1)
        end = end or datetime.now()
        exchange = self.resolve_exchange(symbol, exchange)

        # Build ordered list of feeds to try
        if feed_name:
            feed_order = [feed_name]
        else:
            feed_order = ["efinance", "akshare"]

        last_error: Exception | None = None
        for fname in feed_order:
            feed = self._feeds.get(fname)
            if feed is None:
                continue
            try:
                logger.info(f"Downloading {symbol}.{exchange.value} [{start:%Y%m%d}-{end:%Y%m%d}] via {feed.name}")
                df = await feed.fetch_bars(symbol, interval, start, end, exchange)
                if not df.empty:
                    df["exchange"] = exchange.value
                    self._store.save(df, symbol, exchange, interval)
                    logger.info(f"Saved {len(df)} bars for {symbol}.{exchange.value} via {feed.name}")
                    return df
                logger.warning(f"{feed.name} returned empty for {symbol}, trying next feed...")
            except Exception as e:
                last_error = e
                logger.warning(f"{feed.name} failed for {symbol}: {e}; trying next feed...")

        # All feeds failed
        if last_error:
            raise last_error
        return pd.DataFrame()

    # ── Load ──────────────────────────────────────────────────────────

    def load_bars(
        self,
        symbol: str,
        interval: Interval = Interval.DAILY,
        start: datetime | None = None,
        end: datetime | None = None,
        exchange: Exchange | None = None,
    ) -> pd.DataFrame:
        """Load bars from local storage.

        If exchange is None, auto-detects from symbol prefix.
        Falls back to scanning all exchanges if the detected one has no data.
        """
        start_ts = pd.Timestamp(start) if start else None
        end_ts = pd.Timestamp(end) if end else None

        # Try auto-detected exchange first
        exc = self.resolve_exchange(symbol, exchange)
        df = self._store.load(symbol, exc, interval, start_ts, end_ts)
        if not df.empty:
            return df

        # Scan other exchanges (handles mismatches in old stored data)
        stored_exc = self.find_stored_exchange(symbol, interval)
        if stored_exc and stored_exc != exc:
            logger.debug(f"{symbol}: data found under {stored_exc.value}, not {exc.value}")
            return self._store.load(symbol, stored_exc, interval, start_ts, end_ts)

        return pd.DataFrame()

    def bars_to_bar_data_list(
        self,
        df: pd.DataFrame,
        symbol: str,
        exchange: Exchange,
        interval: Interval,
    ) -> list[BarData]:
        bars = []
        for _, row in df.iterrows():
            bar = BarData(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                datetime=row["datetime"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                turnover=float(row.get("turnover", 0)),
            )
            bars.append(bar)
        return bars

    def has_data(
        self,
        symbol: str,
        exchange: Exchange | None = None,
        interval: Interval = Interval.DAILY,
    ) -> bool:
        exc = self.resolve_exchange(symbol, exchange)
        if self._store.exists(symbol, exc, interval):
            return True
        # Also check other exchanges
        return self.find_stored_exchange(symbol, interval) is not None

    def list_all_symbols(self, interval: Interval = Interval.DAILY) -> list[dict]:
        """List all stored symbols across all exchanges."""
        result = []
        for exc in [Exchange.SSE, Exchange.SZSE, Exchange.BSE]:
            for sym in self._store.list_symbols(exc, interval):
                result.append({"symbol": sym, "exchange": exc.value})
        return result
