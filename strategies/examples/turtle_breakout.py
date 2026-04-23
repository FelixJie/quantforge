"""Turtle Breakout Strategy — classic trend-following breakout system.

Based on the original Turtle Trading rules popularized by Richard Dennis:
  - BUY  when price breaks above the highest high of the last N bars (entry channel)
  - SELL when price falls below the lowest low of the last M bars (exit channel)
  - Position sizing based on ATR (volatility-adjusted)
  - Hard stop at 2×ATR below entry

Default parameters: entry_period=20, exit_period=10, atr_period=14, atr_multiplier=2.0
"""

from typing import ClassVar

import numpy as np

from quantforge.core.constants import Exchange, OrderType
from quantforge.core.datatypes import BarData
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


class TurtleBreakoutStrategy(Strategy):
    """A-share adaptation of the classic Turtle breakout system.

    Buys on N-day high breakout, sells on M-day low breakdown.
    ATR-based stop controls risk on each trade.
    """

    name: ClassVar[str] = "turtle_breakout"
    description: ClassVar[str] = (
        "海龟突破策略 — 经典趋势跟踪系统，N日最高价突破买入，M日最低价破位卖出，"
        "ATR动态调整止损位，适合单边行情，是量化趋势策略的经典原型。"
    )
    author: ClassVar[str] = "QuantForge"
    category: ClassVar[str] = "trend_following"
    tags: ClassVar[list[str]] = ["海龟", "突破", "趋势跟随", "ATR", "止损", "经典"]
    parameters: ClassVar[list[str]] = ["symbol", "entry_period", "exit_period", "atr_multiplier"]

    symbol: str = "000001"
    exchange: Exchange = Exchange.SZSE
    entry_period: int = 20      # N-day breakout channel
    exit_period: int = 10       # M-day exit channel
    atr_period: int = 14
    atr_multiplier: float = 2.0  # stop = entry - multiplier * ATR
    risk_pct: float = 0.01       # risk 1% of capital per unit

    def __init__(self, ctx: StrategyContext, params: dict | None = None):
        super().__init__(ctx, params)
        if isinstance(self.exchange, str):
            self.exchange = Exchange(self.exchange)
        self._entry_price: float | None = None
        self._stop_price: float | None = None

    async def on_init(self) -> None:
        self.ctx.log(
            f"Turtle Breakout | entry={self.entry_period}d exit={self.exit_period}d "
            f"atr_mult={self.atr_multiplier} symbol={self.symbol}"
        )

    async def on_bar(self, bar: BarData) -> None:
        if bar.symbol != self.symbol:
            return
        df = self.ctx.get_bars_df(self.symbol)
        min_bars = max(self.entry_period, self.exit_period, self.atr_period) + 2
        if len(df) < min_bars:
            return

        price = bar.close
        pos = self.ctx.get_position(self.symbol)
        has_position = pos is not None and pos.volume > 0

        atr = self._calc_atr(df)
        high_n = float(df["high"].iloc[-self.entry_period - 1:-1].max())
        low_m = float(df["low"].iloc[-self.exit_period - 1:-1].min())

        if has_position:
            # Trail stop on lowest-low exit channel
            dynamic_stop = max(self._stop_price or 0, low_m)
            self._stop_price = dynamic_stop
            if price <= dynamic_stop:
                available = pos.volume - pos.frozen
                if available > 0:
                    await self.ctx.sell(self.symbol, volume=available, price=price,
                                        exchange=self.exchange, order_type=OrderType.LIMIT)
                    self.ctx.log(f"EXIT [通道止损] price={price:.2f} stop={dynamic_stop:.2f}")
                    self._entry_price = None
                    self._stop_price = None
        else:
            # Entry: break above N-day high
            if price > high_n and atr > 0:
                account = self.ctx.get_account()
                # Unit = risk_pct * capital / (atr_multiplier * ATR)
                unit_size = int(account.available * self.risk_pct / (self.atr_multiplier * atr) / 100) * 100
                if unit_size <= 0:
                    unit_size = int(account.available * 0.9 / price / 100) * 100
                if unit_size > 0:
                    await self.ctx.buy(self.symbol, volume=float(unit_size), price=price,
                                       exchange=self.exchange, order_type=OrderType.LIMIT)
                    self._entry_price = price
                    self._stop_price = price - self.atr_multiplier * atr
                    self.ctx.log(
                        f"BUY [突破{self.entry_period}日高] price={price:.2f} "
                        f"stop={self._stop_price:.2f} vol={unit_size}"
                    )

    def _calc_atr(self, df) -> float:
        if len(df) < self.atr_period + 1:
            return 0.0
        high = df["high"]
        low = df["low"]
        close_prev = df["close"].shift(1)
        tr = (high - low).combine(
            (high - close_prev).abs(), max
        ).combine((low - close_prev).abs(), max)
        return float(tr.rolling(self.atr_period).mean().iloc[-1])

    async def on_stop(self) -> None:
        self.ctx.log("Turtle strategy stopped.")
