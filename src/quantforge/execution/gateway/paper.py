"""Paper trading gateway — simulates live trading with real-time price quotes.

Unlike SimGateway (which fills on next bar open), PaperGateway:
- Accepts market orders and fills immediately at current quote + slippage
- Persists positions/account state to JSON for cross-session continuity
- Tracks P&L against real quotes polled via AKShare
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from quantforge.core.constants import Direction, EventType, OrderStatus, OrderType
from quantforge.core.datatypes import (
    AccountData,
    Event,
    OrderData,
    PositionData,
    TradeData,
)
from quantforge.execution.gateway.base import Gateway

if TYPE_CHECKING:
    from quantforge.core.event import EventEngine
    from quantforge.strategy.context import StrategyContext


_STATE_PATH = Path("data/paper_state.json")


class PaperGateway(Gateway):
    """Paper trading gateway with persistent state and real-time quote updates.

    Features:
    - Immediate market-order fills at latest quote + slippage
    - Limit order queue: fills when quote crosses limit price
    - Commission and stamp-tax same as SimGateway
    - T+1: newly-bought shares frozen until next trading day
    - State persistence: positions/account saved to JSON
    """

    name = "paper"

    def __init__(
        self,
        event_engine: EventEngine,
        commission_rate: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax_rate: float = 0.001,
        slippage_pct: float = 0.001,
        t_plus_1: bool = True,
        state_path: Path = _STATE_PATH,
    ):
        self._event_engine = event_engine
        self._commission_rate = commission_rate
        self._min_commission = min_commission
        self._stamp_tax_rate = stamp_tax_rate
        self._slippage_pct = slippage_pct
        self._t_plus_1 = t_plus_1
        self._state_path = state_path

        # Latest quotes: symbol → price
        self._quotes: dict[str, float] = {}
        # Pending limit orders
        self._pending_orders: list[OrderData] = []
        # Context registry
        self._contexts: dict[str, StrategyContext] = {}
        # Current trading date (YYYY-MM-DD string)
        self._current_date: str = ""

        self._load_state()

    # ── Lifecycle ────────────────────────────────────────────────────

    def register_context(self, ctx: StrategyContext) -> None:
        self._contexts[ctx.strategy_name] = ctx
        # Restore persisted positions/account into context
        self._restore_context(ctx)

    def _load_state(self) -> None:
        """Load persisted state from JSON."""
        if not self._state_path.exists():
            self._state = {}
            return
        try:
            with open(self._state_path) as f:
                self._state = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load paper state: {e}")
            self._state = {}

    def _save_state(self) -> None:
        """Persist current state to JSON."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {}
        for name, ctx in self._contexts.items():
            acc = ctx.get_account()
            snapshot[name] = {
                "account": {
                    "balance": acc.balance,
                    "available": acc.available,
                    "frozen": acc.frozen,
                    "realized_pnl": acc.realized_pnl,
                },
                "positions": [
                    {
                        "symbol": p.symbol,
                        "exchange": p.exchange.value,
                        "volume": p.volume,
                        "avg_price": p.avg_price,
                        "frozen": p.frozen,
                        "realized_pnl": p.realized_pnl,
                    }
                    for p in ctx.get_all_positions()
                    if p.volume > 0
                ],
                "current_date": self._current_date,
            }
        with open(self._state_path, "w") as f:
            json.dump(snapshot, f, indent=2)

    def _restore_context(self, ctx: StrategyContext) -> None:
        """Restore persisted positions/account into a newly registered context."""
        saved = self._state.get(ctx.strategy_name)
        if not saved:
            return
        acc_data = saved.get("account", {})
        account = ctx.get_account()
        account.balance = acc_data.get("balance", account.balance)
        account.available = acc_data.get("available", account.available)
        account.frozen = acc_data.get("frozen", 0.0)
        account.realized_pnl = acc_data.get("realized_pnl", 0.0)
        ctx.update_account(account)

        from quantforge.core.constants import Exchange

        for p_data in saved.get("positions", []):
            try:
                exc = Exchange(p_data["exchange"])
            except ValueError:
                exc = Exchange.SZSE
            pos = PositionData(
                symbol=p_data["symbol"],
                exchange=exc,
                volume=p_data.get("volume", 0),
                avg_price=p_data.get("avg_price", 0.0),
                frozen=p_data.get("frozen", 0),
                realized_pnl=p_data.get("realized_pnl", 0.0),
            )
            ctx.update_position(pos)

        self._current_date = saved.get("current_date", "")
        logger.info(f"Restored paper state for {ctx.strategy_name}: "
                    f"balance={account.balance:.2f}, "
                    f"positions={len(ctx.get_all_positions())}")

    # ── Quote Updates ────────────────────────────────────────────────

    async def update_quote(self, symbol: str, price: float, date_str: str = "") -> None:
        """Called by the real-time data module with latest price.

        Also triggers pending limit order checks and T+1 date rollover.
        """
        self._quotes[symbol] = price

        # Date rollover → unfreeze T+1 positions
        if date_str and date_str != self._current_date:
            self._unfreeze_positions()
            self._current_date = date_str
            self._save_state()

        # Check if any pending limit orders can now fill
        await self._check_limit_orders(symbol, price)

    async def _check_limit_orders(self, symbol: str, price: float) -> None:
        """Fill pending limit orders whose price condition is met."""
        to_fill = []
        for order in self._pending_orders:
            if order.symbol != symbol:
                continue
            if order.order_type == OrderType.MARKET:
                to_fill.append(order)
            elif order.order_type == OrderType.LIMIT:
                if order.direction == Direction.LONG and price <= order.price:
                    to_fill.append(order)
                elif order.direction == Direction.SHORT and price >= order.price:
                    to_fill.append(order)

        for order in to_fill:
            self._pending_orders.remove(order)
            await self._fill_order(order, price)

    # ── Gateway Interface ────────────────────────────────────────────

    async def send_order(self, order: OrderData) -> str:
        """Accept an order.  Market orders fill immediately; limits are queued."""
        order.status = OrderStatus.SUBMITTED

        quote = self._quotes.get(order.symbol)
        if order.order_type == OrderType.MARKET and quote is not None:
            await self._fill_order(order, quote)
        else:
            self._pending_orders.append(order)
            logger.debug(f"Paper: queued {order.order_type} order {order.order_id} "
                         f"for {order.symbol} @ {order.price}")
        return order.order_id

    async def cancel_order(self, order_id: str) -> None:
        self._pending_orders = [
            o for o in self._pending_orders if o.order_id != order_id
        ]

    # ── Fill Logic ───────────────────────────────────────────────────

    async def _fill_order(self, order: OrderData, market_price: float) -> None:
        ctx = self._contexts.get(order.strategy_name)
        if ctx is None:
            logger.warning(f"No context for strategy {order.strategy_name}")
            return

        # Apply slippage
        if order.direction == Direction.LONG:
            fill_price = market_price * (1 + self._slippage_pct)
        else:
            fill_price = market_price * (1 - self._slippage_pct)

        # T+1 sell check
        if order.direction == Direction.SHORT and self._t_plus_1:
            pos = ctx.get_position(order.symbol)
            if pos:
                available = pos.volume - pos.frozen
                if order.volume > available:
                    order.status = OrderStatus.REJECTED
                    logger.warning(
                        f"T+1 rejection: {order.symbol} sell {order.volume} "
                        f"but only {available} available"
                    )
                    await self._publish_order(order)
                    return

        # Cost calculation
        turnover = fill_price * order.volume
        commission = max(turnover * self._commission_rate, self._min_commission)
        stamp_tax = turnover * self._stamp_tax_rate if order.direction == Direction.SHORT else 0.0
        total_cost = commission + stamp_tax

        # Funds check
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

        # Execute fill
        order.filled = order.volume
        order.status = OrderStatus.FILLED

        import datetime as _dt
        trade = TradeData(
            trade_id=str(uuid.uuid4())[:8],
            order_id=order.order_id,
            symbol=order.symbol,
            exchange=order.exchange,
            direction=order.direction,
            price=fill_price,
            volume=order.volume,
            commission=total_cost,
            slippage=abs(fill_price - market_price) * order.volume,
            datetime=_dt.datetime.now(),
        )

        self._update_position(ctx, trade, fill_price)
        self._update_account(ctx, trade)
        ctx.update_order(order)
        ctx.record_trade(trade)

        await self._publish_order(order)
        await self._publish_trade(trade)

        # Persist after every trade
        self._save_state()

        logger.info(
            f"Paper FILL {order.direction.value} {order.volume} {order.symbol} "
            f"@ {fill_price:.3f}  commission={total_cost:.2f}"
        )

    def _update_position(self, ctx: StrategyContext, trade: TradeData, current_price: float) -> None:
        pos = ctx.get_position(trade.symbol)
        if pos is None:
            pos = PositionData(symbol=trade.symbol, exchange=trade.exchange)

        if trade.direction == Direction.LONG:
            total_cost = pos.avg_price * pos.volume + trade.price * trade.volume
            pos.volume += trade.volume
            pos.avg_price = total_cost / pos.volume if pos.volume > 0 else 0
            if self._t_plus_1:
                pos.frozen += trade.volume
        else:
            pos.realized_pnl += (trade.price - pos.avg_price) * trade.volume
            pos.volume -= trade.volume
            if pos.volume <= 0:
                pos.volume = 0
                pos.avg_price = 0
                pos.frozen = 0

        if pos.volume > 0:
            pos.unrealized_pnl = (current_price - pos.avg_price) * pos.volume

        ctx.update_position(pos)

    def _update_account(self, ctx: StrategyContext, trade: TradeData) -> None:
        account = ctx.get_account()
        if trade.direction == Direction.LONG:
            cost = trade.price * trade.volume + trade.commission
            account.available -= cost
            account.frozen += trade.price * trade.volume
        else:
            proceeds = trade.price * trade.volume - trade.commission
            account.available += proceeds
            account.frozen -= trade.price * trade.volume
            if account.frozen < 0:
                account.frozen = 0

        total_unrealized = sum(p.unrealized_pnl for p in ctx.get_all_positions())
        account.unrealized_pnl = total_unrealized
        account.balance = account.available + account.frozen + total_unrealized
        ctx.update_account(account)

    def _unfreeze_positions(self) -> None:
        for ctx in self._contexts.values():
            for pos in ctx.get_all_positions():
                if pos.frozen > 0:
                    pos.frozen = 0
                    ctx.update_position(pos)

    # ── Mark to Market ────────────────────────────────────────────────

    def mark_to_market(self) -> None:
        """Update unrealized P&L for all positions using latest quotes."""
        for ctx in self._contexts.values():
            account = ctx.get_account()
            for pos in ctx.get_all_positions():
                quote = self._quotes.get(pos.symbol)
                if quote and pos.volume > 0:
                    pos.unrealized_pnl = (quote - pos.avg_price) * pos.volume
                    ctx.update_position(pos)
            total_unrealized = sum(p.unrealized_pnl for p in ctx.get_all_positions())
            account.unrealized_pnl = total_unrealized
            account.balance = account.available + account.frozen + total_unrealized
            ctx.update_account(account)

    # ── Event Publishing ──────────────────────────────────────────────

    async def _publish_order(self, order: OrderData) -> None:
        await self._event_engine.publish(Event(type=EventType.ORDER, data=order))

    async def _publish_trade(self, trade: TradeData) -> None:
        await self._event_engine.publish(Event(type=EventType.TRADE, data=trade))
