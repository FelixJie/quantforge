"""Grid Trading Strategy — systematic buy-low / sell-high within a price band.

Creates evenly-spaced grid lines above and below a center price.
Buys when price drops to a lower grid level (and we don't hold that level yet).
Sells when price rises back to the grid level above our entry.

This strategy profits in ranging/oscillating markets through repeated micro-trades
but suffers in strong directional trends (price can exit the grid entirely).

Parameters:
    center_price  : Center of the grid (default: auto-set from first bar)
    grid_spacing  : Price gap between grid lines as a fraction (default: 0.02 = 2%)
    grid_levels   : Number of grid lines above AND below center (default: 5)
    lot_size      : Shares per grid trade (default: 100)
"""

from typing import ClassVar

from quantforge.core.constants import Exchange, OrderType
from quantforge.core.datatypes import BarData
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


class GridTradingStrategy(Strategy):
    """Price-grid mean-reversion strategy for ranging A-share markets."""

    name: ClassVar[str] = "grid_trading"
    description: ClassVar[str] = (
        "网格交易策略 — 以中心价格为基准划定等间距网格，价格下穿网格线时买入，"
        "上穿时卖出，在震荡行情中持续积累差价收益。适合波动率稳定的横盘个股。"
    )
    author: ClassVar[str] = "QuantForge"
    category: ClassVar[str] = "mean_reversion"
    tags: ClassVar[list[str]] = ["网格", "震荡", "均值回归", "低频", "套利", "自动"]
    parameters: ClassVar[list[str]] = ["symbol", "grid_spacing", "grid_levels", "lot_size"]

    symbol: str = "000001"
    exchange: Exchange = Exchange.SZSE
    center_price: float = 0.0     # 0 = auto from first bar
    grid_spacing: float = 0.02    # 2% between grid lines
    grid_levels: int = 5          # grids above and below
    lot_size: int = 100           # shares per grid order

    def __init__(self, ctx: StrategyContext, params: dict | None = None):
        super().__init__(ctx, params)
        if isinstance(self.exchange, str):
            self.exchange = Exchange(self.exchange)
        self._initialized = False
        self._grid_prices: list[float] = []
        # Track which grids we have open buy positions from
        self._held_grids: set[int] = set()  # grid index (negative = below center)

    async def on_init(self) -> None:
        self.ctx.log(
            f"Grid Trading | symbol={self.symbol} spacing={self.grid_spacing:.1%} "
            f"levels={self.grid_levels} lot={self.lot_size}"
        )

    def _build_grid(self, center: float) -> None:
        self._grid_prices = []
        for i in range(-self.grid_levels, self.grid_levels + 1):
            self._grid_prices.append(round(center * (1 + i * self.grid_spacing), 3))
        self._grid_prices.sort()
        self.ctx.log(
            f"Grid built | center={center:.2f} "
            f"range=[{self._grid_prices[0]:.2f}, {self._grid_prices[-1]:.2f}]"
        )

    def _nearest_grid_idx(self, price: float) -> int:
        """Return index of nearest grid price below current price."""
        for i in range(len(self._grid_prices) - 1, -1, -1):
            if self._grid_prices[i] <= price:
                return i
        return 0

    async def on_bar(self, bar: BarData) -> None:
        if bar.symbol != self.symbol:
            return
        price = bar.close

        # Auto-initialize center on first bar
        if not self._initialized:
            center = self.center_price if self.center_price > 0 else price
            self._build_grid(center)
            self._initialized = True
            return

        if not self._grid_prices:
            return

        # Price outside grid — do nothing
        if price <= self._grid_prices[0] or price >= self._grid_prices[-1]:
            return

        grid_idx = self._nearest_grid_idx(price)

        # BUY: price just touched a grid level we don't hold
        if grid_idx not in self._held_grids:
            account = self.ctx.get_account()
            cost = price * self.lot_size
            if account.available >= cost:
                await self.ctx.buy(
                    self.symbol, volume=float(self.lot_size), price=price,
                    exchange=self.exchange, order_type=OrderType.LIMIT,
                )
                self._held_grids.add(grid_idx)
                self.ctx.log(
                    f"BUY [网格{grid_idx}] price={price:.2f} "
                    f"grid={self._grid_prices[grid_idx]:.2f}"
                )

        # SELL: price has risen to the grid above any held grid
        sell_grids = [g for g in list(self._held_grids) if grid_idx > g]
        for g in sell_grids:
            pos = self.ctx.get_position(self.symbol)
            if pos and pos.volume - pos.frozen >= self.lot_size:
                await self.ctx.sell(
                    self.symbol, volume=float(self.lot_size), price=price,
                    exchange=self.exchange, order_type=OrderType.LIMIT,
                )
                self._held_grids.discard(g)
                self.ctx.log(
                    f"SELL [网格{g}→{grid_idx}] price={price:.2f} "
                    f"profit≈{(price - self._grid_prices[g]) * self.lot_size:.2f}"
                )

    async def on_stop(self) -> None:
        self.ctx.log(f"Grid strategy stopped. Held grids: {sorted(self._held_grids)}")
