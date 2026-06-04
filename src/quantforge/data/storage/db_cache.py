"""Unified SQLite cache — single persistent store for all data modules.

Goals
=====
1. **One database file** (``data/cache.db``) replaces the scattered JSON files under
   ``data/cache/*``.  Every module (sector, market, news, ai_picks, stock_meta, …)
   writes into it via the same thin API.
2. **TTL-based freshness** — each entry carries a TTL in seconds.  ``get()``
   returns ``None`` when the entry is older than its TTL.  ``get_stale()`` is
   available as a graceful fallback when the live upstream source fails.
3. **Refresh-on-demand / overwrite** — ``set()`` always **replaces** (upserts)
   the previous row for the same key, so every new fetch overwrites the last.
   A companion ``POST /api/cache/refresh?key=…`` endpoint exposes this as an
   HTTP action so the frontend can trigger a forced refresh.
4. **Category index** — every entry is tagged with a ``category`` (``"sector"``,
   ``"market"``, ``"news"``, ``"ai_picks"``, ``"stock_meta"``, …).  This powers
   ``list_by_category()`` / ``delete_by_category()`` admin operations and lets
   the admin UI show how much data is cached per area.

Schema
======
``cache_entries`` table::

    key            TEXT PRIMARY KEY        -- unique lookup key, e.g. "sector:industry_boards"
    category       TEXT                    -- e.g. "sector", "market", "news", "ai_picks", "stock_meta"
    payload        TEXT                    -- JSON blob
    fetched_at     TEXT                    -- ISO-8601 timestamp, e.g. "2026-06-01T09:30:00.123456"
    ttl_seconds    INTEGER                 -- how long this entry is considered fresh

``stock_meta`` table (secondary, column-indexed so we can filter/search SQL-side)::

    code           TEXT PRIMARY KEY        -- 6-digit A-share code, e.g. "600519"
    name           TEXT                    -- 贵州茅台
    exchange       TEXT                    -- "SSE" / "SZSE"
    price          REAL
    change_pct     REAL
    change_val     REAL
    updated_at     TEXT                    -- ISO-8601

Additional per-module tables can be declared by calling ``ensure_schema()`` at
import time; the DDL is idempotent (``CREATE TABLE IF NOT EXISTS``).

Public API
==========
::

    # Core key/value cache
    get(key: str, ttl_seconds: int | None) -> dict | None
    get_stale(key: str) -> dict | None
    set(key: str, data: dict, ttl_seconds: int, category: str) -> None
    delete(key: str) -> None
    list_by_category(category: str) -> list[dict]  # [{key, fetched_at, size_b}]
    list_categories() -> list[dict]                # [{category, count, oldest, newest}]
    delete_by_category(category: str) -> int
    clear_all() -> None
    get_meta(ttl_seconds=43200) -> dict
    set_meta() -> dict                            # refreshes stock_meta from efinance
    get_stock(code) -> dict | None
    search_stocks(query, limit=50) -> list[dict]
    list_stocks(limit, sort_by, order, filter_type) -> list[dict]

Only the Python standard library (``sqlite3``) is required — no extra deps.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Paths & connection management
# ---------------------------------------------------------------------------

_DB_DIR = Path("data")
_DB_PATH = _DB_DIR / "cache.db"

# SQLite connections are *per-thread*; we share one ``Connection`` per thread
# through a simple lock-protected dict.  Using ``check_same_thread=False`` with
# a single write-lock is a common alternative, but thread-local keeps things
# trivially safe in a FastAPI / asyncio world (where each request runs in its
# own worker thread).
_local = threading.local()
_write_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is None:
        _DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(_DB_PATH, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # Sensible pragmas for a small, frequently-written cache DB.
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        _ensure_schema(conn)
        _local.conn = conn
    return conn


# ---------------------------------------------------------------------------
# Schema  (idempotent — safe to call repeatedly)
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
    key         TEXT    PRIMARY KEY,
    category    TEXT    NOT NULL DEFAULT 'uncategorized',
    payload     TEXT    NOT NULL,
    fetched_at  TEXT    NOT NULL,
    ttl_seconds INTEGER NOT NULL DEFAULT 600
);
CREATE INDEX IF NOT EXISTS idx_cache_category ON cache_entries(category);
CREATE INDEX IF NOT EXISTS idx_cache_fetched  ON cache_entries(fetched_at);

CREATE TABLE IF NOT EXISTS stock_meta (
    code        TEXT PRIMARY KEY,
    name        TEXT,
    exchange    TEXT,
    price       REAL,
    change_pct  REAL,
    change_val  REAL,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_stock_meta_name     ON stock_meta(name);
CREATE INDEX IF NOT EXISTS idx_stock_meta_exchange ON stock_meta(exchange);

-- Sector boards (one row per industry/concept board, current snapshot)
CREATE TABLE IF NOT EXISTS sector_boards (
    kind          TEXT NOT NULL,            -- 'industry' | 'concept'
    name          TEXT NOT NULL,
    node          TEXT,                      -- Sina node code (new_*/gn_*)
    change_pct    REAL,
    avg_pe        REAL,
    median_pe     REAL,
    avg_pb        REAL,
    pe_valid      INTEGER,
    turnover_rate REAL,
    market_cap    REAL,
    amount        REAL,
    up_count      INTEGER,
    down_count    INTEGER,
    total         INTEGER,
    leader        TEXT,
    leader_change REAL,
    updated_at    TEXT,
    PRIMARY KEY (kind, name)
);
CREATE INDEX IF NOT EXISTS idx_sector_boards_kind ON sector_boards(kind);

-- Sector constituents (one row per stock per board)
CREATE TABLE IF NOT EXISTS sector_constituents (
    kind          TEXT NOT NULL,
    board         TEXT NOT NULL,
    code          TEXT NOT NULL,
    name          TEXT,
    price         REAL,
    change_pct    REAL,
    turnover_rate REAL,
    turnover      REAL,                      -- 成交额 (元)
    pe            REAL,
    pb            REAL,
    market_cap    REAL,
    updated_at    TEXT,
    PRIMARY KEY (kind, board, code)
);
CREATE INDEX IF NOT EXISTS idx_sector_cons_board ON sector_constituents(kind, board);
CREATE INDEX IF NOT EXISTS idx_sector_cons_code  ON sector_constituents(code);

-- Per-account watchlist (durable user data, not wiped by cache clear)
CREATE TABLE IF NOT EXISTS watchlist (
    user_id   TEXT NOT NULL,
    code      TEXT NOT NULL,
    name      TEXT,
    notes     TEXT DEFAULT '',
    tags      TEXT DEFAULT '[]',     -- JSON array
    added_at  TEXT,
    PRIMARY KEY (user_id, code)
);
CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    with _write_lock:
        conn.executescript(_SCHEMA)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now().isoformat()


def _size_b(payload: str) -> int:
    try:
        return len(payload.encode("utf-8"))
    except Exception:
        return len(payload)


# ---------------------------------------------------------------------------
# Core key/value cache API
# ---------------------------------------------------------------------------

def get(key: str, ttl_seconds: int | None = None) -> dict | None:
    """Return cached payload for ``key`` if it exists and is fresh.

    ``ttl_seconds`` — if omitted, the TTL stored alongside the entry is used;
    if provided, it overrides the stored TTL (useful when a caller wants a
    shorter/longer freshness window than what the writer originally set).
    Returns ``None`` if the entry is missing or expired.
    """
    try:
        row = _conn().execute(
            "SELECT payload, fetched_at, ttl_seconds FROM cache_entries WHERE key=?",
            (key,),
        ).fetchone()
    except Exception as exc:
        logger.debug(f"db_cache.get({key!r}) failed: {exc}")
        return None
    if not row:
        return None
    fetched = _parse_iso(row["fetched_at"])
    if fetched is None:
        return None
    ttl = ttl_seconds if ttl_seconds is not None else int(row["ttl_seconds"])
    if (datetime.now() - fetched).total_seconds() > ttl:
        return None
    try:
        return json.loads(row["payload"])
    except Exception as exc:
        logger.debug(f"db_cache.get({key!r}) bad JSON: {exc}")
        return None


def get_stale(key: str) -> dict | None:
    """Return the cached payload regardless of age — used as graceful fallback
    when the live upstream call fails."""
    try:
        row = _conn().execute(
            "SELECT payload FROM cache_entries WHERE key=?", (key,)
        ).fetchone()
    except Exception as exc:
        logger.debug(f"db_cache.get_stale({key!r}) failed: {exc}")
        return None
    if not row:
        return None
    try:
        return json.loads(row["payload"])
    except Exception:
        return None


def set(
    key: str,
    data: Any,
    ttl_seconds: int,
    category: str = "uncategorized",
) -> None:
    """Upsert ``data`` under ``key`` — **always overwrites** previous row.

    ``data`` is JSON-serialised; any non-serialisable leaf (e.g. a ``datetime``,
    a ``Decimal``) is coerced to its string representation via ``default=str``.
    """
    payload = json.dumps(data, ensure_ascii=False, default=str)
    with _write_lock:
        try:
            _conn().execute(
                """
                INSERT INTO cache_entries(key, category, payload, fetched_at, ttl_seconds)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    category   = excluded.category,
                    payload    = excluded.payload,
                    fetched_at = excluded.fetched_at,
                    ttl_seconds = excluded.ttl_seconds
                """,
                (
                    key,
                    category,
                    payload,
                    _now_iso(),
                    int(ttl_seconds),
                ),
            )
        except Exception as exc:
            logger.warning(f"db_cache.set({key!r}) failed: {exc}")


def delete(key: str) -> None:
    with _write_lock:
        try:
            _conn().execute("DELETE FROM cache_entries WHERE key=?", (key,))
        except Exception as exc:
            logger.debug(f"db_cache.delete({key!r}) failed: {exc}")


def list_by_category(category: str) -> list[dict]:
    try:
        rows = _conn().execute(
            """SELECT key, fetched_at, payload
               FROM cache_entries
               WHERE category=?
               ORDER BY fetched_at DESC""",
            (category,),
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.list_by_category({category!r}) failed: {exc}")
        return []
    return [
        {
            "key": r["key"],
            "fetched_at": r["fetched_at"],
            "size_b": _size_b(r["payload"]),
        }
        for r in rows
    ]


def list_categories() -> list[dict]:
    try:
        rows = _conn().execute(
            """SELECT category,
                      COUNT(*)                                    AS count,
                      MIN(fetched_at)                            AS oldest,
                      MAX(fetched_at)                            AS newest
               FROM cache_entries
               GROUP BY category
               ORDER BY count DESC""",
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.list_categories failed: {exc}")
        return []
    return [dict(r) for r in rows]


def delete_by_category(category: str) -> int:
    with _write_lock:
        try:
            cur = _conn().execute(
                "DELETE FROM cache_entries WHERE category=?", (category,)
            )
            return cur.rowcount or 0
        except Exception as exc:
            logger.debug(f"db_cache.delete_by_category({category!r}) failed: {exc}")
            return 0


def clear_all() -> None:
    with _write_lock:
        try:
            _conn().execute("DELETE FROM cache_entries;")
            _conn().execute("DELETE FROM stock_meta;")
        except Exception as exc:
            logger.warning(f"db_cache.clear_all failed: {exc}")


def stats() -> dict:
    try:
        conn = _conn()
        total = conn.execute("SELECT COUNT(*) AS c FROM cache_entries").fetchone()["c"]
        cats = list_categories()
        stock_total = conn.execute("SELECT COUNT(*) AS c FROM stock_meta").fetchone()["c"]
    except Exception:
        total = stock_total = 0
        cats = []
    return {
        "db_path": str(_DB_PATH),
        "entries_total": total,
        "entries_by_category": cats,
        "stock_meta_total": stock_total,
    }


# ---------------------------------------------------------------------------
# stock_meta table helpers
# ---------------------------------------------------------------------------
# ``stock_meta`` duplicates the JSON-file-based stock name table into a proper
# SQL table so callers can do SQL-side searches, pagination and sorting without
# having to materialise the entire universe in Python memory each time.
#
# ``get_meta`` / ``set_meta`` keep the existing ``get_all_names()`` /
# ``search_stocks()`` API contract intact — nothing else in the codebase needs
# to change.

def _row_to_stock(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "code": row["code"],
        "name": row["name"] or "",
        "exchange": row["exchange"] or "",
        "price": row["price"],
        "change_pct": row["change_pct"],
        "change": row["change_val"],
    }


def get_stock(code: str) -> dict | None:
    try:
        row = _conn().execute(
            "SELECT * FROM stock_meta WHERE code=?", (code,)
        ).fetchone()
    except Exception:
        return None
    return _row_to_stock(row)


def get_all_names() -> dict[str, str]:
    try:
        rows = _conn().execute("SELECT code, name FROM stock_meta").fetchall()
    except Exception:
        return {}
    return {r["code"]: (r["name"] or "") for r in rows}


def count_stocks() -> int:
    try:
        return _conn().execute("SELECT COUNT(*) AS c FROM stock_meta").fetchone()["c"]
    except Exception:
        return 0


def search_stocks(query: str, limit: int = 50) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []
    like = f"%{q}%"
    try:
        rows = _conn().execute(
            """SELECT * FROM stock_meta
               WHERE code LIKE ? OR name LIKE ?
               ORDER BY code ASC
               LIMIT ?""",
            (like, like, int(limit)),
        ).fetchall()
    except Exception:
        return []
    return [_row_to_stock(r) for r in rows if r]


def list_stocks(
    limit: int = 100,
    sort_by: str = "code",
    order: str = "asc",
    filter_type: str | None = None,
) -> list[dict]:
    sort_cols = {
        "code": "code",
        "name": "name",
        "change_pct": "change_pct",
        "price": "price",
    }
    col = sort_cols.get(sort_by, "code")
    direction = "DESC" if (order or "").lower() == "desc" else "ASC"

    where = ""
    params: list[Any] = []
    if filter_type == "gainers":
        where = "WHERE change_pct IS NOT NULL "
    elif filter_type == "losers":
        where = "WHERE change_pct IS NOT NULL "

    try:
        rows = _conn().execute(
            f"""SELECT * FROM stock_meta {where}
                ORDER BY {col} {direction}
                LIMIT ?""",
            params + [int(limit)],
        ).fetchall()
    except Exception:
        return []
    return [_row_to_stock(r) for r in rows if r]


def upsert_stocks(rows: list[dict]) -> int:
    """Bulk-upsert rows into the ``stock_meta`` table.

    ``rows`` items should include ``code`` + ``name`` (and optionally
    ``exchange``, ``price``, ``change_pct``, ``change``).  Rows without a
    ``code`` are skipped.
    """
    now = _now_iso()
    tuples = []
    for r in rows:
        code = r.get("code")
        if not code:
            continue
        tuples.append(
            (
                str(code),
                r.get("name", ""),
                r.get("exchange", ""),
                r.get("price"),
                r.get("change_pct"),
                r.get("change"),
                now,
            )
        )
    if not tuples:
        return 0
    with _write_lock:
        try:
            _conn().executemany(
                """
                INSERT INTO stock_meta(code, name, exchange, price, change_pct, change_val, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name       = excluded.name,
                    exchange   = excluded.exchange,
                    price      = excluded.price,
                    change_pct = excluded.change_pct,
                    change_val = excluded.change_val,
                    updated_at = excluded.updated_at
                """,
                tuples,
            )
        except Exception as exc:
            logger.warning(f"db_cache.upsert_stocks failed: {exc}")
            return 0
    return len(tuples)


def clear_stock_meta() -> None:
    with _write_lock:
        try:
            _conn().execute("DELETE FROM stock_meta;")
        except Exception as exc:
            logger.debug(f"db_cache.clear_stock_meta failed: {exc}")


# ---------------------------------------------------------------------------
# Sector tables (structured storage for industry/concept boards + constituents)
# ---------------------------------------------------------------------------

_BOARD_COLS = [
    "kind", "name", "node", "change_pct", "avg_pe", "median_pe", "avg_pb",
    "pe_valid", "turnover_rate", "market_cap", "amount", "up_count",
    "down_count", "total", "leader", "leader_change",
]

_CONS_COLS = [
    "code", "name", "price", "change_pct", "turnover_rate", "turnover",
    "pe", "pb", "market_cap",
]


def _newest_age_seconds(rows: list[sqlite3.Row]) -> float | None:
    """Seconds since the most recently updated row (None if no timestamps)."""
    stamps = [_parse_iso(r["updated_at"]) for r in rows if r["updated_at"]]
    stamps = [s for s in stamps if s is not None]
    if not stamps:
        return None
    return (datetime.now() - max(stamps)).total_seconds()


def replace_sector_boards(kind: str, boards: list[dict]) -> int:
    """Replace the whole snapshot of boards for ``kind`` (delete + insert)."""
    now = _now_iso()
    rows = []
    for b in boards:
        vals = [kind if c == "kind" else b.get(c) for c in _BOARD_COLS]
        rows.append(tuple(vals) + (now,))
    placeholders = ",".join("?" * (len(_BOARD_COLS) + 1))
    cols = ",".join(_BOARD_COLS) + ",updated_at"
    with _write_lock:
        try:
            conn = _conn()
            conn.execute("DELETE FROM sector_boards WHERE kind=?", (kind,))
            conn.executemany(
                f"INSERT INTO sector_boards({cols}) VALUES({placeholders})", rows
            )
        except Exception as exc:
            logger.warning(f"db_cache.replace_sector_boards({kind!r}) failed: {exc}")
            return 0
    return len(rows)


def get_sector_boards(kind: str) -> list[dict] | None:
    """All stored boards for ``kind`` (regardless of age). None if empty."""
    try:
        rows = _conn().execute(
            "SELECT * FROM sector_boards WHERE kind=? ORDER BY name", (kind,)
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.get_sector_boards({kind!r}) failed: {exc}")
        return None
    if not rows:
        return None
    out = []
    for r in rows:
        d = dict(r)
        d.pop("updated_at", None)
        out.append(d)
    return out


def sector_boards_fresh(kind: str, ttl_seconds: int) -> bool:
    try:
        rows = _conn().execute(
            "SELECT updated_at FROM sector_boards WHERE kind=?", (kind,)
        ).fetchall()
    except Exception:
        return False
    age = _newest_age_seconds(rows)
    return age is not None and age <= ttl_seconds


def replace_sector_constituents(kind: str, board: str, stocks: list[dict]) -> int:
    """Replace the constituent snapshot for one (kind, board)."""
    now = _now_iso()
    rows = []
    for s in stocks:
        vals = [kind, board] + [s.get(c) for c in _CONS_COLS]
        rows.append(tuple(vals) + (now,))
    cols = "kind,board," + ",".join(_CONS_COLS) + ",updated_at"
    placeholders = ",".join("?" * (len(_CONS_COLS) + 3))
    with _write_lock:
        try:
            conn = _conn()
            conn.execute(
                "DELETE FROM sector_constituents WHERE kind=? AND board=?", (kind, board)
            )
            conn.executemany(
                f"INSERT INTO sector_constituents({cols}) VALUES({placeholders})", rows
            )
        except Exception as exc:
            logger.warning(
                f"db_cache.replace_sector_constituents({kind!r},{board!r}) failed: {exc}"
            )
            return 0
    return len(rows)


def get_sector_constituents(kind: str, board: str) -> list[dict] | None:
    try:
        rows = _conn().execute(
            "SELECT * FROM sector_constituents WHERE kind=? AND board=? "
            "ORDER BY change_pct DESC",
            (kind, board),
        ).fetchall()
    except Exception as exc:
        logger.debug(
            f"db_cache.get_sector_constituents({kind!r},{board!r}) failed: {exc}"
        )
        return None
    if not rows:
        return None
    out = []
    for r in rows:
        d = dict(r)
        d.pop("kind", None)
        d.pop("board", None)
        d.pop("updated_at", None)
        out.append(d)
    return out


def sector_constituents_fresh(kind: str, board: str, ttl_seconds: int) -> bool:
    try:
        rows = _conn().execute(
            "SELECT updated_at FROM sector_constituents WHERE kind=? AND board=?",
            (kind, board),
        ).fetchall()
    except Exception:
        return False
    age = _newest_age_seconds(rows)
    return age is not None and age <= ttl_seconds


# ---------------------------------------------------------------------------
# Watchlist (per-account)
# ---------------------------------------------------------------------------

def _row_to_watch(row: sqlite3.Row) -> dict:
    try:
        tags = json.loads(row["tags"]) if row["tags"] else []
    except Exception:
        tags = []
    return {
        "code": row["code"],
        "name": row["name"] or row["code"],
        "notes": row["notes"] or "",
        "tags": tags,
        "added_at": row["added_at"],
    }


def get_watchlist(user_id: str) -> list[dict]:
    try:
        rows = _conn().execute(
            "SELECT * FROM watchlist WHERE user_id=? ORDER BY added_at", (user_id,)
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.get_watchlist({user_id!r}) failed: {exc}")
        return []
    return [_row_to_watch(r) for r in rows]


def watchlist_get_item(user_id: str, code: str) -> dict | None:
    try:
        row = _conn().execute(
            "SELECT * FROM watchlist WHERE user_id=? AND code=?", (user_id, code)
        ).fetchone()
    except Exception:
        return None
    return _row_to_watch(row) if row else None


def watchlist_add(user_id: str, code: str, name: str = "", notes: str = "",
                  tags: list[str] | None = None) -> dict | None:
    """Insert a watchlist row. Returns the new item, or None if it already existed."""
    if watchlist_get_item(user_id, code) is not None:
        return None
    item = {
        "code": code,
        "name": name or code,
        "notes": notes or "",
        "tags": tags or [],
        "added_at": _now_iso(),
    }
    with _write_lock:
        try:
            _conn().execute(
                "INSERT INTO watchlist(user_id, code, name, notes, tags, added_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (user_id, code, item["name"], item["notes"],
                 json.dumps(item["tags"], ensure_ascii=False), item["added_at"]),
            )
        except Exception as exc:
            logger.warning(f"db_cache.watchlist_add failed: {exc}")
            return None
    return item


def watchlist_remove(user_id: str, code: str) -> bool:
    with _write_lock:
        try:
            cur = _conn().execute(
                "DELETE FROM watchlist WHERE user_id=? AND code=?", (user_id, code)
            )
            return (cur.rowcount or 0) > 0
        except Exception as exc:
            logger.debug(f"db_cache.watchlist_remove failed: {exc}")
            return False


def watchlist_update_notes(user_id: str, code: str, notes: str) -> dict | None:
    with _write_lock:
        try:
            cur = _conn().execute(
                "UPDATE watchlist SET notes=? WHERE user_id=? AND code=?",
                (notes or "", user_id, code),
            )
            if (cur.rowcount or 0) == 0:
                return None
        except Exception as exc:
            logger.warning(f"db_cache.watchlist_update_notes failed: {exc}")
            return None
    return watchlist_get_item(user_id, code)


def watchlist_clear(user_id: str) -> int:
    with _write_lock:
        try:
            cur = _conn().execute("DELETE FROM watchlist WHERE user_id=?", (user_id,))
            return cur.rowcount or 0
        except Exception as exc:
            logger.debug(f"db_cache.watchlist_clear failed: {exc}")
            return 0


# ---------------------------------------------------------------------------
# Optional: one-shot migration from legacy JSON caches
# ---------------------------------------------------------------------------

_OLD_DIRS = [
    Path("data/cache/sector"),
    Path("data/cache/news"),
    Path("data/cache/ai_picks"),
    Path("data/cache/intraday"),
]


def migrate_legacy_json_files() -> dict:
    """Best-effort: load old ``.json`` cache files into the SQLite store.

    Run once at startup.  After that, modules write only to SQLite.  Returns a
    small report of how many entries were migrated per category.
    """
    report: dict[str, int] = {}
    category_by_dir = {
        Path("data/cache/sector"): "sector",
        Path("data/cache/news"): "news",
        Path("data/cache/ai_picks"): "ai_picks",
        Path("data/cache/intraday"): "market_intraday",
    }
    for old_dir in _OLD_DIRS:
        if not old_dir.exists():
            continue
        cat = category_by_dir.get(old_dir, "legacy")
        migrated = 0
        for f in old_dir.rglob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            ts = data.get("_cached_at") or data.get("fetched_at") or data.get("generated_at")
            key = f"{cat}:{f.relative_to(old_dir).as_posix().rstrip('.json')}"
            # If there's already a newer entry for this key, skip.
            existing = get_stale(key)
            if existing is not None:
                continue
            set(key, data, ttl_seconds=600, category=cat)
            migrated += 1
        report[cat] = report.get(cat, 0) + migrated
        if migrated:
            logger.info(f"db_cache: migrated {migrated} {cat} entries from {old_dir}")
    return report


# Kick off the migration at import time (one shot; idempotent on re-runs).
try:
    migrate_legacy_json_files()
except Exception as exc:  # pragma: no cover - best-effort only
    logger.debug(f"db_cache: legacy migration skipped: {exc}")
