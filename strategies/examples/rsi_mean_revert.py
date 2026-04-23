"""RSI Mean Reversion Strategy — buy oversold, sell overbought.

Logic:
  - BUY  when RSI drops below oversold threshold (default 30) → expect bounce
  - SELL when RSI rises above overbought threshold (default 70) → expect pullback

Best suited for range-bound / sideways markets.
Includes a simple stop-loss at 5% below entry to limit downside.
"""

from typing import ClassVar

from quantforge.core.constants import Exchange, OrderType
from quantforge.core.datatypes import BarData
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


class RSIMeanRevertStrategy(Strategy):
    """RSI oversold/overbought mean reversion for A-shares.

    Parameters:
        symbol      : Stock code, e.g. '000001'
        rsi_period  : RSI calculation period (default 14)
        oversold    : RSI below this → buy signal (default 30)
        overbought  : RSI above this → sell signal (default 70)
        stop_loss   : Stop-loss percentage from entry (default 0.05 = 5%)
    """

    name: ClassVar[str] = "rsi_mean_revert"
    description: ClassVar[str] = (
        "RSI均值回归 — 超跌买入、超涨卖出。RSI<30时建仓，RSI>70时平仓，"
        "同时设有5%止损保护。适合震荡行情。"
    )
    author: ClassVar[str] = "QuantForge"
    category: ClassVar[str] = "mean_reversion"
    tags: ClassVar[list[str]] = ["均值回归", "RSI", "振荡", "止损"]
    parameters: ClassVar[list[str]] = ["symbol", "rsi_period", "oversold", "overbought", "stop_loss"]

    symbol: str = "000001"
    exchange: Exchange = Exchange.SZSE
    rsi_period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0
    stop_loss: float = 0.05   # 5%

    def __init__(self, ctx: StrategyContext, params: dict | None = None):
        super().__init__(ctx, params)
        if isinstance(self.exchange, str):
            self.exchange = Exchange(self.exchange)
        self._entry_price: float | None = None

    async def on_init(self) -> None:
        self.ctx.log(
            f"RSI Mean Revert | symbol={self.symbol} period={self.rsi_period} "
            f"oversold={self.oversold} overbought={self.overbought}"
        )

    async def on_bar(self, bar: BarData) -> None:
        if bar.symbol != self.symbol:
            return

        df = self.ctx.get_bars_df(self.symbol)
        if len(df) < self.rsi_period + 2:
            return

        rsi = self._compute_rsi(df["close"], self.rsi_period)
        if rsi is None:
            return

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

        # Buy signal: RSI oversold
        if rsi < self.oversold and not has_position:
            account = self.ctx.get_account()
            invest = account.available * 0.9
            volume = int(invest / price / 100) * 100
            if volume > 0:
                await self.ctx.buy(
                    self.symbol, volume=float(volume), price=price,
                    exchange=self.exchange, order_type=OrderType.LIMIT,
                )
                self._entry_price = price
                self.ctx.log(f"BUY (oversold) | RSI={rsi:.1f} price={price:.2f}")

        # Sell signal: RSI overbought
        elif rsi > self.overbought and has_position:
            available = pos.volume - pos.frozen
            if available > 0:
                await self.ctx.sell(
                    self.symbol, volume=available, price=price,
                    exchange=self.exchange, order_type=OrderType.LIMIT,
                )
                self.ctx.log(f"SELL (overbought) | RSI={rsi:.1f} price={price:.2f}")
                self._entry_price = None

    def _compute_rsi(self, close, period: int) -> float | None:
        if len(close) < period + 1:
            return None
        delta = close.diff().dropna()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        if loss.iloc[-1] == 0:
            return 100.0
        rs = gain.iloc[-1] / loss.iloc[-1]
        return 100 - (100 / (1 + rs))

    async def on_stop(self) -> None:
        self.ctx.log("Strategy stopped.")
