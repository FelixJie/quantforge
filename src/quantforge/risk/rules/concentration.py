"""Concentration limit rule — prevent over-concentration in few stocks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantforge.core.constants import Direction
from quantforge.core.datatypes import OrderData
from quantforge.risk.rules.base import RiskCheckResult, RiskRule

if TYPE_CHECKING:
    from quantforge.risk.manager import RiskContext


class ConcentrationRule(RiskRule):
    """Limit the number of distinct holdings and concentration in top positions."""

    name = "concentration"
    priority = 20

    def __init__(
        self,
        max_holdings: int = 10,          # max number of distinct stocks held
        max_top1_pct: float = 0.30,      # top-1 holding cannot exceed 30% of portfolio
    ):
        self.max_holdings = max_holdings
        self.max_top1_pct = max_top1_pct

    async def check(self, order: OrderData, ctx: RiskContext) -> RiskCheckResult:
        if order.direction != Direction.LONG:
            return RiskCheckResult(True, self.name)

        positions = [p for p in ctx.get_all_positions() if p.volume > 0]
        account = ctx.get_account()

        # Check max holdings
        existing_symbols = {p.symbol for p in positions}
        is_new_symbol = order.symbol not in existing_symbols
        if is_new_symbol and len(existing_symbols) >= self.max_holdings:
            return RiskCheckResult(
                passed=False,
                rule_name=self.name,
                message=(
                    f"Already holding {len(existing_symbols)} stocks "
                    f"(max={self.max_holdings}). Cannot open new position in {order.symbol}."
                ),
            )

        # Check top-1 concentration
        if account.balance > 0:
            order_value = order.price * order.volume
            pos_values = {p.symbol: p.avg_price * p.volume for p in positions}
            pos_values[order.symbol] = pos_values.get(order.symbol, 0) + order_value
            top1_pct = max(pos_values.values()) / account.balance
            if top1_pct > self.max_top1_pct:
                return RiskCheckResult(
                    passed=False,
                    rule_name=self.name,
                    message=(
                        f"Top-1 concentration would be {top1_pct:.1%}, "
                        f"exceeds limit of {self.max_top1_pct:.1%}."
                    ),
                )

        return RiskCheckResult(True, self.name)
