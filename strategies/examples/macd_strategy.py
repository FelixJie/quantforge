"""MACD Crossover Strategy — momentum trend-following.

Logic:
  - BUY  when MACD line crosses above Signal line (bullish crossover)
  - SELL when MACD line crosses below Signal line (bearish crossover)
  - Additional filter: only buy when MACD histogram is positive (strong momentum)

MACD parameters: EMA(fast=12), EMA(slow=26), Signal=EMA(9) of MACD line.
"""

from typing import ClassVar

import pandas as pd

from quantforge.core.constants import Exchange, OrderType
from quantforge.core.datatypes import BarData
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


class MACDStrategy(Strategy):
    """MACD crossover trend-following for A-shares.

    Parameters:
        symbol       : Stock code
        fast_period  : Fast EMA period (default 12)
        slow_period  : Slow EMA period (default 26)
        signal_period: Signal EMA period (default 9)
        capital_pct  : Fraction of capital to use per trade (default 0.9)
    """

    name: ClassVar[str] = "macd"
    description: ClassVar[str] = (
        "MACD趋势跟随 — MACD线上穿信号线时做多，下穿时平仓。"
        "经典动量指标，捕捉中期趋势，默认参数(12,26,9)。"
    )
    author: ClassVar[str] = "QuantForge"
    category: ClassVar[str] = "trend_following"
    tags: ClassVar[list[str]] = ["趋势跟随", "MACD", "动量", "经典"]
    parameters: ClassVar[list[str]] = ["symbol", "fast_period", "slow_period", "signal_period"]

    symbol: str = "000001"
    exchange: Exchange = Exchange.SZSE
    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9
    capital_pct: float = 0.9

    def __init__(self, ctx: StrategyContext, params: dict | None = None):
        super().__init__(ctx, params)
        if isinstance(self.exchange, str):
            self.exchange = Exchange(self.exchange)

    async def on_init(self) -> None:
        self.ctx.log(
            f"MACD Strategy | symbol={self.symbol} "
            f"fast={self.fast_period} slow={self.slow_period} signal={self.signal_period}"
        )

    async def on_bar(self, bar: BarData) -> None:
        if bar.symbol != self.symbol:
            return

        df = self.ctx.get_bars_df(self.symbol)
        min_bars = self.slow_period + self.signal_period + 2
        if len(df) < min_bars:
            return

        macd, signal = self._compute_macd(df["close"])
        if macd is None:
            return

        macd_now, macd_prev = macd[-1], macd[-2]
        sig_now, sig_prev = signal[-1], signal[-2]

        price = bar.close
        pos = self.ctx.get_position(self.symbol)
        has_position = pos is not None and pos.volume > 0

        # Bullish crossover: MACD crosses above signal
        if macd_prev <= sig_prev and macd_now > sig_now and not has_position:
            account = self.ctx.get_account()
            invest = account.available * self.capital_pct
            volume = int(invest / price / 100) * 100
            if volume > 0:
                await self.ctx.buy(
                    self.symbol, volume=float(volume), price=price,
                    exchange=self.exchange, order_type=OrderType.LIMIT,
                )
                self.ctx.log(
                    f"BUY crossover | MACD={macd_now:.4f} > Signal={sig_now:.4f} price={price:.2f}"
                )

        # Bearish crossover: MACD crosses below signal
        elif macd_prev >= sig_prev and macd_now < sig_now and has_position:
            available = pos.volume - pos.frozen
            if available > 0:
                await self.ctx.sell(
                    self.symbol, volume=available, price=price,
                    exchange=self.exchange, order_type=OrderType.LIMIT,
                )
                self.ctx.log(
                    f"SELL crossover | MACD={macd_now:.4f} < Signal={sig_now:.4f} price={price:.2f}"
                )

    def _compute_macd(self, close: pd.Series):
        """Return (macd_series, signal_series) as arrays."""
        if len(close) < self.slow_period + self.signal_period:
            return None, None
        ema_fast = close.ewm(span=self.fast_period, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow_period, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal = macd.ewm(span=self.signal_period, adjust=False).mean()
        return macd.values, signal.values

    async def on_stop(self) -> None:
        self.ctx.log("Strategy stopped.")
