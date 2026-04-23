"""Ensemble Voting Strategy — multi-signal consensus.

Three independent signal generators vote on direction:
  1. MA Crossover  : golden cross → bullish, death cross → bearish
  2. MACD          : MACD > Signal → bullish, MACD < Signal → bearish
  3. RSI Level     : RSI < 50 + rising → bullish, RSI > 50 + falling → bearish

Action is taken only when >= min_votes signals agree.
This reduces false signals by requiring consensus before acting.
"""

from typing import ClassVar

import numpy as np
import pandas as pd

from quantforge.core.constants import Exchange, OrderType
from quantforge.core.datatypes import BarData
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


class EnsembleVotingStrategy(Strategy):
    """Multi-signal ensemble voting for A-shares.

    Parameters:
        symbol       : Stock code
        min_votes    : Minimum bullish votes to buy (default 2 of 3)
        fast_period  : Fast MA period (default 10)
        slow_period  : Slow MA period (default 30)
        rsi_period   : RSI period (default 14)
    """

    name: ClassVar[str] = "ensemble_voting"
    description: ClassVar[str] = (
        "集成投票策略 — 综合均线、MACD、RSI三个信号进行多数投票："
        "≥2个信号看涨时做多，≥2个看空时平仓。降低单信号噪声，提高信号可靠性。"
    )
    author: ClassVar[str] = "QuantForge"
    category: ClassVar[str] = "ml"
    tags: ClassVar[list[str]] = ["集成学习", "多信号投票", "AI", "降噪", "鲁棒"]
    parameters: ClassVar[list[str]] = ["symbol", "min_votes", "fast_period", "slow_period", "rsi_period"]

    symbol: str = "000001"
    exchange: Exchange = Exchange.SZSE
    min_votes: int = 2     # Need 2 of 3 signals to agree
    fast_period: int = 10
    slow_period: int = 30
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 14
    capital_pct: float = 0.9

    def __init__(self, ctx: StrategyContext, params: dict | None = None):
        super().__init__(ctx, params)
        if isinstance(self.exchange, str):
            self.exchange = Exchange(self.exchange)
        self._prev_vote: int = 0  # track previous composite vote for edge detection

    async def on_init(self) -> None:
        self.ctx.log(
            f"Ensemble Voting | symbol={self.symbol} min_votes={self.min_votes}/3"
        )

    async def on_bar(self, bar: BarData) -> None:
        if bar.symbol != self.symbol:
            return

        df = self.ctx.get_bars_df(self.symbol)
        min_bars = self.macd_slow + self.macd_signal + 5
        if len(df) < min_bars:
            return

        close = df["close"]
        price = bar.close

        # Collect votes
        votes = [
            self._ma_vote(close),
            self._macd_vote(close),
            self._rsi_vote(close),
        ]
        bullish = sum(1 for v in votes if v > 0)
        bearish = sum(1 for v in votes if v < 0)

        pos = self.ctx.get_position(self.symbol)
        has_position = pos is not None and pos.volume > 0

        prev_bullish = self._prev_vote
        self._prev_vote = bullish

        vote_str = " ".join(["▲" if v > 0 else ("▼" if v < 0 else "─") for v in votes])

        # Buy: transition to consensus bullish (edge trigger)
        if bullish >= self.min_votes and prev_bullish < self.min_votes and not has_position:
            account = self.ctx.get_account()
            volume = int(account.available * self.capital_pct / price / 100) * 100
            if volume > 0:
                await self.ctx.buy(self.symbol, volume=float(volume), price=price,
                                   exchange=self.exchange, order_type=OrderType.LIMIT)
                self.ctx.log(f"BUY consensus {bullish}/3 [{vote_str}] | price={price:.2f}")

        # Sell: consensus turns bearish
        elif bearish >= self.min_votes and has_position:
            available = pos.volume - pos.frozen
            if available > 0:
                await self.ctx.sell(self.symbol, volume=available, price=price,
                                    exchange=self.exchange, order_type=OrderType.LIMIT)
                self.ctx.log(f"SELL consensus {bearish}/3 bear [{vote_str}] | price={price:.2f}")

    def _ma_vote(self, close: pd.Series) -> int:
        """MA crossover vote: +1 bullish, -1 bearish, 0 neutral."""
        if len(close) < self.slow_period + 2:
            return 0
        fast = close.rolling(self.fast_period).mean()
        slow = close.rolling(self.slow_period).mean()
        if float(fast.iloc[-1]) > float(slow.iloc[-1]):
            return 1
        elif float(fast.iloc[-1]) < float(slow.iloc[-1]):
            return -1
        return 0

    def _macd_vote(self, close: pd.Series) -> int:
        """MACD vote: +1 if MACD > signal, -1 if below."""
        if len(close) < self.macd_slow + self.macd_signal:
            return 0
        ema_fast = close.ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.macd_slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        sig = macd.ewm(span=self.macd_signal, adjust=False).mean()
        diff = float(macd.iloc[-1]) - float(sig.iloc[-1])
        return 1 if diff > 0 else (-1 if diff < 0 else 0)

    def _rsi_vote(self, close: pd.Series) -> int:
        """RSI vote: above 50 and rising → bullish; below 50 and falling → bearish."""
        if len(close) < self.rsi_period + 3:
            return 0
        delta = close.diff().dropna()
        gain = delta.clip(lower=0).rolling(self.rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(self.rsi_period).mean()
        if float(loss.iloc[-1]) == 0:
            rsi_now, rsi_prev = 100.0, 100.0
        else:
            rsi_now = 100 - 100 / (1 + float(gain.iloc[-1]) / float(loss.iloc[-1]))
            if float(loss.iloc[-2]) == 0:
                rsi_prev = 100.0
            else:
                rsi_prev = 100 - 100 / (1 + float(gain.iloc[-2]) / float(loss.iloc[-2]))

        if rsi_now > 50 and rsi_now > rsi_prev:
            return 1
        elif rsi_now < 50 and rsi_now < rsi_prev:
            return -1
        return 0

    async def on_stop(self) -> None:
        self.ctx.log("Strategy stopped.")
