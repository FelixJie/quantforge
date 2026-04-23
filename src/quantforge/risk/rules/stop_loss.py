"""Stop-loss enforcement rule."""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantforge.core.constants import Direction
from quantforge.core.datatypes import OrderData
from quantforge.risk.rules.base import RiskCheckResult, RiskRule

if TYPE_CHECKING:
    from quantforge.risk.manager import RiskContext


class StopLossRule(RiskRule):
    """Force-close positions that breach the per-trade stop-loss threshold.

    This rule does NOT generate orders directly — instead it rejects
    new BUY orders on symbols where stop-loss has been triggered.
    The strategy is expected to handle stop-loss sells itself; this rule
    acts as a safety net.
    """

    name = "stop_loss"
    priority = 15

    def __init__(self, max_loss_pct: float = 0.08):
        """
        Args:
            max_loss_pct: Maximum allowed loss per position as a fraction (e.g. 0.08 = 8%).
        """
        self.max_loss_pct = max_loss_pct
        self._stopped_symbols: set[str] = set()

    def update(self, ctx: RiskContext) -> list[str]:
        """Check all positions and flag those exceeding stop-loss.

        Returns list of symbols that have been stopped out.
        Called by RiskManager on each bar.
        """
        newly_stopped = []
        for pos in ctx.get_all_positions():
            if pos.volume <= 0 or pos.avg_price <= 0:
                continue
            loss_pct = (pos.avg_price - pos.unrealized_pnl / pos.volume - pos.avg_price) / pos.avg_price
            # Simpler: use unrealized_pnl directly
            unrealized_loss_pct = pos.unrealized_pnl / (pos.avg_price * pos.volume) if pos.avg_price * pos.volume > 0 else 0
            if unrealized_loss_pct < -self.max_loss_pct:
                if pos.symbol not in self._stopped_symbols:
                    self._stopped_symbols.add(pos.symbol)
                    newly_stopped.append(pos.symbol)
        # Remove stopped symbols once position is closed
        closed = [s for s in self._stopped_symbols if not any(p.symbol == s and p.volume > 0 for p in ctx.get_all_positions())]
        for s in closed:
            self._stopped_symbols.discard(s)
        return newly_stopped

    async def check(self, order: OrderData, ctx: RiskContext) -> RiskCheckResult:
        # Block new buys on stopped symbols
        if order.direction == Direction.LONG and order.symbol in self._stopped_symbols:
            return RiskCheckResult(
                passed=False,
                rule_name=self.name,
                message=f"{order.symbol} is stopped out (loss > {self.max_loss_pct:.1%}). Buy blocked.",
            )
        return RiskCheckResult(True, self.name)
