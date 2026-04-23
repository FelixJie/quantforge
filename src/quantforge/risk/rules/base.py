"""Abstract risk rule interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from quantforge.core.datatypes import OrderData

if TYPE_CHECKING:
    from quantforge.risk.manager import RiskContext


@dataclass
class RiskCheckResult:
    """Result of a single risk rule check."""
    passed: bool
    rule_name: str
    message: str = ""


class RiskRule(ABC):
    """A single, composable risk check.

    Rules are evaluated in order of priority (lower = checked first).
    If any rule returns passed=False, the order is rejected.
    """

    name: str = ""
    enabled: bool = True
    priority: int = 100

    @abstractmethod
    async def check(self, order: OrderData, ctx: RiskContext) -> RiskCheckResult:
        """Evaluate the order against this rule.

        Return RiskCheckResult with passed=False to reject the order.
        """
        ...
