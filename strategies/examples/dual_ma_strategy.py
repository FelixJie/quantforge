"""Dual Moving Average Crossover Strategy — classic trend-following example.

Logic:
  - BUY  when fast MA crosses above slow MA (golden cross)
  - SELL when fast MA crosses below slow MA (death cross)

Default parameters:
  fast_period = 10 (10-day MA)
  slow_period = 30 (30-day MA)
"""

from typing import ClassVar

from quantforge.core.constants import Exchange, OrderType
from quantforge.core.datatypes import BarData
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


class DualMAStrategy(Strategy):
    """Dual moving average crossover for A-shares."""

    name: ClassVar[str] = "dual_ma"
    description: ClassVar[str] = "Dual moving average crossover (trend following)"
    author: ClassVar[str] = "QuantForge"
    parameters: ClassVar[list[str]] = ["fast_period", "slow_period", "symbol", "exchange"]

    # Default parameters
    fast_period: int = 10
    slow_period: int = 30
    symbol: str = "000001"
    exchange: Exchange = Exchange.SZSE

    def __init__(self, ctx: StrategyContext, params: dict | None = None):
        super().__init__(ctx, params)
        # Ensure exchange is an Exchange enum
        if isinstance(self.exchange, str):
            self.exchange = Exchange(self.exchange)

    async def on_init(self) -> None:
        self.ctx.log(
            f"Initialized: fast={self.fast_period}, slow={self.slow_period}, "
            f"symbol={self.symbol}"
        )

    async def on_bar(self, bar: BarData) -> None:
        if bar.symbol != self.symbol:
            return

        # Need enough bars for slow MA
        df = self.ctx.get_bars_df(self.symbol)
        if len(df) < self.slow_period + 1:
            return

        close = df["close"]
        fast_ma = close.rolling(self.fast_period).mean()
        slow_ma = close.rolling(self.slow_period).mean()

        # Current and previous values
        fast_now = fast_ma.iloc[-1]
        fast_prev = fast_ma.iloc[-2]
        slow_now = slow_ma.iloc[-1]
        slow_prev = slow_ma.iloc[-2]

        current_price = bar.close
        pos = self.ctx.get_position(self.symbol)
        has_position = pos is not None and pos.volume > 0

        # Golden cross: fast crosses above slow — BUY
        if fast_prev <= slow_prev and fast_now > slow_now and not has_position:
            account = self.ctx.get_account()
            # Use 90% of available capital
            invest = account.available * 0.9
            volume = int(invest / current_price / 100) * 100  # round to lot size
            if volume > 0:
                await self.ctx.buy(
                    self.symbol,
                    volume=float(volume),
                    price=current_price,
                    exchange=self.exchange,
                    order_type=OrderType.LIMIT,
                )
                self.ctx.log(
                    f"BUY signal | price={current_price:.2f} | "
                    f"volume={volume} | fast={fast_now:.3f} > slow={slow_now:.3f}"
                )

        # Death cross: fast crosses below slow — SELL
        elif fast_prev >= slow_prev and fast_now < slow_now and has_position:
            available = pos.volume - pos.frozen
            if available > 0:
                await self.ctx.sell(
                    self.symbol,
                    volume=available,
                    price=current_price,
                    exchange=self.exchange,
                    order_type=OrderType.LIMIT,
                )
                self.ctx.log(
                    f"SELL signal | price={current_price:.2f} | "
                    f"volume={available} | fast={fast_now:.3f} < slow={slow_now:.3f}"
                )

    async def on_stop(self) -> None:
        self.ctx.log("Strategy stopped.")
