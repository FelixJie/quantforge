"""Portfolio manager — orchestrates multiple strategies running in paper mode.

Responsibilities:
- Start / stop individual paper-trading strategy sessions
- Aggregate P&L and positions across all running strategies
- Wire RealtimeDataStream → PaperGateway quote callbacks
- Expose a clean summary for the REST API
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import importlib
from typing import TYPE_CHECKING

from loguru import logger

from quantforge.core.constants import Exchange
from quantforge.core.event import EventEngine
from quantforge.data.realtime import RealtimeDataStream
from quantforge.execution.gateway.paper import PaperGateway
from quantforge.strategy.context import StrategyContext

if TYPE_CHECKING:
    from quantforge.strategy.base import Strategy


class StrategySession:
    """Represents one live strategy running against PaperGateway."""

    def __init__(
        self,
        session_id: str,
        strategy_name: str,
        strategy_module_path: str,
        strategy_params: dict,
        strategy: Strategy,
        context: StrategyContext,
        gateway: PaperGateway,
        symbols: list[str],
        exchange: Exchange,
        started_at: _dt.datetime,
    ):
        self.session_id = session_id
        self.strategy_name = strategy_name
        self.strategy_module_path = strategy_module_path
        self.strategy_params = strategy_params
        self.strategy = strategy
        self.context = context
        self.gateway = gateway
        self.symbols = symbols
        self.exchange = exchange
        self.started_at = started_at
        self.status: str = "running"
        self.error: str | None = None

    def summary(self) -> dict:
        acc = self.context.get_account()
        positions = [
            {
                "symbol": p.symbol,
                "volume": p.volume,
                "avg_price": round(p.avg_price, 3),
                "unrealized_pnl": round(p.unrealized_pnl, 2),
                "realized_pnl": round(p.realized_pnl, 2),
                "frozen": p.frozen,
            }
            for p in self.context.get_all_positions()
            if p.volume > 0
        ]
        initial = acc.balance - acc.unrealized_pnl - acc.realized_pnl
        if initial <= 0:
            initial = acc.balance
        return {
            "session_id": self.session_id,
            "strategy_name": self.strategy_name,
            "symbols": self.symbols,
            "exchange": self.exchange.value,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "error": self.error,
            "account": {
                "balance": round(acc.balance, 2),
                "available": round(acc.available, 2),
                "frozen": round(acc.frozen, 2),
                "unrealized_pnl": round(acc.unrealized_pnl, 2),
                "realized_pnl": round(acc.realized_pnl, 2),
            },
            "positions": positions,
        }


    def detail(self) -> dict:
        """Full session detail including trades, orders, and strategy logs."""
        trades = [
            {
                "trade_id": t.trade_id,
                "order_id": t.order_id,
                "symbol": t.symbol,
                "direction": t.direction.value,
                "price": round(t.price, 3),
                "volume": t.volume,
                "commission": round(t.commission, 2),
                "datetime": t.datetime.isoformat() if t.datetime else None,
            }
            for t in self.context._trades
        ]
        orders = [
            {
                "order_id": o.order_id,
                "symbol": o.symbol,
                "direction": o.direction.value,
                "price": round(o.price, 3),
                "volume": o.volume,
                "filled": o.filled,
                "status": o.status.value,
                "datetime": o.datetime.isoformat() if o.datetime else None,
            }
            for o in self.context._orders.values()
        ]
        return {
            **self.summary(),
            "trades": trades,
            "orders": orders,
            "logs": list(self.context._logs),
        }


class PortfolioManager:
    """Manages the lifecycle of all live paper-trading sessions.

    One shared RealtimeDataStream polls quotes for all subscribed symbols.
    Each session gets its own EventEngine + PaperGateway + StrategyContext.
    """

    def __init__(self, poll_interval: float = 5.0):
        self._sessions: dict[str, StrategySession] = {}
        self._poll_interval = poll_interval

        # Shared realtime stream (started lazily when first session is created)
        self._rt_stream: RealtimeDataStream | None = None
        self._rt_event_engine: EventEngine | None = None

    # ── Session management ────────────────────────────────────────────

    async def start_session(
        self,
        session_id: str,
        strategy_module_path: str,
        symbols: list[str],
        exchange: Exchange,
        initial_capital: float,
        strategy_params: dict | None = None,
    ) -> StrategySession:
        """Create and start a new paper-trading session."""
        if session_id in self._sessions:
            raise ValueError(f"Session {session_id} already exists")

        # Load strategy class dynamically
        strategy_cls = self._import_strategy(strategy_module_path)

        # Create isolated event engine for this session
        event_engine = EventEngine()

        # Create gateway
        gateway = PaperGateway(
            event_engine=event_engine,
            t_plus_1=True,
        )

        # Create context
        ctx = StrategyContext(
            strategy_name=session_id,
            event_engine=event_engine,
            initial_capital=initial_capital,
        )
        gateway.register_context(ctx)

        # Instantiate strategy
        params = strategy_params or {}
        if symbols:
            params.setdefault("symbol", symbols[0])
            params.setdefault("exchange", exchange.value)
        strategy = strategy_cls(ctx=ctx, params=params)
        await strategy.on_init()

        session = StrategySession(
            session_id=session_id,
            strategy_name=strategy_module_path.split(".")[-1],
            strategy_module_path=strategy_module_path,
            strategy_params=strategy_params or {},
            strategy=strategy,
            context=ctx,
            gateway=gateway,
            symbols=symbols,
            exchange=exchange,
            started_at=_dt.datetime.now(),
        )
        self._sessions[session_id] = session

        # Ensure real-time stream is running and register callbacks
        await self._ensure_stream(event_engine)
        for sym in symbols:
            self._rt_stream.subscribe(sym, exchange)
            self._rt_stream.register_callback(sym, gateway.update_quote)

        logger.info(
            f"Paper session started: {session_id} "
            f"strategy={strategy_module_path} symbols={symbols}"
        )
        return session

    def stop_session(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session and session.status == "running":
            session.status = "stopped"
            # Unregister gateway callbacks so quotes stop triggering on_bar
            if self._rt_stream:
                for sym in session.symbols:
                    self._rt_stream.unregister_callback(sym, session.gateway.update_quote)
            logger.info(f"Paper session stopped: {session_id}")

    async def resume_session(self, session_id: str) -> StrategySession:
        """Resume a previously stopped session, preserving existing context (positions, trades, logs)."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        if session.status == "running":
            return session

        session.status = "running"
        # Re-register gateway callbacks so quotes resume triggering on_bar
        await self._ensure_stream(session.context._event_engine)
        for sym in session.symbols:
            self._rt_stream.subscribe(sym, session.exchange)
            self._rt_stream.register_callback(sym, session.gateway.update_quote)
        session.context.log("策略已恢复运行")
        logger.info(f"Paper session resumed: {session_id}")
        return session

    def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def get_session(self, session_id: str) -> StrategySession | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        return [s.summary() for s in self._sessions.values()]

    # ── Aggregate portfolio view ──────────────────────────────────────

    def aggregate_summary(self) -> dict:
        """Aggregate P&L across all running sessions."""
        sessions = list(self._sessions.values())
        total_balance = sum(s.context.get_account().balance for s in sessions)
        total_unrealized = sum(s.context.get_account().unrealized_pnl for s in sessions)
        total_realized = sum(s.context.get_account().realized_pnl for s in sessions)

        all_positions: dict[str, dict] = {}
        for session in sessions:
            for pos in session.context.get_all_positions():
                if pos.volume <= 0:
                    continue
                key = f"{pos.symbol}.{session.session_id}"
                all_positions[key] = {
                    "symbol": pos.symbol,
                    "session": session.session_id,
                    "volume": pos.volume,
                    "avg_price": round(pos.avg_price, 3),
                    "unrealized_pnl": round(pos.unrealized_pnl, 2),
                }

        return {
            "session_count": len(sessions),
            "running_count": sum(1 for s in sessions if s.status == "running"),
            "total_balance": round(total_balance, 2),
            "total_unrealized_pnl": round(total_unrealized, 2),
            "total_realized_pnl": round(total_realized, 2),
            "positions": list(all_positions.values()),
            "latest_quotes": self._rt_stream.get_all_quotes() if self._rt_stream else {},
        }

    # ── Internal helpers ──────────────────────────────────────────────

    async def _ensure_stream(self, event_engine: EventEngine) -> None:
        """Start the shared real-time stream if not already running."""
        if self._rt_stream is None:
            self._rt_event_engine = event_engine
            self._rt_stream = RealtimeDataStream(
                event_engine, poll_interval=self._poll_interval
            )
            self._rt_stream.start()

    @staticmethod
    def _import_strategy(module_path: str):
        """Dynamically import a strategy class from dotted module path."""
        parts = module_path.rsplit(".", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid module path: {module_path}")
        module_name, class_name = parts
        try:
            mod = importlib.import_module(module_name)
            return getattr(mod, class_name)
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Cannot load strategy {module_path}: {e}") from e

    def shutdown(self) -> None:
        """Stop all sessions and the real-time stream."""
        for session in self._sessions.values():
            session.status = "stopped"
        if self._rt_stream:
            self._rt_stream.stop()
        logger.info("PortfolioManager shutdown complete")
