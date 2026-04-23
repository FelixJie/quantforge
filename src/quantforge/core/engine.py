"""MainEngine — lifecycle manager and component registry.

Wires together EventEngine, DataManager, RiskManager,
OrderRouter, and Strategy instances into a coherent runtime.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from loguru import logger

from quantforge.core.constants import EngineStatus, EventType, OrderStatus
from quantforge.core.datatypes import Event, OrderData
from quantforge.core.event import EventEngine
from quantforge.core.settings import Settings
from quantforge.data.manager import DataManager
from quantforge.execution.signal_bus import ClutchState, SignalBus
from quantforge.risk.manager import RiskManager
from quantforge.risk.rules.concentration import ConcentrationRule
from quantforge.risk.rules.drawdown_limit import DrawdownLimitRule
from quantforge.risk.rules.position_limit import PositionLimitRule
from quantforge.risk.rules.stop_loss import StopLossRule
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


class MainEngine:
    """Central hub that owns all system components.

    Responsibilities:
    - Start/stop the event loop
    - Register gateways, strategies, risk rules
    - Route orders through risk → execution
    - Provide a clean API for CLI and API layers
    """

    def __init__(self, settings: Settings | None = None, data_dir: str = "data"):
        self._settings = settings or Settings()
        self._status = EngineStatus.STOPPED

        # Core components
        self.event_engine = EventEngine()
        self.data_manager = DataManager(data_dir)

        # Strategy registry
        self._strategies: dict[str, Strategy] = {}
        self._contexts: dict[str, StrategyContext] = {}
        self._risk_managers: dict[str, RiskManager] = {}
        self._signal_buses: dict[str, SignalBus] = {}

        # Gateway registry (name → gateway instance)
        self._gateways: dict[str, Any] = {}

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._status != EngineStatus.STOPPED:
            return
        self._status = EngineStatus.STARTING
        await self.event_engine.start()
        self._status = EngineStatus.RUNNING
        logger.info("MainEngine started")

    async def stop(self) -> None:
        if self._status != EngineStatus.RUNNING:
            return
        self._status = EngineStatus.STOPPING
        for strategy in self._strategies.values():
            await strategy.on_stop()
        await self.event_engine.stop()
        self._status = EngineStatus.STOPPED
        logger.info("MainEngine stopped")

    @property
    def status(self) -> EngineStatus:
        return self._status

    # ── Gateway ──────────────────────────────────────────────────────

    def register_gateway(self, gateway) -> None:
        self._gateways[gateway.name] = gateway
        logger.info(f"Gateway registered: {gateway.name}")

    def get_gateway(self, name: str):
        return self._gateways.get(name)

    # ── Strategy ─────────────────────────────────────────────────────

    def add_strategy(
        self,
        strategy_cls: type[Strategy],
        params: dict | None = None,
        initial_capital: float | None = None,
        clutch_state: ClutchState = ClutchState.ENGAGED,
        gateway_name: str = "sim",
    ) -> str:
        """Register and initialise a strategy. Returns strategy name."""
        capital = initial_capital or self._settings.get(
            "backtest.initial_capital", 1_000_000.0
        )
        strategy_name = strategy_cls.name or strategy_cls.__name__

        # Create context
        ctx = StrategyContext(
            strategy_name=strategy_name,
            event_engine=self.event_engine,
            initial_capital=capital,
        )

        # Create risk manager with default rules from config
        rm = self._build_risk_manager(ctx, capital)

        # Create signal bus
        bus = SignalBus(state=clutch_state)
        bus.register_buy_fn(ctx.buy)
        bus.register_sell_fn(ctx.sell)

        # Create strategy
        strategy = strategy_cls(ctx, params or {})

        # Wire ORDER event: risk check → gateway
        async def handle_order(event: Event) -> None:
            order: OrderData = event.data
            if order.strategy_name != strategy_name:
                return
            if order.status != OrderStatus.PENDING:
                ctx.update_order(order)
                return
            # Run risk checks
            passed = await rm.check_order(order)
            if passed:
                gateway = self._gateways.get(gateway_name)
                if gateway:
                    await gateway.send_order(order)

        self.event_engine.register(EventType.ORDER, handle_order)

        # Store
        self._strategies[strategy_name] = strategy
        self._contexts[strategy_name] = ctx
        self._risk_managers[strategy_name] = rm
        self._signal_buses[strategy_name] = bus

        logger.info(f"Strategy added: {strategy_name}")
        return strategy_name

    async def init_strategy(self, strategy_name: str) -> None:
        strategy = self._strategies[strategy_name]
        await strategy.on_init()
        strategy.inited = True
        logger.info(f"Strategy initialised: {strategy_name}")

    # ── Risk ─────────────────────────────────────────────────────────

    def _build_risk_manager(self, ctx: StrategyContext, capital: float) -> RiskManager:
        rm = RiskManager(self.event_engine, ctx, capital)
        rm.add_rule(DrawdownLimitRule(
            max_daily_drawdown=self._settings.get("risk.max_daily_drawdown", 0.05),
            max_total_drawdown=self._settings.get("risk.max_total_drawdown", 0.20),
        ))
        rm.add_rule(PositionLimitRule(
            max_single_pct=self._settings.get("risk.max_position_pct", 0.10),
        ))
        rm.add_rule(ConcentrationRule())
        rm.add_rule(StopLossRule())
        return rm

    def get_risk_manager(self, strategy_name: str) -> RiskManager | None:
        return self._risk_managers.get(strategy_name)

    # ── Clutch control ───────────────────────────────────────────────

    def engage_clutch(self, strategy_name: str) -> None:
        bus = self._signal_buses.get(strategy_name)
        if bus:
            bus.engage()

    def disengage_clutch(self, strategy_name: str) -> None:
        bus = self._signal_buses.get(strategy_name)
        if bus:
            bus.disengage()

    # ── Queries ──────────────────────────────────────────────────────

    def get_context(self, strategy_name: str) -> StrategyContext | None:
        return self._contexts.get(strategy_name)

    def get_all_strategies(self) -> list[str]:
        return list(self._strategies.keys())
