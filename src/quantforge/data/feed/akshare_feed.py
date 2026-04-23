"""AKShare data feed — free A-share data, no token required."""

import asyncio
from datetime import datetime

import pandas as pd
from loguru import logger

from quantforge.core.constants import Exchange, Interval
from quantforge.core.errors import DataError
from quantforge.data.feed.base import DataFeed

# Mapping from our Interval enum to AKShare period parameter
_INTERVAL_MAP = {
    Interval.DAILY: "daily",
    Interval.WEEKLY: "weekly",
}


class AKShareFeed(DataFeed):
    """A-share data via AKShare (akshare.xyz)."""

    name = "akshare"

    async def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        start: datetime,
        end: datetime,
        exchange: Exchange = Exchange.SSE,
    ) -> pd.DataFrame:
        """Fetch historical bars from AKShare.

        Uses stock_zh_a_hist for daily/weekly data.
        """
        if interval not in _INTERVAL_MAP:
            raise DataError(f"AKShare does not support interval: {interval}")

        period = _INTERVAL_MAP[interval]
        start_str = start.strftime("%Y%m%d")
        end_str = end.strftime("%Y%m%d")

        try:
            # Run sync AKShare call in thread pool
            df = await asyncio.to_thread(
                self._fetch_sync, symbol, period, start_str, end_str
            )
        except Exception as e:
            raise DataError(f"AKShare fetch failed for {symbol}: {e}") from e

        if df.empty:
            logger.warning(f"No data returned for {symbol} [{start_str} - {end_str}]")
            return df

        return self._normalize(df, symbol, exchange, interval)

    def _fetch_sync(
        self, symbol: str, period: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Synchronous AKShare call (run in thread).

        Tries East Money backend first, falls back to Sina Finance if that fails.
        """
        import akshare as ak

        # Primary: East Money via stock_zh_a_hist
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            if not df.empty:
                return df
        except Exception as e:
            logger.warning(f"stock_zh_a_hist failed for {symbol}: {e}; trying Sina Finance...")

        # Fallback: Sina Finance via stock_zh_a_daily
        # Symbol prefix: 6xxxxx → sh, 0/3xxxxx → sz, 8/4xxxxx → bj
        if symbol.startswith("6"):
            sina_sym = f"sh{symbol}"
        elif symbol.startswith(("8", "4")):
            sina_sym = f"bj{symbol}"
        else:
            sina_sym = f"sz{symbol}"

        df = ak.stock_zh_a_daily(
            symbol=sina_sym,
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
        # Sina columns: date, open, high, low, close, volume, amount, outstanding_share, turnover(rate)
        # Drop columns that would cause name collisions before renaming
        df = df.drop(columns=[c for c in ["outstanding_share", "turnover"] if c in df.columns])
        df = df.rename(columns={"date": "日期", "open": "开盘", "close": "收盘",
                                 "high": "最高", "low": "最低", "volume": "成交量",
                                 "amount": "成交额"})
        return df

    def _normalize(
        self, df: pd.DataFrame, symbol: str, exchange: Exchange, interval: Interval
    ) -> pd.DataFrame:
        """Normalize AKShare output to standard QuantForge format.

        stock_zh_a_hist positional columns:
          0=日期, 1=开盘, 2=收盘, 3=最高, 4=最低, 5=成交量, 6=成交额, 7=振幅,
          8=涨跌幅, 9=涨跌额, 10=换手率
        Uses positional mapping to avoid GBK/UTF-8 column name encoding issues.
        """
        cols = df.columns.tolist()
        # Try named columns first (works when encoding is fine)
        name_map = {
            "日期": "datetime", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume", "成交额": "turnover",
        }
        if any(c in cols for c in name_map):
            df = df.rename(columns=name_map)
        else:
            # Positional fallback
            pos_map = {0: "datetime", 1: "open", 2: "close", 3: "high",
                       4: "low", 5: "volume", 6: "turnover"}
            df = df.rename(columns={cols[i]: name for i, name in pos_map.items() if i < len(cols)})

        # Keep only standard columns
        keep_cols = ["datetime", "open", "high", "low", "close", "volume", "turnover"]
        available = [c for c in keep_cols if c in df.columns]
        df = df[available].copy()

        # Parse datetime
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)

        # Add metadata columns
        df["symbol"] = symbol
        df["exchange"] = exchange.value
        df["interval"] = interval.value

        return df

    async def get_symbols(self, exchange: Exchange) -> list[str]:
        """Get all A-share stock symbols."""
        import akshare as ak

        df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
        symbols = df["代码"].tolist()

        # Filter by exchange prefix
        if exchange == Exchange.SSE:
            symbols = [s for s in symbols if s.startswith("6")]
        elif exchange == Exchange.SZSE:
            symbols = [s for s in symbols if s.startswith(("0", "3"))]

        return symbols
