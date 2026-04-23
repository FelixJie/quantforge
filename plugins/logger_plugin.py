"""Example plugin: logs backtest events to a CSV file.

Drop any .py file with a module-level `plugin` attribute into the
plugins/ directory and it will be auto-discovered by PluginManager.
"""

from __future__ import annotations

import csv
from pathlib import Path

from quantforge.plugin.base import BasePlugin
from quantforge.plugin.hooks import HookContext


class LoggerPlugin(BasePlugin):
    name = "logger"
    description = "Records backtest events to logs/backtest_events.csv"
    version = "0.1.0"

    def __init__(self):
        self._log_path = Path("logs/backtest_events.csv")
        self._file = None
        self._writer = None

    async def on_load(self, ctx: HookContext) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        ctx.logger.info(f"LoggerPlugin: will write events to {self._log_path}")

    async def on_backtest_start(self, ctx: HookContext) -> None:
        self._file = open(self._log_path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(["event", "strategy", "symbols", "start", "end"])
        self._writer.writerow([
            "backtest_start",
            ctx.strategy_name,
            ",".join(ctx.symbols),
            str(ctx.start),
            str(ctx.end),
        ])

    async def on_backtest_end(self, ctx: HookContext) -> None:
        if ctx.result and self._writer:
            self._writer.writerow([
                "backtest_end",
                ctx.strategy_name,
                ",".join(ctx.symbols),
                f"return={ctx.result.total_return:.4f}",
                f"sharpe={ctx.result.sharpe_ratio:.4f}",
            ])
        if self._file:
            self._file.close()
            self._file = None
            self._writer = None

    async def on_trade(self, ctx: HookContext) -> None:
        if ctx.trade and self._writer:
            t = ctx.trade
            self._writer.writerow([
                "trade",
                ctx.strategy_name,
                t.symbol,
                str(t.direction),
                f"price={t.price}",
            ])

    async def on_risk_alert(self, ctx: HookContext) -> None:
        ctx.logger.warning(
            f"[LoggerPlugin] Risk alert for {ctx.strategy_name}: "
            f"{ctx.extra.get('reason', 'unknown')}"
        )


plugin = LoggerPlugin()
