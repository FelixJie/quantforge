"""Hook context object — passed to every plugin hook call."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger as _logger

if TYPE_CHECKING:
    from quantforge.backtest.engine import BacktestResult
    from quantforge.core.datatypes import BarData, OrderData, TradeData


@dataclass
class HookContext:
    """Carries all contextual data available to a plugin hook.

    Not every field is populated for every hook — only fields relevant
    to that hook will be set.  Always check for None before using.
    """

    # ── Always available ──────────────────────────────────────────────
    plugin_name: str = ""
    hook_name: str = ""
    logger: Any = field(default_factory=lambda: _logger)

    # ── Backtest context ──────────────────────────────────────────────
    strategy_name: str = ""
    symbols: list[str] = field(default_factory=list)
    start: Any = None        # datetime
    end: Any = None          # datetime
    initial_capital: float = 0.0

    # ── Per-bar context ───────────────────────────────────────────────
    bar: Any = None          # BarData | None

    # ── Post-backtest result ──────────────────────────────────────────
    result: Any = None       # BacktestResult | None

    # ── Order / trade context ─────────────────────────────────────────
    order: Any = None        # OrderData | None
    trade: Any = None        # TradeData | None

    # ── Arbitrary extra data (plugins can stash state here) ───────────
    extra: dict = field(default_factory=dict)
