"""Chandelier Exit Strategy — ATR-based trailing stop trend following.

The Chandelier Exit sets a dynamic stop loss that trails the highest high
achieved since entry by a multiple of ATR. This lets winners run while
providing a volatility-calibrated floor.

Entry: Price closes above the N-day EMA (trend confirmation)
Exit:  Price falls below (highest_high_since_entry - mult × ATR)

The stop level rises with new highs but never falls, creating an asymmetric
payoff — unlimited upside, bounded downside.

Parameters:
    ema_period   : EMA period for trend entry filter (default 21)
    atr_period   : ATR period for stop calibration (default 22)
    multiplier   : Stop = highest_high - mult × ATR (default 3.0)
"""

from typing import ClassVar

from quantforge.core.constants import Exchange, OrderType
from quantforge.core.datatypes import BarData
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


class ChandelierExitStrategy(Strategy):
    """Chandelier Exit trailing-stop trend following strategy."""

    name: ClassVar[str] = "chandelier_exit"
    description: ClassVar[str] = (
        "吊灯止损趋势跟踪 — 以最高价的ATR倍数设定动态追踪止损位，止损只升不降，"
        "让盈利奔跑同时严格控制回撤。价格上穿EMA时入场，跌破止损线时出场。"
        "适合波动率稳定的强势趋势个股，夏普比率通常优于固定止损策略。"
    )
    author: ClassVar[str] = "QuantForge"
    category: ClassVar[str] = "trend_following"
    tags: ClassVar[list[str]] = ["吊灯止损", "追踪止损", "ATR", "EMA", "趋势跟随", "让利润奔跑"]
    parameters: ClassVar[list[str]] = ["symbol", "ema_period", "atr_period", "multiplier"]

    symbol: str = "000001"
    exchange: Exchange = Exchange.SZSE
    ema_period: int = 21
    atr_period: int = 22
    multiplier: float = 3.0

    def __init__(self, ctx: StrategyContext, params: dict | None = None):
        super().__init__(ctx, params)
        if isinstance(self.exchange, str):
            self.exchange = Exchange(self.exchange)
        self._highest_high: float = 0.0
        self._stop: float = 0.0
        self._in_position: bool = False

    async def on_init(self) -> None:
        self.ctx.log(
            f"Chandelier Exit | ema={self.ema_period} atr={self.atr_period} "
            f"mult={self.multiplier} symbol={self.symbol}"
        )

    async def on_bar(self, bar: BarData) -> None:
        if bar.symbol != self.symbol:
            return
        df = self.ctx.get_bars_df(self.symbol)
        min_bars = max(self.ema_period, self.atr_period) + 2
        if len(df) < min_bars:
            return

        price = bar.close
        high = bar.high
        close = df["close"]

        ema = float(close.ewm(span=self.ema_period, adjust=False).mean().iloc[-1])
        atr = self._calc_atr(df)

        pos = self.ctx.get_position(self.symbol)
        has_position = pos is not None and pos.volume > 0

        if has_position:
            # Update trailing stop
            self._highest_high = max(self._highest_high, high)
            new_stop = self._highest_high - self.multiplier * atr
            self._stop = max(self._stop, new_stop)  # stop can only rise

            if price <= self._stop:
                available = pos.volume - pos.frozen
                if available > 0:
                    await self.ctx.sell(self.symbol, volume=available, price=price,
                                        exchange=self.exchange, order_type=OrderType.LIMIT)
                    self.ctx.log(
                        f"EXIT [吊灯止损] price={price:.2f} stop={self._stop:.2f} "
                        f"high_since_entry={self._highest_high:.2f}"
                    )
                    self._highest_high = 0.0
                    self._stop = 0.0
        else:
            # Entry: price above EMA
            if price > ema:
                account = self.ctx.get_account()
                volume = int(account.available * 0.9 / price / 100) * 100
                if volume > 0:
                    await self.ctx.buy(self.symbol, volume=float(volume), price=price,
                                       exchange=self.exchange, order_type=OrderType.LIMIT)
                    self._highest_high = high
                    self._stop = high - self.multiplier * atr
                    self.ctx.log(
                        f"BUY [EMA突破] price={price:.2f} ema={ema:.2f} "
                        f"init_stop={self._stop:.2f}"
                    )

    def _calc_atr(self, df) -> float:
        high = df["high"]
        low = df["low"]
        close_prev = df["close"].shift(1)
        tr = (high - low).combine(
            (high - close_prev).abs(), max
        ).combine((low - close_prev).abs(), max)
        return float(tr.rolling(self.atr_period).mean().iloc[-1])

    async def on_stop(self) -> None:
        self.ctx.log(f"Chandelier strategy stopped. Stop level was: {self._stop:.2f}")
