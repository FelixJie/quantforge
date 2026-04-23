"""Drawdown circuit breaker rule."""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantforge.core.constants import Direction
from quantforge.core.datatypes import OrderData
from quantforge.risk.rules.base import RiskCheckResult, RiskRule

if TYPE_CHECKING:
    from quantforge.risk.manager import RiskContext


class DrawdownLimitRule(RiskRule):
    """Block new BUY orders when drawdown limits are breached.

    Acts as a circuit breaker — when the account has lost too much,
    stop opening new positions to prevent further losses.
    """

    name = "drawdown_limit"
    priority = 5  # High priority, checked early

    def __init__(
        self,
        max_daily_drawdown: float = 0.05,    # 5% daily loss limit
        max_total_drawdown: float = 0.20,    # 20% total drawdown limit
    ):
        self.max_daily_drawdown = max_daily_drawdown
        self.max_total_drawdown = max_total_drawdown

    async def check(self, order: OrderData, ctx: RiskContext) -> RiskCheckResult:
        # Only restrict new BUY orders — allow selling to exit positions
        if order.direction != Direction.LONG:
            return RiskCheckResult(True, self.name)

        account = ctx.get_account()
        initial = ctx.initial_capital

        if initial <= 0:
            return RiskCheckResult(True, self.name)

        # Total drawdown from initial capital
        total_drawdown = (initial - account.balance) / initial
        if total_drawdown >= self.max_total_drawdown:
            return RiskCheckResult(
                passed=False,
                rule_name=self.name,
                message=(
                    f"Total drawdown {total_drawdown:.1%} >= limit {self.max_total_drawdown:.1%}. "
                    f"New buys blocked."
                ),
            )

        # Daily drawdown check
        daily_start = ctx.daily_start_balance
        if daily_start and daily_start > 0:
            daily_drawdown = (daily_start - account.balance) / daily_start
            if daily_drawdown >= self.max_daily_drawdown:
                return RiskCheckResult(
                    passed=False,
                    rule_name=self.name,
                    message=(
                        f"Daily drawdown {daily_drawdown:.1%} >= limit {self.max_daily_drawdown:.1%}. "
                        f"New buys blocked for today."
                    ),
                )

        return RiskCheckResult(True, self.name)
