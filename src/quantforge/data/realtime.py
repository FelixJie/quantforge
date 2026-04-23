"""Real-time market data streaming via AKShare polling.

Since A-share exchanges do not expose WebSocket feeds publicly,
this module polls AKShare at configurable intervals and pushes
TickData events into the EventEngine.

Usage:
    rt = RealtimeDataStream(event_engine)
    rt.subscribe("000001", Exchange.SZSE)
    asyncio.create_task(rt.run(interval_seconds=5))
"""

from __future__ import annotations

import asyncio
import datetime as _dt
from typing import TYPE_CHECKING, Callable

from loguru import logger

from quantforge.core.constants import EventType, Exchange
from quantforge.core.datatypes import Event, TickData

if TYPE_CHECKING:
    from quantforge.core.event import EventEngine


QuoteCallback = Callable[[str, float, str], None]


class RealtimeDataStream:
    """Polls AKShare for real-time A-share spot quotes.

    Emits TickData events via EventEngine and optionally calls registered
    quote callbacks (used by PaperGateway to trigger limit-order checks).
    """

    def __init__(self, event_engine: EventEngine, poll_interval: float = 5.0):
        self._event_engine = event_engine
        self._poll_interval = poll_interval

        # symbol → exchange mapping for subscribed symbols
        self._subscriptions: dict[str, Exchange] = {}
        # quote callbacks: symbol → list of async callbacks(symbol, price, date_str)
        self._callbacks: dict[str, list[QuoteCallback]] = {}

        self._running = False
        self._task: asyncio.Task | None = None

        # Latest quotes cache: symbol → (price, datetime)
        self._latest: dict[str, tuple[float, _dt.datetime]] = {}

    # ── Subscription management ───────────────────────────────────────

    def subscribe(self, symbol: str, exchange: Exchange = Exchange.SZSE) -> None:
        """Add a symbol to the polling list."""
        self._subscriptions[symbol] = exchange
        logger.info(f"Realtime: subscribed {symbol}.{exchange.value}")

    def unsubscribe(self, symbol: str) -> None:
        self._subscriptions.pop(symbol, None)
        self._callbacks.pop(symbol, None)

    def register_callback(self, symbol: str, callback: QuoteCallback) -> None:
        """Register an async callback for quote updates on a symbol."""
        self._callbacks.setdefault(symbol, []).append(callback)

    def unregister_callback(self, symbol: str, callback: QuoteCallback) -> None:
        """Remove a previously registered callback."""
        cbs = self._callbacks.get(symbol, [])
        try:
            cbs.remove(callback)
        except ValueError:
            pass

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Schedule the polling coroutine as an asyncio task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(f"Realtime data stream started (interval={self._poll_interval}s)")

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Realtime data stream stopped")

    # ── Polling loop ──────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while self._running:
            if self._subscriptions:
                await self._fetch_quotes()
            await asyncio.sleep(self._poll_interval)

    async def _fetch_quotes(self) -> None:
        """Fetch spot quotes for all subscribed symbols."""
        # Run the blocking AKShare call in a thread pool executor
        loop = asyncio.get_event_loop()
        try:
            quotes = await loop.run_in_executor(None, self._fetch_akshare_quotes)
        except Exception as e:
            logger.warning(f"Quote fetch failed: {e}")
            return

        now = _dt.datetime.now()
        for symbol, price in quotes.items():
            exchange = self._subscriptions.get(symbol, Exchange.SZSE)
            date_str = now.strftime("%Y-%m-%d")

            # Update cache
            self._latest[symbol] = (price, now)

            # Publish TickData event
            tick = TickData(
                symbol=symbol,
                exchange=exchange,
                datetime=now,
                last_price=price,
                volume=0.0,
            )
            event = Event(type=EventType.TICK, data=tick)
            await self._event_engine.publish(event)

            # Call registered callbacks (e.g., PaperGateway.update_quote)
            for cb in self._callbacks.get(symbol, []):
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(symbol, price, date_str)
                    else:
                        cb(symbol, price, date_str)
                except Exception as e:
                    logger.warning(f"Quote callback error for {symbol}: {e}")

    def _fetch_akshare_quotes(self) -> dict[str, float]:
        """Blocking call to AKShare for current spot prices.

        Returns dict of {symbol: last_price}.
        Falls back to synthetic prices if AKShare is unavailable.
        """
        try:
            import akshare as ak
            symbols = list(self._subscriptions.keys())
            result = {}

            # AKShare: stock_zh_a_spot_em returns a DataFrame with all A-share spots
            # We filter to the symbols we care about
            df = ak.stock_zh_a_spot_em()
            # Column layout: 代码, 名称, 最新价, ...
            df = df[df["代码"].isin(symbols)]
            for _, row in df.iterrows():
                price = float(row.get("最新价", 0) or 0)
                if price > 0:
                    result[row["代码"]] = price

            # For subscribed symbols with no result, keep last known price
            for sym in symbols:
                if sym not in result and sym in self._latest:
                    result[sym] = self._latest[sym][0]

            return result

        except Exception as e:
            logger.debug(f"AKShare spot fetch failed ({e}), using synthetic prices")
            return self._synthetic_quotes()

    def _synthetic_quotes(self) -> dict[str, float]:
        """Generate plausible synthetic prices for testing when AKShare is unavailable."""
        import random

        result = {}
        for symbol in self._subscriptions:
            last = self._latest.get(symbol)
            if last:
                # Random walk: ±0.3%
                drift = random.uniform(-0.003, 0.003)
                result[symbol] = round(last[0] * (1 + drift), 3)
            else:
                # Seed price based on symbol hash
                seed = sum(ord(c) for c in symbol) % 1000 + 5
                result[symbol] = float(seed)
        return result

    # ── Query API ─────────────────────────────────────────────────────

    def get_latest(self, symbol: str) -> float | None:
        """Return the most recent cached price for a symbol."""
        entry = self._latest.get(symbol)
        return entry[0] if entry else None

    def get_all_quotes(self) -> dict[str, dict]:
        """Return all cached quotes as a dict for API serialization."""
        result = {}
        for symbol, (price, ts) in self._latest.items():
            result[symbol] = {
                "symbol": symbol,
                "price": price,
                "exchange": self._subscriptions.get(symbol, Exchange.SZSE).value,
                "timestamp": ts.isoformat(),
            }
        return result
