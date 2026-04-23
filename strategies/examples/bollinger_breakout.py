"""Bollinger Band Breakout Strategy.

Logic:
  - BUY  when price breaks above the upper band (momentum breakout)
  - SELL when price falls back below the middle band (mean reversion exit)
  - Emergency stop-loss at configurable percentage below entry

Rationale: breakout above upper band signals strong trend continuation.
Exit at middle band captures the move while protecting profits.
"""

from typing import ClassVar

from quantforge.core.constants import Exchange, OrderType
from quantforge.core.datatypes import BarData
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


class BollingerBreakoutStrategy(Strategy):
    """Bollinger Band breakout for A-share trend trading.

    Parameters:
        symbol       : Stock code
        bb_period    : Bollinger Band period (default 20)
        bb_std       : Standard deviation multiplier (default 2.0)
        stop_loss    : Stop loss % from entry (default 0.07 = 7%)
    """

    name: ClassVar[str] = "bollinger_breakout"
    description: ClassVar[str] = (
        "布林带突破策略 — 价格突破上轨时买入（趋势跟随），"
        "跌回中轨时卖出获利了结，并设7%止损。适合单边趋势行情。"
    )
    author: ClassVar[str] = "QuantForge"
    category: ClassVar[str] = "trend_following"
    tags: ClassVar[list[str]] = ["趋势跟随", "布林带", "突破", "止损"]
    parameters: ClassVar[list[str]] = ["symbol", "bb_period", "bb_std", "stop_loss"]

    symbol: str = "000001"
    exchange: Exchange = Exchange.SZSE
    bb_period: int = 20
    bb_std: float = 2.0
    stop_loss: float = 0.07

    def __init__(self, ctx: StrategyContext, params: dict | None = None):
        super().__init__(ctx, params)
        if isinstance(self.exchange, str):
            self.exchange = Exchange(self.exchange)
        self._entry_price: float | None = None

    async def on_init(self) -> None:
        self.ctx.log(
            f"Bollinger Breakout | symbol={self.symbol} "
            f"period={self.bb_period} std={self.bb_std}"
        )

    async def on_bar(self, bar: BarData) -> None:
        if bar.symbol != self.symbol:
            return

        df = self.ctx.get_bars_df(self.symbol)
        if len(df) < self.bb_period + 2:
            return

        close = df["close"]
        mid = close.rolling(self.bb_period).mean()
        std = close.rolling(self.bb_period).std()
        upper = mid + self.bb_std * std

        mid_now = float(mid.iloc[-1])
        upper_now = float(upper.iloc[-1])
        upper_prev = float(upper.iloc[-2])
        price_prev = float(close.iloc[-2])
        price = bar.close

        pos = self.ctx.get_position(self.symbol)
        has_position = pos is not None and pos.volume > 0

        # Stop-loss check
        if has_position and self._entry_price:
            loss_pct = (price - self._entry_price) / self._entry_price
            if loss_pct < -self.stop_loss:
                available = pos.volume - pos.frozen
                if available > 0:
                    await self.ctx.sell(
                        self.symbol, volume=available, price=price,
                        exchange=self.exchange, order_type=OrderType.LIMIT,
                    )
                    self.ctx.log(f"STOP LOSS | price={price:.2f} loss={loss_pct:.2%}")
                    self._entry_price = None
                return

        # Buy: price crosses above upper band
        if price_prev <= upper_prev and price > upper_now and not has_position:
            account = self.ctx.get_account()
            invest = account.available * 0.9
            volume = int(invest / price / 100) * 100
            if volume > 0:
                await self.ctx.buy(
                    self.symbol, volume=float(volume), price=price,
                    exchange=self.exchange, order_type=OrderType.LIMIT,
                )
                self._entry_price = price
                self.ctx.log(
                    f"BUY breakout | price={price:.2f} upper={upper_now:.2f}"
                )

        # Sell: price falls back to middle band
        elif price < mid_now and has_position:
            available = pos.volume - pos.frozen
            if available > 0:
                await self.ctx.sell(
                    self.symbol, volume=available, price=price,
                    exchange=self.exchange, order_type=OrderType.LIMIT,
                )
                self.ctx.log(
                    f"SELL at mid | price={price:.2f} mid={mid_now:.2f}"
                )
                self._entry_price = None

    async def on_stop(self) -> None:
        self.ctx.log("Strategy stopped.")
