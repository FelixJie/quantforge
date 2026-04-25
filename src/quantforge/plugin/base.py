"""Abstract base class for QuantForge plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quantforge.plugin.hooks import HookContext


class BasePlugin(ABC):
    """All plugins must subclass BasePlugin and implement the three lifecycle methods.

    Discovery: place a .py file inside a directory that is registered with
    PluginManager.register_directory().  The file must expose a module-level
    ``plugin`` attribute that is an instance of a BasePlugin subclass.

    Example
    -------
    # my_plugin.py
    from quantforge.plugin.base import BasePlugin
    from quantforge.plugin.hooks import HookContext

    class MyPlugin(BasePlugin):
        name = "my_plugin"
        description = "Does something useful"

        async def on_load(self, ctx: HookContext) -> None:
            ctx.logger.info("MyPlugin loaded")

        async def on_backtest_start(self, ctx: HookContext) -> None:
            ctx.logger.info(f"Backtest starting for {ctx.strategy_name}")

        async def on_backtest_end(self, ctx: HookContext) -> None:
            ctx.logger.info(f"Backtest done. Return={ctx.result.total_return:.2%}")

    plugin = MyPlugin()
    """

    #: Unique identifier (used for logging and deduplication)
    name: str = ""
    #: Human-readable description shown in API / CLI
    description: str = ""
    #: Version string
    version: str = "0.1.0"

    @abstractmethod
    async def on_load(self, ctx: HookContext) -> None:
        """Called once when the plugin is registered."""

    async def on_unload(self, ctx: HookContext) -> None:
        """Called when the plugin is explicitly unloaded."""

    # ── Backtest hooks ────────────────────────────────────────────────

    async def on_backtest_start(self, ctx: HookContext) -> None:
        """Called before the bar-replay loop begins."""

    async def on_bar(self, ctx: HookContext) -> None:
        """Called after each bar is processed (strategy + events drained)."""

    async def on_backtest_end(self, ctx: HookContext) -> None:
        """Called after the backtest finishes with the final result."""

    # ── Order / trade hooks ───────────────────────────────────────────

    async def on_order(self, ctx: HookContext) -> None:
        """Called when an order event is published."""

    async def on_trade(self, ctx: HookContext) -> None:
        """Called when a trade (fill) event is published."""

    # ── Risk hooks ────────────────────────────────────────────────────

    async def on_risk_alert(self, ctx: HookContext) -> None:
        """Called when RiskManager rejects an order."""
