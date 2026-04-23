"""Keltner Channel Strategy — EMA-centered volatility band with ATR width.

The Keltner Channel is built on:
  - Middle line: EMA(close, period)
  - Upper band:  EMA + multiplier * ATR
  - Lower band:  EMA - multiplier * ATR

Signal logic:
  - BUY  when price closes below lower band (oversold / mean-reversion)
  - EXIT when price crosses back above the middle EMA line
  - Optional trend filter: only trade in direction of longer-term trend (200 EMA)

Parameters:
    ema_period    : EMA period for middle line (default 20)
    atr_period    : ATR period for band width (default 14)
    multiplier    : Band width = multiplier × ATR (default 2.0)
    trend_filter  : If True, only buy when price is above 200-day EMA
"""

from typing import ClassVar

import numpy as np

from quantforge.core.constants import Exchange, OrderType
from quantforge.core.datatypes import BarData
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


class KeltnerChannelStrategy(Strategy):
    """Keltner channel mean-reversion with optional long-term trend filter."""

    name: ClassVar[str] = "keltner_channel"
    description: ClassVar[str] = (
        "肯特纳通道策略 — 以EMA为中轨，ATR为宽度构建动态波动通道。"
        "价格触及下轨超卖时买入，回归中轨时止盈出场。支持长期趋势过滤，"
        "仅在牛市方向上做多，避免逆势交易。"
    )
    author: ClassVar[str] = "QuantForge"
    category: ClassVar[str] = "mean_reversion"
    tags: ClassVar[list[str]] = ["肯特纳", "通道", "ATR", "EMA", "均值回归", "趋势过滤"]
    parameters: ClassVar[list[str]] = ["symbol", "ema_period", "atr_period", "multiplier", "trend_filter"]

    symbol: str = "000001"
    exchange: Exchange = Exchange.SZSE
    ema_period: int = 20
    atr_period: int = 14
    multiplier: float = 2.0
    trend_filter: bool = True    # Only buy when above 200-day EMA
    trend_period: int = 200
    stop_loss: float = 0.06

    def __init__(self, ctx: StrategyContext, params: dict | None = None):
        super().__init__(ctx, params)
        if isinstance(self.exchange, str):
            self.exchange = Exchange(self.exchange)
        self._entry_price: float | None = None

    async def on_init(self) -> None:
        self.ctx.log(
            f"Keltner Channel | ema={self.ema_period} atr={self.atr_period} "
            f"mult={self.multiplier} trend_filter={self.trend_filter}"
        )

    async def on_bar(self, bar: BarData) -> None:
        if bar.symbol != self.symbol:
            return
        df = self.ctx.get_bars_df(self.symbol)
        min_bars = max(self.ema_period, self.atr_period, self.trend_period if self.trend_filter else 0) + 2
        if len(df) < min_bars:
            return

        price = bar.close
        close = df["close"]
        high = df["high"]
        low = df["low"]

        ema = float(close.ewm(span=self.ema_period, adjust=False).mean().iloc[-1])
        atr = self._calc_atr(high, low, close)
        upper = ema + self.multiplier * atr
        lower = ema - self.multiplier * atr

        pos = self.ctx.get_position(self.symbol)
        has_position = pos is not None and pos.volume > 0

        # Stop loss
        if has_position and self._entry_price:
            loss = (price - self._entry_price) / self._entry_price
            if loss < -self.stop_loss:
                available = pos.volume - pos.frozen
                if available > 0:
                    await self.ctx.sell(self.symbol, volume=available, price=price,
                                        exchange=self.exchange, order_type=OrderType.LIMIT)
                    self.ctx.log(f"STOP LOSS | loss={loss:.2%}")
                    self._entry_price = None
                return

        # Trend filter
        in_uptrend = True
        if self.trend_filter and len(close) >= self.trend_period:
            trend_ema = float(close.ewm(span=self.trend_period, adjust=False).mean().iloc[-1])
            in_uptrend = price > trend_ema

        if not has_position and price <= lower and in_uptrend:
            account = self.ctx.get_account()
            volume = int(account.available * 0.9 / price / 100) * 100
            if volume > 0:
                await self.ctx.buy(self.symbol, volume=float(volume), price=price,
                                   exchange=self.exchange, order_type=OrderType.LIMIT)
                self._entry_price = price
                self.ctx.log(f"BUY [触及下轨] price={price:.2f} lower={lower:.2f} ema={ema:.2f}")

        elif has_position and price >= ema:
            available = pos.volume - pos.frozen
            if available > 0:
                await self.ctx.sell(self.symbol, volume=available, price=price,
                                    exchange=self.exchange, order_type=OrderType.LIMIT)
                self._entry_price = None
                self.ctx.log(f"SELL [回归中轨] price={price:.2f} ema={ema:.2f}")

    def _calc_atr(self, high, low, close) -> float:
        close_prev = close.shift(1)
        tr = (high - low).combine(
            (high - close_prev).abs(), max
        ).combine((low - close_prev).abs(), max)
        return float(tr.rolling(self.atr_period).mean().iloc[-1])

    async def on_stop(self) -> None:
        self.ctx.log("Keltner strategy stopped.")
