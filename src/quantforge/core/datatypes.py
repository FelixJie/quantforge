"""Core data models for QuantForge."""

from __future__ import annotations

import datetime as _dt
from typing import Optional

from pydantic import BaseModel, Field

from quantforge.core.constants import (
    Direction,
    EventType,
    Exchange,
    Interval,
    OrderStatus,
    OrderType,
)

# Alias to avoid field-name vs class-name conflict in Python 3.14 annotations
DateTime = _dt.datetime


class TickData(BaseModel):
    """Real-time tick data."""
    symbol: str
    exchange: Exchange
    datetime: DateTime
    last_price: float
    volume: float
    turnover: float = 0.0
    bid_price_1: float = 0.0
    ask_price_1: float = 0.0
    bid_volume_1: float = 0.0
    ask_volume_1: float = 0.0


class BarData(BaseModel):
    """OHLCV bar data."""
    symbol: str
    exchange: Exchange
    interval: Interval
    datetime: DateTime
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float = 0.0
    open_interest: float = 0.0


class OrderData(BaseModel):
    """Order information."""
    order_id: str
    symbol: str
    exchange: Exchange
    direction: Direction
    order_type: OrderType
    price: float
    volume: float
    filled: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    strategy_name: str = ""
    datetime: Optional[DateTime] = None


class TradeData(BaseModel):
    """Fill / trade execution data."""
    trade_id: str
    order_id: str
    symbol: str
    exchange: Exchange
    direction: Direction
    price: float
    volume: float
    commission: float = 0.0
    slippage: float = 0.0
    datetime: Optional[DateTime] = None


class PositionData(BaseModel):
    """Position state."""
    symbol: str
    exchange: Exchange
    direction: Direction = Direction.LONG
    volume: float = 0.0
    frozen: float = 0.0          # T+1: shares bought today, cannot sell
    avg_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


class AccountData(BaseModel):
    """Account state."""
    account_id: str = "default"
    balance: float = 0.0
    available: float = 0.0
    frozen: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


class SignalData(BaseModel):
    """Strategy signal (before becoming an order)."""
    strategy_name: str
    symbol: str
    exchange: Exchange
    direction: Direction
    volume: float
    price: float = 0.0
    order_type: OrderType = OrderType.LIMIT
    datetime: Optional[DateTime] = None


class Event(BaseModel):
    """Event flowing through EventEngine."""
    model_config = {"arbitrary_types_allowed": True}

    type: EventType
    data: TickData | BarData | OrderData | TradeData | PositionData | AccountData | SignalData | str
    timestamp: DateTime = Field(default_factory=_dt.datetime.now)
    source: str = ""
