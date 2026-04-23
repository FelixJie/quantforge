"""Adaptive Momentum Strategy — regime-switching between trend and mean-reversion.

Detects market regime from realized volatility:
  - LOW  volatility → TRENDING regime → MA crossover signal
  - HIGH volatility → RANGING  regime → RSI reversal signal

This "adaptive" approach avoids using trend rules in choppy markets and
reversal rules in strong trends, improving signal quality.
"""

from typing import ClassVar

import numpy as np

from quantforge.core.constants import Exchange, OrderType
from quantforge.core.datatypes import BarData
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


class AdaptiveMomentumStrategy(Strategy):
    """Regime-adaptive strategy: trend-following in low-vol, mean-reversion in high-vol.

    Parameters:
        symbol          : Stock code
        vol_window      : Rolling window for volatility estimation (default 20)
        vol_threshold   : Annualized vol threshold to switch regime (default 0.30 = 30%)
        fast_period     : Fast MA for trending regime (default 10)
        slow_period     : Slow MA for trending regime (default 30)
        rsi_period      : RSI period for ranging regime (default 14)
        rsi_oversold    : RSI buy level in ranging regime (default 35)
        rsi_overbought  : RSI sell level in ranging regime (default 65)
    """

    name: ClassVar[str] = "adaptive_momentum"
    description: ClassVar[str] = (
        "自适应动量策略 — 自动识别市场状态：低波动率趋势行情用均线跟随，"
        "高波动率震荡行情切换为RSI均值回归，智能适应不同市场环境。"
    )
    author: ClassVar[str] = "QuantForge"
    category: ClassVar[str] = "adaptive"
    tags: ClassVar[list[str]] = ["自适应", "状态切换", "AI", "多信号", "机制转换"]
    parameters: ClassVar[list[str]] = ["symbol", "vol_window", "vol_threshold", "fast_period", "slow_period"]

    symbol: str = "000001"
    exchange: Exchange = Exchange.SZSE
    vol_window: int = 20
    vol_threshold: float = 0.30    # 30% annualized vol = regime switch point
    fast_period: int = 10
    slow_period: int = 30
    rsi_period: int = 14
    rsi_oversold: float = 35.0
    rsi_overbought: float = 65.0
    stop_loss: float = 0.06

    def __init__(self, ctx: StrategyContext, params: dict | None = None):
        super().__init__(ctx, params)
        if isinstance(self.exchange, str):
            self.exchange = Exchange(self.exchange)
        self._entry_price: float | None = None

    async def on_init(self) -> None:
        self.ctx.log(f"Adaptive Momentum | symbol={self.symbol} vol_threshold={self.vol_threshold:.0%}")

    async def on_bar(self, bar: BarData) -> None:
        if bar.symbol != self.symbol:
            return

        df = self.ctx.get_bars_df(self.symbol)
        min_bars = max(self.slow_period, self.rsi_period, self.vol_window) + 3
        if len(df) < min_bars:
            return

        close = df["close"]
        price = bar.close

        # Detect regime via realized volatility
        returns = close.pct_change().dropna()
        realized_vol = float(returns.tail(self.vol_window).std() * np.sqrt(252))
        is_trending = realized_vol < self.vol_threshold

        pos = self.ctx.get_position(self.symbol)
        has_position = pos is not None and pos.volume > 0

        # Stop-loss
        if has_position and self._entry_price:
            loss = (price - self._entry_price) / self._entry_price
            if loss < -self.stop_loss:
                available = pos.volume - pos.frozen
                if available > 0:
                    await self.ctx.sell(self.symbol, volume=available, price=price,
                                        exchange=self.exchange, order_type=OrderType.LIMIT)
                    self.ctx.log(f"STOP LOSS | regime={'趋势' if is_trending else '震荡'} loss={loss:.2%}")
                    self._entry_price = None
                return

        if is_trending:
            await self._trend_signal(close, price, pos, has_position)
        else:
            await self._reversion_signal(close, price, pos, has_position)

    async def _trend_signal(self, close, price, pos, has_position):
        fast = close.rolling(self.fast_period).mean()
        slow = close.rolling(self.slow_period).mean()
        fast_now, fast_prev = float(fast.iloc[-1]), float(fast.iloc[-2])
        slow_now, slow_prev = float(slow.iloc[-1]), float(slow.iloc[-2])

        if fast_prev <= slow_prev and fast_now > slow_now and not has_position:
            await self._buy(price, "趋势金叉")
        elif fast_prev >= slow_prev and fast_now < slow_now and has_position:
            await self._sell(pos, price, "趋势死叉")

    async def _reversion_signal(self, close, price, pos, has_position):
        rsi = self._rsi(close, self.rsi_period)
        if rsi is None:
            return
        if rsi < self.rsi_oversold and not has_position:
            await self._buy(price, f"超跌RSI={rsi:.1f}")
        elif rsi > self.rsi_overbought and has_position:
            await self._sell(pos, price, f"超涨RSI={rsi:.1f}")

    async def _buy(self, price, reason):
        account = self.ctx.get_account()
        volume = int(account.available * 0.9 / price / 100) * 100
        if volume > 0:
            await self.ctx.buy(self.symbol, volume=float(volume), price=price,
                               exchange=self.exchange, order_type=OrderType.LIMIT)
            self._entry_price = price
            self.ctx.log(f"BUY [{reason}] | price={price:.2f}")

    async def _sell(self, pos, price, reason):
        available = pos.volume - pos.frozen
        if available > 0:
            await self.ctx.sell(self.symbol, volume=available, price=price,
                                exchange=self.exchange, order_type=OrderType.LIMIT)
            self._entry_price = None
            self.ctx.log(f"SELL [{reason}] | price={price:.2f}")

    def _rsi(self, close, period):
        if len(close) < period + 1:
            return None
        delta = close.diff().dropna()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        if float(loss.iloc[-1]) == 0:
            return 100.0
        return float(100 - 100 / (1 + gain.iloc[-1] / loss.iloc[-1]))

    async def on_stop(self) -> None:
        self.ctx.log("Strategy stopped.")
