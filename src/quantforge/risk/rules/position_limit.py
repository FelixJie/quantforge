"""Position size limit rule."""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantforge.core.constants import Direction
from quantforge.core.datatypes import OrderData
from quantforge.risk.rules.base import RiskCheckResult, RiskRule

if TYPE_CHECKING:
    from quantforge.risk.manager import RiskContext


class PositionLimitRule(RiskRule):
    """Reject orders that would exceed position size limits.

    Checks:
    - Single stock position cannot exceed max_single_pct of portfolio
    - Total long exposure cannot exceed max_total_pct of portfolio
    """

    name = "position_limit"
    priority = 10

    def __init__(
        self,
        max_single_pct: float = 0.10,   # max 10% in any single stock
        max_total_pct: float = 1.0,      # max 100% total exposure
    ):
        self.max_single_pct = max_single_pct
        self.max_total_pct = max_total_pct

    async def check(self, order: OrderData, ctx: RiskContext) -> RiskCheckResult:
        account = ctx.get_account()
        if account.balance <= 0:
            return RiskCheckResult(True, self.name)

        # Estimated order value
        order_value = order.price * order.volume

        # Current position in this symbol
        pos = ctx.get_position(order.symbol)
        current_pos_value = (pos.avg_price * pos.volume) if pos else 0.0

        # After-fill position value
        if order.direction == Direction.LONG:
            new_pos_value = current_pos_value + order_value
        else:
            new_pos_value = max(current_pos_value - order_value, 0.0)

        # Single stock limit
        single_pct = new_pos_value / account.balance
        if single_pct > self.max_single_pct:
            return RiskCheckResult(
                passed=False,
                rule_name=self.name,
                message=(
                    f"{order.symbol} position would be {single_pct:.1%} of portfolio, "
                    f"exceeds limit of {self.max_single_pct:.1%}"
                ),
            )

        # Total exposure limit
        total_exposure = sum(
            p.avg_price * p.volume for p in ctx.get_all_positions()
        )
        if order.direction == Direction.LONG:
            total_exposure += order_value
        total_pct = total_exposure / account.balance
        if total_pct > self.max_total_pct:
            return RiskCheckResult(
                passed=False,
                rule_name=self.name,
                message=(
                    f"Total exposure would be {total_pct:.1%} of portfolio, "
                    f"exceeds limit of {self.max_total_pct:.1%}"
                ),
            )

        return RiskCheckResult(True, self.name)
