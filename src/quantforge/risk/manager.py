"""RiskManager — central order interception pipeline.

All orders pass through RiskManager before reaching the execution gateway.
Inspired by WonderTrader's composite risk control architecture.
"""

from __future__ import annotations

import datetime as _dt
from typing import TYPE_CHECKING, Callable

import pandas as pd
from loguru import logger

from quantforge.core.constants import EventType, OrderStatus
from quantforge.core.datatypes import AccountData, Event, OrderData, PositionData
from quantforge.core.errors import RiskRejectedError
from quantforge.risk.rules.base import RiskCheckResult, RiskRule

if TYPE_CHECKING:
    from quantforge.core.event import EventEngine


class RiskContext:
    """Read-only view of account/position/market state provided to risk rules."""

    def __init__(
        self,
        get_account_fn,
        get_position_fn,
        get_all_positions_fn,
        initial_capital: float,
        get_bars_fn: Callable[[str, int], pd.DataFrame] | None = None,
    ):
        self._get_account = get_account_fn
        self._get_position = get_position_fn
        self._get_all_positions = get_all_positions_fn
        self.initial_capital = initial_capital
        self.daily_start_balance: float | None = None
        self._current_date: _dt.date | None = None
        # Optional bars provider for MA-based rules (anti_chase, trend_alignment)
        self.get_bars_fn: Callable[[str, int], pd.DataFrame] | None = get_bars_fn

    def get_account(self) -> AccountData:
        return self._get_account()

    def get_position(self, symbol: str) -> PositionData | None:
        return self._get_position(symbol)

    def get_all_positions(self) -> list[PositionData]:
        return self._get_all_positions()

    def update_daily_balance(self, current_date: _dt.date) -> None:
        """Record start-of-day balance for daily drawdown calculation."""
        if self._current_date != current_date:
            self._current_date = current_date
            self.daily_start_balance = self._get_account().balance


class RiskManager:
    """Intercepts all orders and runs them through registered risk rules.

    Usage:
        rm = RiskManager(event_engine, ctx)
        rm.add_rule(PositionLimitRule(max_single_pct=0.10))
        rm.add_rule(DrawdownLimitRule(max_total_drawdown=0.20))

    Any rule returning passed=False causes the order to be REJECTED
    and a RISK_ALERT event to be published.
    """

    def __init__(
        self,
        event_engine: EventEngine,
        strategy_ctx,  # StrategyContext — avoid circular import
        initial_capital: float,
    ):
        self._event_engine = event_engine
        self._strategy_ctx = strategy_ctx
        self._rules: list[RiskRule] = []

        # Wire up bars provider if StrategyContext exposes one
        get_bars_fn = getattr(strategy_ctx, "get_bars_for_risk", None)

        self._risk_ctx = RiskContext(
            get_account_fn=strategy_ctx.get_account,
            get_position_fn=strategy_ctx.get_position,
            get_all_positions_fn=strategy_ctx.get_all_positions,
            initial_capital=initial_capital,
            get_bars_fn=get_bars_fn,
        )

    def add_rule(self, rule: RiskRule) -> None:
        """Register a risk rule. Rules are sorted by priority automatically."""
        # Auto-wire bars provider for MA-based rules
        if hasattr(rule, "set_bars_provider") and self._risk_ctx.get_bars_fn is not None:
            rule.set_bars_provider(self._risk_ctx.get_bars_fn)
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)
        logger.debug(f"Risk rule added: {rule.name} (priority={rule.priority})")

    def remove_rule(self, rule_name: str) -> None:
        self._rules = [r for r in self._rules if r.name != rule_name]

    def update_daily(self, current_date: _dt.date) -> None:
        """Called at the start of each new trading day."""
        self._risk_ctx.update_daily_balance(current_date)

    async def check_order(self, order: OrderData) -> bool:
        """Run all rules against an order.

        Returns True if order passes all checks.
        Publishes RISK_ALERT event and sets order status to REJECTED on failure.
        """
        for rule in self._rules:
            if not rule.enabled:
                continue
            result: RiskCheckResult = await rule.check(order, self._risk_ctx)
            if not result.passed:
                order.status = OrderStatus.REJECTED
                self._strategy_ctx.update_order(order)

                alert_msg = f"[{result.rule_name}] {result.message}"
                logger.warning(f"Risk REJECTED order {order.order_id} | {alert_msg}")

                alert_event = Event(
                    type=EventType.RISK_ALERT,
                    data=alert_msg,
                    source="risk_manager",
                )
                await self._event_engine.publish(alert_event)
                return False

        return True

    @property
    def rules(self) -> list[RiskRule]:
        return list(self._rules)
