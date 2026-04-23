"""Volume-Price Breakout Strategy — 量价共振突破.

Combines a price breakout signal with a volume confirmation:
  1. Price breaks above the highest close of the last N bars
  2. Volume is at least vol_multiplier × the N-bar average volume
  Both conditions must be true simultaneously (resonance).

Exit rules:
  - Price falls back below the N-bar moving average → trend over, exit
  - Hard stop at stop_loss % below entry

This strategy filters out false breakouts by requiring volume participation,
improving signal quality in A-share markets which often see high-volume breakouts.
"""

from typing import ClassVar

from quantforge.core.constants import Exchange, OrderType
from quantforge.core.datatypes import BarData
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


class VolumePriceBreakoutStrategy(Strategy):
    """Breakout strategy requiring both price AND volume confirmation."""

    name: ClassVar[str] = "volume_price_breakout"
    description: ClassVar[str] = (
        "量价共振突破策略 — 同时满足价格突破N日高点和成交量放大N倍两个条件才开仓，"
        "有效过滤假突破信号。价格回落均线时止盈出场，内置硬止损控制回撤。"
        "特别适合A股放量突破的主升浪行情。"
    )
    author: ClassVar[str] = "QuantForge"
    category: ClassVar[str] = "trend_following"
    tags: ClassVar[list[str]] = ["量价", "突破", "共振", "放量", "趋势跟随", "过滤"]
    parameters: ClassVar[list[str]] = ["symbol", "lookback", "vol_multiplier", "stop_loss"]

    symbol: str = "000001"
    exchange: Exchange = Exchange.SZSE
    lookback: int = 20            # N-bar lookback for high + avg volume
    vol_multiplier: float = 1.5   # Volume must be > multiplier × avg
    stop_loss: float = 0.07       # Hard stop at 7% below entry

    def __init__(self, ctx: StrategyContext, params: dict | None = None):
        super().__init__(ctx, params)
        if isinstance(self.exchange, str):
            self.exchange = Exchange(self.exchange)
        self._entry_price: float | None = None
        self._in_position: bool = False

    async def on_init(self) -> None:
        self.ctx.log(
            f"Volume-Price Breakout | lookback={self.lookback} "
            f"vol_mult={self.vol_multiplier}× stop={self.stop_loss:.0%}"
        )

    async def on_bar(self, bar: BarData) -> None:
        if bar.symbol != self.symbol:
            return
        df = self.ctx.get_bars_df(self.symbol)
        if len(df) < self.lookback + 2:
            return

        price = bar.close
        volume = bar.volume
        close = df["close"]
        vol_series = df["volume"]

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
                    self.ctx.log(f"STOP LOSS | loss={loss:.2%} entry={self._entry_price:.2f}")
                    self._entry_price = None
                return

        # Exit: price falls back below MA
        if has_position:
            ma = float(close.iloc[-self.lookback:].mean())
            if price < ma:
                available = pos.volume - pos.frozen
                if available > 0:
                    await self.ctx.sell(self.symbol, volume=available, price=price,
                                        exchange=self.exchange, order_type=OrderType.LIMIT)
                    self.ctx.log(f"EXIT [跌破均线] price={price:.2f} ma={ma:.2f}")
                    self._entry_price = None
            return

        # Entry: price + volume breakout (resonance)
        prev_high = float(close.iloc[-self.lookback - 1:-1].max())
        avg_vol = float(vol_series.iloc[-self.lookback - 1:-1].mean())

        price_breakout = price > prev_high
        volume_confirm = avg_vol > 0 and volume > self.vol_multiplier * avg_vol

        if price_breakout and volume_confirm:
            account = self.ctx.get_account()
            trade_vol = int(account.available * 0.9 / price / 100) * 100
            if trade_vol > 0:
                await self.ctx.buy(self.symbol, volume=float(trade_vol), price=price,
                                   exchange=self.exchange, order_type=OrderType.LIMIT)
                self._entry_price = price
                self.ctx.log(
                    f"BUY [量价共振] price={price:.2f} high={prev_high:.2f} "
                    f"vol={volume:.0f} avg={avg_vol:.0f} ({volume/avg_vol:.1f}×)"
                )

    async def on_stop(self) -> None:
        self.ctx.log("Volume-Price strategy stopped.")
