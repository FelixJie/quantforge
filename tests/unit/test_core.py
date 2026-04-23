"""Unit tests for core modules."""

import asyncio
from datetime import datetime

import pytest

from quantforge.core.constants import Direction, EventType, Exchange, Interval, OrderStatus, OrderType
from quantforge.core.datatypes import BarData, Event, OrderData, AccountData
from quantforge.core.event import EventEngine
from quantforge.core.settings import Settings


class TestEventEngine:
    """Tests for the async event bus."""

    @pytest.mark.asyncio
    async def test_publish_and_receive(self):
        engine = EventEngine()
        received = []

        async def handler(event: Event):
            received.append(event)

        engine.register(EventType.LOG, handler)

        event = Event(type=EventType.LOG, data="hello")
        engine.publish_sync(event)

        await engine.process_one()
        assert len(received) == 1
        assert received[0].data == "hello"

    @pytest.mark.asyncio
    async def test_unregister(self):
        engine = EventEngine()
        received = []

        async def handler(event: Event):
            received.append(event)

        engine.register(EventType.LOG, handler)
        engine.unregister(EventType.LOG, handler)

        engine.publish_sync(Event(type=EventType.LOG, data="x"))
        await engine.process_one()
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_process_one_empty(self):
        engine = EventEngine()
        result = await engine.process_one()
        assert result is False


class TestDataTypes:
    """Tests for Pydantic data models."""

    def test_bar_data(self):
        bar = BarData(
            symbol="000001",
            exchange=Exchange.SZSE,
            interval=Interval.DAILY,
            datetime=datetime(2023, 1, 3),
            open=10.0,
            high=10.5,
            low=9.8,
            close=10.2,
            volume=1_000_000,
        )
        assert bar.symbol == "000001"
        assert bar.close == 10.2

    def test_order_data(self):
        order = OrderData(
            order_id="test001",
            symbol="000001",
            exchange=Exchange.SZSE,
            direction=Direction.LONG,
            order_type=OrderType.LIMIT,
            price=10.0,
            volume=1000,
        )
        assert order.status == OrderStatus.PENDING
        assert order.filled == 0.0


class TestSettings:
    """Tests for configuration loading."""

    def test_get_default(self):
        settings = Settings()
        capital = settings.get("backtest.initial_capital")
        assert capital == 1_000_000.0

    def test_get_missing_with_default(self):
        settings = Settings()
        val = settings.get("nonexistent.key", "fallback")
        assert val == "fallback"

    def test_nested_access(self):
        settings = Settings()
        commission = settings.get("backtest.commission_rate")
        assert commission == 0.0003
