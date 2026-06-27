"""Whole-market quote snapshot — background refresher.

Keeps a durable, queryable snapshot of every A-share's realtime quote in the
``stock_quote`` table (``data/cache.db``) so the API can serve list/quote
displays from indexed SQL in <1s, fully decoupled from upstream API latency
and availability.  When the network is down, reads still return the last
snapshot (stale-but-instant).

Two jobs, both off the request path:

* **universe** — the set of stock codes/names, accumulated into ``stock_meta``
  from Sina's ``hs_a`` listing (only source that enumerates the market here).
  Accumulate-only: partial/failed pulls never shrink it, so it converges to the
  full ~5400 names over a few cycles.
* **quotes** — batch realtime quotes via the datasource facade (iFinD→Tencent,
  the reliable source behind this proxy), 60 codes/request, concurrency 8,
  upserted in a single transaction into ``stock_quote``.

Scheduling is trade-hours aware: 30s during A-share sessions, 5min otherwise.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone, time as dtime

from loguru import logger

from quantforge.data.storage import db_cache
from quantforge.data.feed import datasource

# Dedicated thread pool for the snapshot's blocking network I/O.  Crucial: using
# our own executor (rather than asyncio.to_thread's shared default pool) keeps
# slow/stalled upstream calls from starving uvicorn's request handling.
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="snapshot")


async def _run(fn, *args):
    return await asyncio.get_event_loop().run_in_executor(_EXECUTOR, fn, *args)

# ── Tunables ─────────────────────────────────────────────────────────────────
_BATCH = 60                 # codes per Tencent request
_CONCURRENCY = 8            # parallel quote requests
_INTERVAL_TRADE = 30        # seconds, during A-share sessions
_INTERVAL_IDLE = 300        # seconds, outside sessions
_UNIVERSE_MIN = 4000        # rebuild universe if it has fewer codes than this
_UNIVERSE_TTL = 6 * 3600    # otherwise rebuild at most every 6h

_SINA_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_SINA_BASE = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"

_last_universe_build = 0.0
_loop_count = 0


# ── Universe (code list) from Sina ───────────────────────────────────────────

def _sina_http(url: str) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": _SINA_UA, "Referer": "https://finance.sina.com.cn"}
    )
    return urllib.request.urlopen(req, timeout=12).read().decode("gbk", "replace")


def _sina_count(node: str = "hs_a") -> int:
    try:
        raw = _sina_http(_SINA_BASE + f"Market_Center.getHQNodeStockCount?node={node}")
        m = re.search(r"\d+", raw)
        return int(m.group()) if m else 0
    except Exception:
        return 0


def _sina_page(node: str, page: int, num: int = 100) -> list[dict]:
    url = (_SINA_BASE + "Market_Center.getHQNodeData"
           f"?page={page}&num={num}&sort=symbol&asc=1&node={node}&_s_r_a=page")
    try:  # one attempt per cycle; accumulation across cycles handles blips
        arr = json.loads(_sina_http(url))
    except Exception:
        return []
    out = []
    for s in arr:
        try:
            sym = str(s.get("symbol", ""))
            code = str(s.get("code", "")).strip()
            if not code:
                continue
            out.append({
                "code": code,
                "name": s.get("name", ""),
                "exchange": "SH" if sym.startswith("sh") else ("SZ" if sym.startswith("sz") else ""),
            })
        except Exception:
            continue
    return out


async def build_universe() -> int:
    """Accumulate codes/names from Sina into ``stock_meta`` (only grows)."""
    count = await _run(_sina_count, "hs_a")
    pages = ((count + 99) // 100) if count else 55  # fall back to ~55 pages if count fails
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def fetch(p: int) -> list[dict]:
        async with sem:
            return await _run(_sina_page, "hs_a", p, 100)

    results = await asyncio.gather(*[fetch(p) for p in range(1, pages + 1)])
    rows = [r for page in results for r in page if r.get("code")]
    n = await _run(db_cache.upsert_stocks, rows) if rows else 0
    total = await _run(db_cache.count_stocks)
    logger.info(f"snapshot.build_universe: sina_count={count} fetched={len(rows)} upserted={n} "
                f"universe_total={total}")
    return n


# ── Quote mapping (datasource → stock_quote row) ─────────────────────────────

def _exchange_of(code: str) -> str:
    if code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("8", "4")):
        return "BJ"
    return "SZ"


def _map_quote(code: str, q: dict) -> dict:
    amt_wan = q.get("amount_wan")
    mcap_yi = q.get("mcap_yi")
    return {
        "code": code,
        "name": q.get("name"),
        "exchange": _exchange_of(code),
        "price": q.get("price"),
        "change_pct": q.get("change_pct"),
        "change": q.get("change_amt"),
        "open": q.get("open"),
        "high": q.get("high"),
        "low": q.get("low"),
        "pre_close": q.get("last_close"),
        "volume": q.get("volume"),
        "turnover": amt_wan * 10000 if amt_wan else None,
        "turnover_rate": q.get("turnover_pct"),
        "pe": q.get("pe_ttm"),
        "pb": q.get("pb"),
        "market_cap": mcap_yi * 1e8 if mcap_yi else None,
    }


# ── Quote refresh ────────────────────────────────────────────────────────────

async def refresh_quotes() -> int:
    """Fetch quotes for the whole universe and upsert into ``stock_quote``."""
    codes = list((await _run(db_cache.get_all_names)).keys())
    if not codes:
        logger.warning("snapshot.refresh_quotes: empty universe — building first")
        await build_universe()
        codes = list((await _run(db_cache.get_all_names)).keys())
        if not codes:
            return 0

    chunks = [codes[i:i + _BATCH] for i in range(0, len(codes), _BATCH)]
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def fetch(chunk: list[str]) -> dict:
        async with sem:
            try:
                return await _run(datasource.quotes, chunk) or {}
            except Exception:
                return {}

    maps = await asyncio.gather(*[fetch(c) for c in chunks])
    rows = [_map_quote(code, q) for m in maps for code, q in m.items() if q]
    if not rows:
        logger.debug("snapshot.refresh_quotes: no quotes returned this cycle")
        return 0
    n = await _run(db_cache.quote_upsert_many, rows)
    # Keep names fresh in the universe too (cheap, and self-heals empty names).
    await _run(db_cache.upsert_stocks, [{"code": r["code"], "name": r["name"],
                                         "exchange": r["exchange"]} for r in rows if r.get("name")])
    return n


# ── Trade-hours scheduling ───────────────────────────────────────────────────

def _beijing_now() -> datetime:
    # Avoid tz database dependency on Windows: Beijing = UTC+8, no DST.
    return datetime.now(timezone.utc) + timedelta(hours=8)


def is_trade_hours(now: datetime | None = None) -> bool:
    now = now or _beijing_now()
    if now.weekday() >= 5:  # Sat/Sun
        return False
    t = now.time()
    morning = dtime(9, 25) <= t <= dtime(11, 30)
    afternoon = dtime(13, 0) <= t <= dtime(15, 0)
    return morning or afternoon


# ── Public entry points ──────────────────────────────────────────────────────

async def refresh_once() -> int:
    """One full cycle (build universe if needed, then refresh quotes).

    Used for cold-start warm-up triggered by the API.  Errors are swallowed.
    """
    global _last_universe_build
    try:
        import time as _t
        if (await _run(db_cache.count_stocks)) < _UNIVERSE_MIN or (_t.time() - _last_universe_build) > _UNIVERSE_TTL:
            await build_universe()
            _last_universe_build = _t.time()
        return await refresh_quotes()
    except Exception as exc:
        logger.warning(f"snapshot.refresh_once failed: {exc}")
        return 0


async def run_forever() -> None:
    """Background loop: refresh the snapshot on a trade-hours-aware cadence."""
    global _loop_count
    logger.info("snapshot.run_forever: starting background market-snapshot refresher")
    # Initial warm-up as soon as possible.
    await refresh_once()
    while True:
        try:
            interval = _INTERVAL_TRADE if is_trade_hours() else _INTERVAL_IDLE
            await asyncio.sleep(interval)
            _loop_count += 1
            t0 = asyncio.get_event_loop().time()
            n = await refresh_once()
            dt = asyncio.get_event_loop().time() - t0
            total = await _run(db_cache.count_stocks)
            logger.info(f"snapshot: cycle#{_loop_count} upserted={n} "
                        f"universe={total} in {dt:.1f}s "
                        f"(trade_hours={is_trade_hours()})")
        except asyncio.CancelledError:
            logger.info("snapshot.run_forever: cancelled")
            raise
        except Exception as exc:
            logger.warning(f"snapshot.run_forever cycle error: {exc}")
            await asyncio.sleep(_INTERVAL_IDLE)
