"""SignalBus — signal-execution separation (the "clutch" mechanism).

Inspired by WonderTrader's design: strategy signals are decoupled from
actual order execution. The clutch can be engaged (live/paper) or
disengaged (log-only / pause mode) without changing strategy code.

This enables:
- Switching between backtest / paper / live mode transparently
- Pausing execution while keeping signal generation running
- Fan-out: one strategy's signals → multiple accounts (M+N model)
- Signal replay for debugging
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable, Coroutine, Any

from loguru import logger

from quantforge.core.datatypes import OrderData, SignalData


class ClutchState(StrEnum):
    """Whether signals are routed to actual execution."""
    ENGAGED = "engaged"       # signals → execution pipeline
    DISENGAGED = "disengaged" # signals logged only (dry-run / paused)


@dataclass
class SignalRecord:
    """Immutable record of a signal for logging and replay."""
    signal: SignalData
    timestamp: _dt.datetime = field(default_factory=_dt.datetime.now)
    routed: bool = False
    note: str = ""


# Type alias for order submission callback
OrderSubmitFn = Callable[[OrderData], Coroutine[Any, Any, str]]


class SignalBus:
    """Routes strategy signals to execution (or logs them only).

    Usage:
        bus = SignalBus()
        bus.engage()  # signals will be executed
        bus.set_order_fn(ctx.buy)

        # Strategy emits a signal:
        await bus.emit(signal)
    """

    def __init__(self, state: ClutchState = ClutchState.ENGAGED):
        self._state = state
        self._order_fns: dict[str, OrderSubmitFn] = {}  # direction → submit fn
        self._signal_log: list[SignalRecord] = []

    # ── Clutch control ────────────────────────────────────────────────

    def engage(self) -> None:
        """Connect signals to execution pipeline."""
        self._state = ClutchState.ENGAGED
        logger.info("SignalBus: clutch ENGAGED — signals will execute")

    def disengage(self) -> None:
        """Disconnect signals from execution (dry-run mode)."""
        self._state = ClutchState.DISENGAGED
        logger.info("SignalBus: clutch DISENGAGED — signals logged only")

    @property
    def is_engaged(self) -> bool:
        return self._state == ClutchState.ENGAGED

    @property
    def state(self) -> ClutchState:
        return self._state

    # ── Registration ─────────────────────────────────────────────────

    def register_buy_fn(self, fn: OrderSubmitFn) -> None:
        """Register the coroutine to call when routing a BUY signal."""
        self._order_fns["buy"] = fn

    def register_sell_fn(self, fn: OrderSubmitFn) -> None:
        """Register the coroutine to call when routing a SELL signal."""
        self._order_fns["sell"] = fn

    # ── Signal emission ──────────────────────────────────────────────

    async def emit(self, signal: SignalData) -> str | None:
        """Emit a signal. Routes to execution if clutch is engaged.

        Returns order_id if routed, None if logged-only.
        """
        record = SignalRecord(signal=signal)
        self._signal_log.append(record)

        if not self.is_engaged:
            record.note = "disengaged"
            logger.debug(
                f"SignalBus [DISENGAGED] {signal.strategy_name} | "
                f"{signal.direction.upper()} {signal.symbol} x{signal.volume} @ {signal.price:.2f}"
            )
            return None

        from quantforge.core.constants import Direction
        fn_key = "buy" if signal.direction == Direction.LONG else "sell"
        fn = self._order_fns.get(fn_key)
        if fn is None:
            logger.warning(f"SignalBus: no {fn_key} function registered")
            return None

        order_id = await fn(
            signal.symbol,
            signal.volume,
            signal.price,
            signal.exchange,
            signal.order_type,
        )
        record.routed = True
        record.note = f"order_id={order_id}"
        logger.debug(
            f"SignalBus [ENGAGED] routed → order {order_id} | "
            f"{signal.direction.upper()} {signal.symbol} x{signal.volume} @ {signal.price:.2f}"
        )
        return order_id

    # ── Inspection ───────────────────────────────────────────────────

    @property
    def signal_log(self) -> list[SignalRecord]:
        return list(self._signal_log)

    def clear_log(self) -> None:
        self._signal_log.clear()
