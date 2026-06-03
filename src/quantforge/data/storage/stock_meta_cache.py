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


def _load_from_file() -> bool:
    """Load cache from disk. Returns True if loaded and not stale."""
    if not _CACHE_FILE.exists():
        return False
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data.get("updated_at", "2000-01-01"))
        if (datetime.now() - ts) > timedelta(hours=_MAX_AGE_HOURS):
            logger.debug("Stock meta cache on disk is stale")
            return False
        global _store, _loaded_at
        _store = data.get("stocks", {})
        _loaded_at = ts
        logger.info(f"Stock meta cache loaded from disk: {len(_store)} stocks")
        return True
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

        _store = new_store
        _loaded_at = datetime.now()
        _save_to_file()
        logger.info(f"Stock meta cache refreshed: {len(_store)} stocks")
    except Exception as e:
        logger.warning(f"Stock meta cache refresh failed: {e}")
        # Fall back to stale disk cache if available
        if not _store:
            _load_from_file()


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
