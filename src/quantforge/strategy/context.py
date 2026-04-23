"""StrategyContext — the strategy's window into the trading system.

Provides data access, order submission, and position queries.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import TYPE_CHECKING, Any

import pandas as pd
from loguru import logger

from quantforge.core.constants import (
    Direction,
    EventType,
    Exchange,
    Interval,
    OrderStatus,
    OrderType,
)
from quantforge.core.datatypes import (
    AccountData,
    BarData,
    Event,
    OrderData,
    PositionData,
    TradeData,
)

if TYPE_CHECKING:
    from quantforge.core.event import EventEngine


class StrategyContext:
    """Provided to each strategy instance as its interface to the system."""

    def __init__(
        self,
        strategy_name: str,
        event_engine: EventEngine,
        initial_capital: float = 1_000_000.0,
    ):
        self.strategy_name = strategy_name
        self._event_engine = event_engine

        # Internal state
        self._positions: dict[str, PositionData] = {}
        self._orders: dict[str, OrderData] = {}
        self._trades: list[TradeData] = []
        self._account = AccountData(
            account_id=strategy_name,
            balance=initial_capital,
            available=initial_capital,
        )

        # Bar history for indicator computation
        self._bar_history: dict[str, list[BarData]] = {}

        # In-memory log buffer (capped at 500 entries)
        self._logs: list[dict] = []

    # ── Data Access ──────────────────────────────────────────────────

    def record_bar(self, bar: BarData) -> None:
        """Record a bar in history (called by engine, not strategy)."""
        key = bar.symbol
        if key not in self._bar_history:
            self._bar_history[key] = []
        self._bar_history[key].append(bar)

    def get_bars_df(self, symbol: str, count: int = 0) -> pd.DataFrame:
        """Get recent bars as DataFrame. count=0 means all available."""
        bars = self._bar_history.get(symbol, [])
        if count > 0:
            bars = bars[-count:]
        if not bars:
            return pd.DataFrame()
        records = [
            {
                "datetime": b.datetime,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "turnover": b.turnover,
            }
            for b in bars
        ]
        return pd.DataFrame(records)

    # ── Order Management ─────────────────────────────────────────────

    async def buy(
        self,
        symbol: str,
        volume: float,
        price: float,
        exchange: Exchange = Exchange.SSE,
        order_type: OrderType = OrderType.LIMIT,
    ) -> str:
        """Submit a buy order. Returns order_id."""
        return await self._submit_order(
            symbol, exchange, Direction.LONG, volume, price, order_type
        )

    async def sell(
        self,
        symbol: str,
        volume: float,
        price: float,
        exchange: Exchange = Exchange.SSE,
        order_type: OrderType = OrderType.LIMIT,
    ) -> str:
        """Submit a sell order. Returns order_id."""
        return await self._submit_order(
            symbol, exchange, Direction.SHORT, volume, price, order_type
        )

    async def cancel(self, order_id: str) -> None:
        """Cancel an open order."""
        order = self._orders.get(order_id)
        if order and order.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED):
            order.status = OrderStatus.CANCELLED

    async def _submit_order(
        self,
        symbol: str,
        exchange: Exchange,
        direction: Direction,
        volume: float,
        price: float,
        order_type: OrderType,
    ) -> str:
        order_id = str(uuid.uuid4())[:8]
        order = OrderData(
            order_id=order_id,
            symbol=symbol,
            exchange=exchange,
            direction=direction,
            order_type=order_type,
            price=price,
            volume=volume,
            status=OrderStatus.PENDING,
            strategy_name=self.strategy_name,
        )
        self._orders[order_id] = order

        # Publish ORDER event for the execution pipeline
        event = Event(type=EventType.ORDER, data=order, source=self.strategy_name)
        await self._event_engine.publish(event)

        return order_id

    # ── Position Queries ─────────────────────────────────────────────

    def get_position(self, symbol: str) -> PositionData | None:
        return self._positions.get(symbol)

    def get_all_positions(self) -> list[PositionData]:
        return list(self._positions.values())

    def get_account(self) -> AccountData:
        return self._account

    # ── Internal Updates (called by gateway/engine) ──────────────────

    def update_position(self, position: PositionData) -> None:
        self._positions[position.symbol] = position

    def update_order(self, order: OrderData) -> None:
        self._orders[order.order_id] = order

    def record_trade(self, trade: TradeData) -> None:
        self._trades.append(trade)

    def update_account(self, account: AccountData) -> None:
        self._account = account

    def get_bars_for_risk(self, symbol: str, limit: int = 25) -> pd.DataFrame:
        """Bars provider callable used by MA-based risk rules (anti_chase, trend_alignment)."""
        return self.get_bars_df(symbol, limit)

    def log(self, msg: str, level: str = "info") -> None:
        getattr(logger, level)(f"[{self.strategy_name}] {msg}")
        self._logs.append({
            "time": _dt.datetime.now().isoformat(timespec="seconds"),
            "level": level,
            "msg": msg,
        })
        if len(self._logs) > 500:
            self._logs = self._logs[-500:]
