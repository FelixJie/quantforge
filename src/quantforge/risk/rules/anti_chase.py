"""Anti-chase rule — reject buy orders when price deviates too far above MA20.

Borrowing from daily_stock_analysis: blocks new buys when the current price
is more than `max_deviation_pct` above the 20-day moving average. In strong
trends the threshold is relaxed by `trend_relax_pct`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import pandas as pd
from loguru import logger

from quantforge.core.constants import Direction
from quantforge.core.datatypes import OrderData
from quantforge.risk.rules.base import RiskCheckResult, RiskRule

if TYPE_CHECKING:
    from quantforge.risk.manager import RiskContext


class AntiChaseRule(RiskRule):
    """Block buy orders when price is too far above MA20.

    A 'strong trend' is defined as MA5 > MA10 > MA20.  In that case the
    threshold is relaxed by `trend_relax_pct` to allow trend-following entries.
    """

    name = "anti_chase"
    priority = 5   # checked early — cheapest rejection

    def __init__(
        self,
        max_deviation_pct: float = 0.05,
        trend_relax_pct: float = 0.03,
        ma_period: int = 20,
        get_bars_fn: Callable[[str, int], pd.DataFrame] | None = None,
    ):
        """
        Args:
            max_deviation_pct: Max allowed deviation above MA20 (default 5%).
            trend_relax_pct: Additional allowance when MA5>MA10>MA20 (default 3%).
            ma_period: MA period for anchor price (default 20).
            get_bars_fn: Optional callable(symbol, limit) → OHLCV DataFrame.
                         If None, rule is skipped (fail-open).
        """
        self.max_deviation_pct = max_deviation_pct
        self.trend_relax_pct = trend_relax_pct
        self.ma_period = ma_period
        self.get_bars_fn = get_bars_fn

    def set_bars_provider(self, fn: Callable[[str, int], pd.DataFrame]) -> None:
        """Wire up bars provider after construction."""
        self.get_bars_fn = fn

    def _compute_mas(self, symbol: str) -> tuple[float | None, float | None, float | None, float | None]:
        """Return (ma5, ma10, ma20, latest_close) or (None, None, None, None) on failure."""
        if self.get_bars_fn is None:
            return None, None, None, None
        try:
            df = self.get_bars_fn(symbol, self.ma_period + 5)
            if df is None or len(df) < self.ma_period:
                return None, None, None, None
            close = df["close"].astype(float)
            ma5  = float(close.rolling(5).mean().iloc[-1])  if len(close) >= 5  else None
            ma10 = float(close.rolling(10).mean().iloc[-1]) if len(close) >= 10 else None
            ma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else None
            latest = float(close.iloc[-1])
            return ma5, ma10, ma20, latest
        except Exception as e:
            logger.debug(f"anti_chase: MA compute failed for {symbol}: {e}")
            return None, None, None, None

    async def check(self, order: OrderData, ctx: RiskContext) -> RiskCheckResult:
        if order.direction != Direction.LONG:
            return RiskCheckResult(True, self.name)

        ma5, ma10, ma20, latest_close = self._compute_mas(order.symbol)
        if ma20 is None:
            # Cannot compute — fail open
            return RiskCheckResult(True, self.name)

        # Determine effective threshold
        is_strong_trend = ma5 is not None and ma10 is not None and ma5 > ma10 > ma20
        threshold = self.max_deviation_pct + (self.trend_relax_pct if is_strong_trend else 0.0)

        order_price = order.price if order.price > 0 else latest_close
        deviation = (order_price - ma20) / ma20

        if deviation > threshold:
            trend_note = " (strong trend, threshold relaxed)" if is_strong_trend else ""
            return RiskCheckResult(
                passed=False,
                rule_name=self.name,
                message=(
                    f"{order.symbol} 追高预警: 现价偏离MA{self.ma_period} "
                    f"{deviation:.1%} > 阈值 {threshold:.1%}{trend_note}，拒绝买入。"
                ),
            )
        return RiskCheckResult(True, self.name)
