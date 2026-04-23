"""eFinance data feed — free A-share data via EastMoney, no token needed.

Advantages over AKShare:
- No exchange parameter required (auto-detected by stock code)
- Supports SSE/SZSE/BSE in one call
- More stable API, backed by EastMoney
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pandas as pd
from loguru import logger

from quantforge.core.constants import Exchange, Interval
from quantforge.core.errors import DataError
from quantforge.data.feed.base import DataFeed

# efinance frequency codes
_FREQ_MAP = {
    Interval.DAILY: "101",    # 日K
    Interval.WEEKLY: "102",   # 周K
}


def detect_exchange(symbol: str) -> Exchange:
    """Infer exchange from A-share stock code prefix.

    Rules:
      6xxxxx → SSE (上交所)
      0xxxxx / 3xxxxx → SZSE (深交所)
      8xxxxx / 4xxxxx → BSE (北交所)
    """
    if symbol.startswith("6"):
        return Exchange.SSE
    elif symbol.startswith(("0", "3")):
        return Exchange.SZSE
    elif symbol.startswith(("8", "4")):
        return Exchange.BSE
    return Exchange.SZSE  # safe default


class EFinanceFeed(DataFeed):
    """A-share OHLCV data via the efinance library (EastMoney backend)."""

    name = "efinance"

    async def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        start: datetime,
        end: datetime,
        exchange: Exchange | None = None,
    ) -> pd.DataFrame:
        if interval not in _FREQ_MAP:
            raise DataError(f"efinance does not support interval: {interval}")

        beg = start.strftime("%Y%m%d")
        end_str = end.strftime("%Y%m%d")

        try:
            df = await asyncio.to_thread(self._fetch_sync, symbol, beg, end_str)
        except Exception as e:
            raise DataError(f"efinance fetch failed for {symbol}: {e}") from e

        if df.empty:
            logger.warning(f"No data returned for {symbol} [{beg} - {end_str}]")
            return df

        inferred_exchange = exchange or detect_exchange(symbol)
        return self._normalize(df, symbol, inferred_exchange, interval)

    def _fetch_sync(self, symbol: str, beg: str, end: str) -> pd.DataFrame:
        import time
        import efinance as ef

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                df = ef.stock.get_quote_history(symbol, beg=beg, end=end)
                return df
            except Exception as e:
                last_exc = e
                wait = 2 ** attempt   # 1s, 2s, 4s
                logger.warning(f"efinance attempt {attempt+1}/3 failed for {symbol}: {e}; retrying in {wait}s")
                time.sleep(wait)
        raise last_exc

    def _normalize(
        self,
        df: pd.DataFrame,
        symbol: str,
        exchange: Exchange,
        interval: Interval,
    ) -> pd.DataFrame:
        """Map efinance positional columns to QuantForge standard format.

        efinance column order (by position):
          0: 股票名称, 1: 股票代码, 2: 日期, 3: 开盘, 4: 收盘,
          5: 最高, 6: 最低, 7: 成交量, 8: 成交额,
          9: 振幅, 10: 涨跌幅, 11: 涨跌额, 12: 换手率
        """
        cols = df.columns.tolist()
        # Map by position — robust to encoding differences
        col_map: dict[str, str] = {}
        pos_names = ["name", "symbol", "datetime", "open", "close", "high", "low",
                     "volume", "turnover", "amplitude", "change_pct", "change_amount",
                     "turnover_rate"]
        for i, mapped_name in enumerate(pos_names):
            if i < len(cols):
                col_map[cols[i]] = mapped_name

        df = df.rename(columns=col_map)

        keep = ["datetime", "open", "high", "low", "close", "volume", "turnover"]
        available = [c for c in keep if c in df.columns]
        df = df[available].copy()

        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)

        # Ensure numeric types
        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df["symbol"] = symbol
        df["exchange"] = exchange.value
        df["interval"] = interval.value

        return df

    async def get_realtime_quote(self, symbol: str) -> dict | None:
        """Fetch a single real-time quote. Returns dict with price etc."""
        try:
            df = await asyncio.to_thread(self._fetch_realtime, symbol)
            if df.empty:
                return None
            row = df.iloc[0]
            cols = df.columns.tolist()
            # Columns positional: 0=名称, 1=代码, 2=涨跌幅, 3=最新价, 4=最高, 5=最低,
            #                      6=今开, 7=涨跌额, 8=换手率, ...
            return {
                "symbol": symbol,
                "price": float(row.iloc[3]) if len(cols) > 3 else 0.0,
                "open": float(row.iloc[6]) if len(cols) > 6 else 0.0,
                "high": float(row.iloc[4]) if len(cols) > 4 else 0.0,
                "low": float(row.iloc[5]) if len(cols) > 5 else 0.0,
                "change_pct": float(row.iloc[2]) if len(cols) > 2 else 0.0,
            }
        except Exception as e:
            logger.debug(f"Realtime quote failed for {symbol}: {e}")
            return None

    def _fetch_realtime(self, symbol: str) -> pd.DataFrame:
        import efinance as ef
        df = ef.stock.get_realtime_quotes()
        # Filter to the specific symbol (column 1 is stock code)
        code_col = df.columns[1]
        return df[df[code_col] == symbol].reset_index(drop=True)

    async def get_symbols(self, exchange: Exchange | None = None) -> list[str]:
        """List all A-share symbols, optionally filtered by exchange."""
        try:
            df = await asyncio.to_thread(self._fetch_all_codes)
            codes = df.iloc[:, 1].astype(str).tolist()  # column 1 = code
            if exchange == Exchange.SSE:
                codes = [c for c in codes if c.startswith("6")]
            elif exchange == Exchange.SZSE:
                codes = [c for c in codes if c.startswith(("0", "3"))]
            elif exchange == Exchange.BSE:
                codes = [c for c in codes if c.startswith(("8", "4"))]
            return codes
        except Exception as e:
            logger.warning(f"get_symbols failed: {e}")
            return []

    def _fetch_all_codes(self) -> pd.DataFrame:
        import efinance as ef
        return ef.stock.get_realtime_quotes()
