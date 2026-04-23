"""Abstract Strategy base class — the core developer interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

from quantforge.core.datatypes import BarData, OrderData, TradeData

if TYPE_CHECKING:
    from quantforge.strategy.context import StrategyContext


class Strategy(ABC):
    """Base class for all trading strategies.

    Subclass this and implement on_init() and on_bar() at minimum.
    The strategy interacts with the system exclusively through self.ctx (StrategyContext).
    """

    # Class-level metadata (used by registry and UI)
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    author: ClassVar[str] = ""
    parameters: ClassVar[list[str]] = []  # Parameter names exposed for optimization

    def __init__(self, ctx: StrategyContext, params: dict[str, Any] | None = None):
        self.ctx = ctx
        self.inited: bool = False
        # Apply parameters as instance attributes
        for key, value in (params or {}).items():
            setattr(self, key, value)

    @abstractmethod
    async def on_init(self) -> None:
        """Called once when the strategy is loaded. Set up indicators here."""
        ...

    @abstractmethod
    async def on_bar(self, bar: BarData) -> None:
        """Called on each new bar. Core trading logic goes here."""
        ...

    async def on_order(self, order: OrderData) -> None:
        """Called when an order status changes."""

    async def on_trade(self, trade: TradeData) -> None:
        """Called when a fill occurs."""

    async def on_stop(self) -> None:
        """Called when the strategy is stopped. Cleanup here."""
