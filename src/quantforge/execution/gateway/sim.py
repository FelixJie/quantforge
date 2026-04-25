"""Simulated gateway for backtesting — realistic fill simulation.

Handles commission, slippage, and A-share T+1 settlement rules.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from loguru import logger

from quantforge.core.constants import Direction, EventType, OrderStatus
from quantforge.core.datatypes import (
    AccountData,
    BarData,
    Event,
    OrderData,
    PositionData,
    TradeData,
)
from quantforge.execution.gateway.base import Gateway

if TYPE_CHECKING:
    from quantforge.core.event import EventEngine
    from quantforge.strategy.context import StrategyContext


class SimGateway(Gateway):
    """Simulated gateway that fills orders against bar data.

    Features:
    - Commission: configurable rate with minimum
    - Stamp tax: sell-only (A-share rule)
    - Slippage: configurable ticks
    - T+1 settlement: tracks frozen shares
    """

    name = "sim"

    def __init__(
        self,
        event_engine: EventEngine,
        commission_rate: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax_rate: float = 0.001,
        slippage_pct: float = 0.001,
        t_plus_1: bool = True,
    ):
        self._event_engine = event_engine
        self._commission_rate = commission_rate
        self._min_commission = min_commission
        self._stamp_tax_rate = stamp_tax_rate
        self._slippage_pct = slippage_pct
        self._t_plus_1 = t_plus_1

        # Pending orders waiting for next bar to fill
        self._pending_orders: list[OrderData] = []
        # Context reference for position/account updates
        self._contexts: dict[str, StrategyContext] = {}
        # Track today's date for T+1
        self._current_date = None

    def register_context(self, ctx: StrategyContext) -> None:
        """Register a strategy context for position/account updates."""
        self._contexts[ctx.strategy_name] = ctx

    async def send_order(self, order: OrderData) -> str:
        """Queue order for fill on next bar."""
        order.status = OrderStatus.SUBMITTED
        self._pending_orders.append(order)
        return order.order_id

    async def cancel_order(self, order_id: str) -> None:
        """Cancel a pending order."""
        self._pending_orders = [
            o for o in self._pending_orders if o.order_id != order_id
        ]

    async def on_bar(self, bar: BarData) -> None:
        """Called by backtest engine on each bar. Attempts to fill pending orders."""
        # Update date and unfreeze T+1 positions
        bar_date = bar.datetime.date()
        if self._current_date != bar_date:
            self._unfreeze_positions(bar_date)
            self._current_date = bar_date

        # Try to fill each pending order
        filled = []
        for order in self._pending_orders:
            if order.symbol != bar.symbol:
                continue
            await self._try_fill(order, bar)
            filled.append(order)

        for order in filled:
            self._pending_orders.remove(order)

    async def _try_fill(self, order: OrderData, bar: BarData) -> None:
        """Attempt to fill an order using bar's open price + slippage."""
        ctx = self._contexts.get(order.strategy_name)
        if ctx is None:
            return

        # Use open price with slippage
        if order.direction == Direction.LONG:
            fill_price = bar.open * (1 + self._slippage_pct)
        else:
            fill_price = bar.open * (1 - self._slippage_pct)

        # T+1 check: cannot sell shares bought today
        if order.direction == Direction.SHORT and self._t_plus_1:
            pos = ctx.get_position(order.symbol)
            if pos:
                available = pos.volume - pos.frozen
                if order.volume > available:
                    order.status = OrderStatus.REJECTED
                    logger.warning(
                        f"T+1 rejection: {order.symbol} sell {order.volume} "
                        f"but only {available} available (frozen={pos.frozen})"
                    )
                    await self._publish_order(order)
                    return

        # Calculate costs
        turnover = fill_price * order.volume
        commission = max(turnover * self._commission_rate, self._min_commission)

        # Stamp tax on sells only
        stamp_tax = 0.0
        if order.direction == Direction.SHORT:
            stamp_tax = turnover * self._stamp_tax_rate

        total_cost = commission + stamp_tax

        # Check sufficient funds for buy
        if order.direction == Direction.LONG:
            account = ctx.get_account()
            if account.available < turnover + total_cost:
                order.status = OrderStatus.REJECTED
                logger.warning(
                    f"Insufficient funds: need {turnover + total_cost:.2f}, "
                    f"available {account.available:.2f}"
                )
                await self._publish_order(order)
                return

        # Fill the order
        order.filled = order.volume
        order.status = OrderStatus.FILLED

        trade = TradeData(
            trade_id=str(uuid.uuid4())[:8],
            order_id=order.order_id,
            symbol=order.symbol,
            exchange=order.exchange,
            direction=order.direction,
            price=fill_price,
            volume=order.volume,
            commission=total_cost,
            slippage=abs(fill_price - bar.open) * order.volume,
            datetime=bar.datetime,
        )

        # Update position
        self._update_position(ctx, trade, bar)
        # Update account
        self._update_account(ctx, trade)

        # Record in context
        ctx.update_order(order)
        ctx.record_trade(trade)

        # Publish events
        await self._publish_order(order)
        await self._publish_trade(trade)

    def _update_position(
        self, ctx: StrategyContext, trade: TradeData, bar: BarData
    ) -> None:
        """Update position after a trade."""
        pos = ctx.get_position(trade.symbol)
        if pos is None:
            pos = PositionData(
                symbol=trade.symbol,
                exchange=trade.exchange,
            )

        if trade.direction == Direction.LONG:
            # Buying: increase position
            total_cost = pos.avg_price * pos.volume + trade.price * trade.volume
            pos.volume += trade.volume
            pos.avg_price = total_cost / pos.volume if pos.volume > 0 else 0
            # T+1: newly bought shares are frozen
            if self._t_plus_1:
                pos.frozen += trade.volume
        else:
            # Selling: decrease position
            pos.realized_pnl += (trade.price - pos.avg_price) * trade.volume
            pos.volume -= trade.volume
            if pos.volume <= 0:
                pos.volume = 0
                pos.avg_price = 0
                pos.frozen = 0

        # Update unrealized P&L
        if pos.volume > 0:
            pos.unrealized_pnl = (bar.close - pos.avg_price) * pos.volume

        ctx.update_position(pos)

    def _update_account(self, ctx: StrategyContext, trade: TradeData) -> None:
        """Update account balance after a trade."""
        account = ctx.get_account()

        if trade.direction == Direction.LONG:
            cost = trade.price * trade.volume + trade.commission
            account.available -= cost
            account.frozen += trade.price * trade.volume
        else:
            proceeds = trade.price * trade.volume - trade.commission
            account.available += proceeds
            # Unfreeze the position value that was sold
            account.frozen -= trade.price * trade.volume
            if account.frozen < 0:
                account.frozen = 0

        account.realized_pnl += (
            (trade.price - ctx.get_position(trade.symbol).avg_price) * trade.volume
            if trade.direction == Direction.SHORT
            else 0
        )

        # Update total balance = available + frozen + unrealized
        total_unrealized = sum(
            p.unrealized_pnl for p in ctx.get_all_positions()
        )
        account.unrealized_pnl = total_unrealized
        account.balance = account.available + account.frozen + total_unrealized

        ctx.update_account(account)

    def _unfreeze_positions(self, new_date) -> None:
        """Unfreeze T+1 frozen shares when date changes."""
        for ctx in self._contexts.values():
            for pos in ctx.get_all_positions():
                if pos.frozen > 0:
                    pos.frozen = 0
                    ctx.update_position(pos)

    async def _publish_order(self, order: OrderData) -> None:
        event = Event(type=EventType.ORDER, data=order)
        await self._event_engine.publish(event)

    async def _publish_trade(self, trade: TradeData) -> None:
        event = Event(type=EventType.TRADE, data=trade)
        await self._event_engine.publish(event)
