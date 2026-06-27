"""Stock metadata cache — persistent code→name mapping for all A-share stocks.

Loaded from disk on startup (JSON file).  Refreshed from efinance when stale.
Provides sub-millisecond name lookups without live API calls.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

_CACHE_FILE = Path("data/cache/stock_names.json")
_MAX_AGE_HOURS = 12

# In-memory store: {code: {"name": str, "exchange": str}}
_store: dict[str, dict] = {}
_loaded_at: datetime | None = None


# ── Public API ────────────────────────────────────────────────────────────────

def get_name(code: str) -> str:
    """Return stock name for code, or empty string if not found."""
    return _store.get(code, {}).get("name", "")


def get_all_names() -> dict[str, str]:
    """Return {code: name} mapping for all cached stocks."""
    return {k: v["name"] for k, v in _store.items()}


def count() -> int:
    return len(_store)


# ── Internal ──────────────────────────────────────────────────────────────────

def _is_stale() -> bool:
    if _loaded_at is None:
        return True
    return (datetime.now() - _loaded_at) > timedelta(hours=_MAX_AGE_HOURS)


def _normalize_store(raw: dict) -> dict:
    """Force the store to be keyed by 6-digit code with ``name`` = display name.

    efinance's ``get_realtime_quotes`` column order has flipped historically
    (code vs name), which silently produced a store keyed by *name* with the
    6-digit code stuffed into the ``name`` field. That inversion breaks every
    consumer (``get_name``/``search_stocks``/机构荐股 linkification all expect a
    code→name map). Detecting the 6-digit field per entry and re-keying makes
    loading robust to whichever orientation the source/disk happens to be in.
    """
    fixed: dict[str, dict] = {}
    for k, v in (raw or {}).items():
        info = dict(v) if isinstance(v, dict) else {"name": v}
        key = str(k).strip()
        name_field = str(info.get("name", "")).strip()
        if key.isdigit() and len(key) == 6:
            code, disp = key, name_field            # already correct
        elif name_field.isdigit() and len(name_field) == 6:
            code, disp = name_field, key            # inverted: name field holds the code
        else:
            code, disp = key, name_field            # unknown shape — leave as-is
        info["name"] = disp
        fixed[code] = info
    return fixed


def _load_from_file(allow_stale: bool = False) -> bool:
    """Load cache from disk.

    Returns True if loaded. By default a cache older than ``_MAX_AGE_HOURS`` is
    treated as stale and *not* loaded (so the caller triggers a network refresh).
    Pass ``allow_stale=True`` to load regardless of age — used as a fallback when
    the network refresh fails, since stale stock names are far better than an
    empty cache (names barely change, and an empty cache silently disables
    features like 机构荐股 stock linkification).
    """
    if not _CACHE_FILE.exists():
        return False
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data.get("updated_at", "2000-01-01"))
        if not allow_stale and (datetime.now() - ts) > timedelta(hours=_MAX_AGE_HOURS):
            logger.debug("Stock meta cache on disk is stale")
            return False
        global _store, _loaded_at
        _store = _normalize_store(data.get("stocks", {}))
        _loaded_at = ts
        stale = (datetime.now() - ts) > timedelta(hours=_MAX_AGE_HOURS)
        logger.info(f"Stock meta cache loaded from disk: {len(_store)} stocks"
                    + ("（已过期，作为网络失败兜底）" if stale else ""))
        return bool(_store)
    except Exception as e:
        logger.warning(f"Failed to load stock meta cache from disk: {e}")
        return False


def _save_to_file():
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now().isoformat(),
            "stocks": _store,
        }
        _CACHE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        logger.info(f"Stock meta cache saved: {len(_store)} stocks → {_CACHE_FILE}")
    except Exception as e:
        logger.warning(f"Failed to save stock meta cache: {e}")


async def refresh(force: bool = False):
    """Refresh stock metadata from efinance.

    - On startup: tries disk cache first; fetches from network only if stale.
    - force=True: always fetches from network.
    """
    global _store, _loaded_at

    if not force and _load_from_file():
        return  # disk cache is fresh

    logger.info("Fetching stock metadata from efinance (realtime quotes)...")
    try:
        import efinance as ef
        from quantforge.data.feed.efinance_feed import detect_exchange

        df = await asyncio.to_thread(ef.stock.get_realtime_quotes)
        # columns positional: 0=name, 1=code, 2=涨跌幅, 3=最新价, etc.
        new_store: dict[str, dict] = {}
        for _, row in df.iterrows():
            try:
                code = str(row.iloc[1]).strip() if len(row) > 1 else ""
                name = str(row.iloc[0]).strip() if len(row) > 0 else ""
                
                price = None
                change_pct = None
                change_val = None
                
                # Try to extract price and change info
                if len(row) > 3:
                    try:
                        price_val = row.iloc[3]
                        if price_val not in (None, "-", ""):
                            price = float(price_val)
                    except (ValueError, TypeError, IndexError):
                        pass
                
                if len(row) > 2:
                    try:
                        pct_val = row.iloc[2]
                        if pct_val not in (None, "-", ""):
                            change_pct = float(pct_val)
                    except (ValueError, TypeError, IndexError):
                        pass
                
                if code and name:
                    new_store[code] = {
                        "name": name,
                        "exchange": detect_exchange(code).value,
                        "price": price,
                        "change_pct": change_pct,
                        "change": change_val,
                    }
            except Exception:
                continue

        _store = _normalize_store(new_store)
        _loaded_at = datetime.now()
        _save_to_file()
        logger.info(f"Stock meta cache refreshed: {len(_store)} stocks")
    except Exception as e:
        logger.warning(f"Stock meta cache refresh failed: {e}")
        # Fall back to stale disk cache if available — stale names beat an empty
        # cache (an empty store silently disables 机构荐股 stock linkification etc.).
        if not _store:
            _load_from_file(allow_stale=True)


def get_stock_info(code: str) -> dict | None:
    """Return full stock info dict for code, or None if not found."""
    return _store.get(code)


def get_stocks_by_filter(filter_func=None, limit: int = None) -> list[dict]:
    """Return list of stocks matching filter function.
    
    Args:
        filter_func: Function that takes (code, info) and returns bool
        limit: Maximum number of results to return
    """
    results = []
    for code, info in _store.items():
        if filter_func is None or filter_func(code, info):
            results.append({
                "code": code,
                "name": info.get("name", ""),
                "exchange": info.get("exchange", ""),
                "price": info.get("price"),
                "change_pct": info.get("change_pct"),
                "change": info.get("change"),
            })
    
    if limit:
        results = results[:limit]
    
    return results


def search_stocks(query: str, limit: int = 50) -> list[dict]:
    """Search stocks by code or name (case-insensitive).
    
    Returns list of matching stocks with basic info.
    """
    query_lower = query.lower()
    results = []
    
    for code, info in _store.items():
        name = info.get("name", "").lower()
        code_str = code.lower()
        
        # Match if query appears in name or code
        if query_lower in name or query_lower in code_str:
            results.append({
                "code": code,
                "name": info.get("name", ""),
                "exchange": info.get("exchange", ""),
                "price": info.get("price"),
                "change_pct": info.get("change_pct"),
                "change": info.get("change"),
            })
            
            if len(results) >= limit:
                break
    
    return results
