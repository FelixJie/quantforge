"""Trend-alignment rule — require MA5 > MA10 > MA20 before allowing buy orders.

Borrowing from daily_stock_analysis: only allow new buy orders when the
short-term moving averages are in a "bull stack" (MA5 above MA10 above MA20).
This prevents buying into downtrends or choppy markets.

The rule is fail-open: if bars data is unavailable it always passes.
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


class TrendAlignmentRule(RiskRule):
    """Require MA5 > MA10 > MA20 bull stack for buy orders.

    Optional: require MA20 itself to be rising (slope > 0) for stricter filtering.
    """

    name = "trend_alignment"
    priority = 6

    def __init__(
        self,
        require_ma20_rising: bool = False,
        get_bars_fn: Callable[[str, int], pd.DataFrame] | None = None,
    ):
        """
        Args:
            require_ma20_rising: If True, also require MA20 to be rising.
            get_bars_fn: Optional callable(symbol, limit) → OHLCV DataFrame.
        """
        self.require_ma20_rising = require_ma20_rising
        self.get_bars_fn = get_bars_fn

    def set_bars_provider(self, fn: Callable[[str, int], pd.DataFrame]) -> None:
        self.get_bars_fn = fn

    async def check(self, order: OrderData, ctx: RiskContext) -> RiskCheckResult:
        if order.direction != Direction.LONG:
            return RiskCheckResult(True, self.name)

        if self.get_bars_fn is None:
            return RiskCheckResult(True, self.name)

        try:
            df = self.get_bars_fn(order.symbol, 25)
            if df is None or len(df) < 20:
                return RiskCheckResult(True, self.name)

            close = df["close"].astype(float)
            ma5  = float(close.rolling(5).mean().iloc[-1])
            ma10 = float(close.rolling(10).mean().iloc[-1])
            ma20 = float(close.rolling(20).mean().iloc[-1])

            bull_stack = ma5 > ma10 > ma20

            if not bull_stack:
                return RiskCheckResult(
                    passed=False,
                    rule_name=self.name,
                    message=(
                        f"{order.symbol} 趋势未对齐: MA5={ma5:.2f} MA10={ma10:.2f} MA20={ma20:.2f}，"
                        f"不满足多头排列(MA5>MA10>MA20)，拒绝买入。"
                    ),
                )

            if self.require_ma20_rising:
                ma20_prev = float(close.rolling(20).mean().iloc[-3])
                if ma20 <= ma20_prev:
                    return RiskCheckResult(
                        passed=False,
                        rule_name=self.name,
                        message=(
                            f"{order.symbol} MA20 未上升 ({ma20_prev:.2f}→{ma20:.2f})，"
                            f"趋势强度不足，拒绝买入。"
                        ),
                    )

        except Exception as e:
            logger.debug(f"trend_alignment: compute failed for {order.symbol}: {e}")

        return RiskCheckResult(True, self.name)
