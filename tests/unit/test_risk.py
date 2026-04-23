"""Unit tests for risk management module."""

from __future__ import annotations

import pytest

from quantforge.core.constants import Direction, Exchange, OrderStatus, OrderType
from quantforge.core.datatypes import AccountData, OrderData, PositionData
from quantforge.core.event import EventEngine
from quantforge.risk.manager import RiskContext, RiskManager
from quantforge.risk.rules.concentration import ConcentrationRule
from quantforge.risk.rules.drawdown_limit import DrawdownLimitRule
from quantforge.risk.rules.position_limit import PositionLimitRule
from quantforge.strategy.context import StrategyContext


def make_order(symbol="000001", direction=Direction.LONG, price=10.0, volume=1000):
    return OrderData(
        order_id="test001",
        symbol=symbol,
        exchange=Exchange.SZSE,
        direction=direction,
        order_type=OrderType.LIMIT,
        price=price,
        volume=volume,
        strategy_name="test",
    )


def make_risk_context(balance=100_000.0):
    account = AccountData(balance=balance, available=balance)
    positions = []

    def get_account():
        return account

    def get_position(symbol):
        return next((p for p in positions if p.symbol == symbol), None)

    def get_all_positions():
        return positions

    ctx = RiskContext(get_account, get_position, get_all_positions, balance)
    ctx._positions = positions
    ctx._account = account
    return ctx


class TestPositionLimitRule:
    @pytest.mark.asyncio
    async def test_within_limit_passes(self):
        rule = PositionLimitRule(max_single_pct=0.20)
        ctx = make_risk_context(100_000.0)
        order = make_order(price=10.0, volume=100)  # 1000 value = 1% of 100k
        result = await rule.check(order, ctx)
        assert result.passed

    @pytest.mark.asyncio
    async def test_exceeds_limit_rejected(self):
        rule = PositionLimitRule(max_single_pct=0.05)
        ctx = make_risk_context(100_000.0)
        order = make_order(price=10.0, volume=1000)  # 10,000 value = 10% > 5%
        result = await rule.check(order, ctx)
        assert not result.passed
        assert "10.0%" in result.message

    @pytest.mark.asyncio
    async def test_sell_not_restricted(self):
        rule = PositionLimitRule(max_single_pct=0.01)
        ctx = make_risk_context(100_000.0)
        order = make_order(direction=Direction.SHORT, price=10.0, volume=10000)
        result = await rule.check(order, ctx)
        # Sells reduce position so should pass
        assert result.passed


class TestDrawdownLimitRule:
    @pytest.mark.asyncio
    async def test_no_drawdown_passes(self):
        rule = DrawdownLimitRule(max_total_drawdown=0.20)
        ctx = make_risk_context(100_000.0)
        ctx.initial_capital = 100_000.0
        order = make_order()
        result = await rule.check(order, ctx)
        assert result.passed

    @pytest.mark.asyncio
    async def test_total_drawdown_blocks_buys(self):
        rule = DrawdownLimitRule(max_total_drawdown=0.20)
        ctx = make_risk_context(75_000.0)   # 25% drawdown from 100k
        ctx.initial_capital = 100_000.0
        order = make_order(direction=Direction.LONG)
        result = await rule.check(order, ctx)
        assert not result.passed
        assert "25.0%" in result.message

    @pytest.mark.asyncio
    async def test_sell_allowed_during_drawdown(self):
        rule = DrawdownLimitRule(max_total_drawdown=0.20)
        ctx = make_risk_context(75_000.0)
        ctx.initial_capital = 100_000.0
        order = make_order(direction=Direction.SHORT)
        result = await rule.check(order, ctx)
        assert result.passed


class TestConcentrationRule:
    @pytest.mark.asyncio
    async def test_within_holdings_passes(self):
        rule = ConcentrationRule(max_holdings=5, max_top1_pct=0.50)
        ctx = make_risk_context(100_000.0)
        order = make_order(price=10.0, volume=100)
        result = await rule.check(order, ctx)
        assert result.passed

    @pytest.mark.asyncio
    async def test_max_holdings_blocks_new_symbol(self):
        rule = ConcentrationRule(max_holdings=2, max_top1_pct=0.99)
        ctx = make_risk_context(100_000.0)
        # Pre-populate 2 positions
        for sym in ["000001", "000002"]:
            ctx._positions.append(
                PositionData(symbol=sym, exchange=Exchange.SZSE, volume=100, avg_price=10.0)
            )
        # Try to add a 3rd symbol
        order = make_order(symbol="000003")
        result = await rule.check(order, ctx)
        assert not result.passed
        assert "000003" in result.message


class TestRiskManager:
    @pytest.mark.asyncio
    async def test_all_rules_pass(self):
        ee = EventEngine()
        ctx = StrategyContext("test", ee, initial_capital=1_000_000.0)
        rm = RiskManager(ee, ctx, 1_000_000.0)
        rm.add_rule(PositionLimitRule(max_single_pct=0.95))

        order = make_order(price=10.0, volume=1000)
        passed = await rm.check_order(order)
        assert passed

    @pytest.mark.asyncio
    async def test_rule_rejection_sets_status(self):
        ee = EventEngine()
        ctx = StrategyContext("test", ee, initial_capital=100_000.0)
        rm = RiskManager(ee, ctx, 100_000.0)
        rm.add_rule(PositionLimitRule(max_single_pct=0.01))

        order = make_order(price=10.0, volume=5000)  # 50k = 50% > 1%
        passed = await rm.check_order(order)
        assert not passed
        assert order.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_rules_checked_in_priority_order(self):
        ee = EventEngine()
        ctx = StrategyContext("test", ee, initial_capital=100_000.0)
        rm = RiskManager(ee, ctx, 100_000.0)

        # Priority 5 rule (checked first)
        rm.add_rule(DrawdownLimitRule(max_total_drawdown=0.01))  # very tight
        rm.add_rule(PositionLimitRule(max_single_pct=0.95))

        # Account has 25% drawdown → DrawdownLimitRule should fire first
        ctx._account.balance = 75_000.0
        rm._risk_ctx.initial_capital = 100_000.0

        order = make_order(direction=Direction.LONG)
        passed = await rm.check_order(order)
        assert not passed
