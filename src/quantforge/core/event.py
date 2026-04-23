"""Async event engine — the backbone of QuantForge.

All modules communicate through publish/subscribe on typed events.
"""

import asyncio
from collections import defaultdict
from typing import Any, Callable, Coroutine

from loguru import logger

from quantforge.core.constants import EventType
from quantforge.core.datatypes import Event

HandlerType = Callable[[Event], Coroutine[Any, Any, None]]


class EventEngine:
    """Asynchronous event bus using asyncio.Queue."""

    def __init__(self):
        self._handlers: dict[EventType, list[HandlerType]] = defaultdict(list)
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._active: bool = False
        self._task: asyncio.Task | None = None

    def register(self, event_type: EventType, handler: HandlerType) -> None:
        """Register a handler for an event type."""
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)

    def unregister(self, event_type: EventType, handler: HandlerType) -> None:
        """Remove a handler."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, event: Event) -> None:
        """Publish an event to the bus."""
        await self._queue.put(event)

    def publish_sync(self, event: Event) -> None:
        """Non-async publish for use in synchronous code paths (e.g. backtest)."""
        self._queue.put_nowait(event)

    async def _dispatch_loop(self) -> None:
        """Main dispatch loop — processes events from queue."""
        while self._active:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            handlers = self._handlers.get(event.type, [])
            for handler in handlers:
                try:
                    await handler(event)
                except Exception:
                    logger.exception(
                        f"Error in handler {handler.__qualname__} for {event.type}"
                    )

    async def start(self) -> None:
        """Start the event dispatch loop."""
        if self._active:
            return
        self._active = True
        self._task = asyncio.create_task(self._dispatch_loop())
        logger.info("EventEngine started")

    async def stop(self) -> None:
        """Stop the event dispatch loop and drain remaining events."""
        self._active = False
        if self._task:
            await self._task
            self._task = None
        logger.info("EventEngine stopped")

    async def process_one(self) -> bool:
        """Process a single event from the queue. Returns False if queue is empty.

        Used by BacktestEngine for synchronous step-through.
        """
        try:
            event = self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return False

        handlers = self._handlers.get(event.type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    f"Error in handler {handler.__qualname__} for {event.type}"
                )
        return True
