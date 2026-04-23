"""Screener summary cache — runs all YAML strategies and persists results for 24h.

Provides:
  run_all()    — run every YAML strategy, save results to disk
  get_cached() — return cached result if fresh, else None
  cache_info() — human-readable cache metadata
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

_CACHE_FILE = Path("data/cache/screener_summary.json")
_MAX_AGE_HOURS = 24


def _load() -> dict | None:
    if not _CACHE_FILE.exists():
        return None
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["saved_at"])
        if (datetime.now() - ts) > timedelta(hours=_MAX_AGE_HOURS):
            return None
        return data
    except Exception:
        return None


def _save(data: dict):
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to save screener cache: {e}")


def get_cached() -> dict | None:
    """Return cached summary if available and < 24h old, else None."""
    return _load()


def cache_info() -> dict:
    """Return cache status metadata."""
    if not _CACHE_FILE.exists():
        return {"has_cache": False}
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["saved_at"])
        age = datetime.now() - ts
        fresh = age < timedelta(hours=_MAX_AGE_HOURS)
        return {
            "has_cache": True,
            "fresh": fresh,
            "saved_at": data["saved_at"],
            "age_minutes": int(age.total_seconds() / 60),
            "strategy_count": len(data.get("results", {})),
        }
    except Exception:
        return {"has_cache": False}


async def run_all(strategy_keys: list[str] | None = None) -> dict:
    """Run all (or specified) YAML screening strategies and cache the combined result.

    Args:
        strategy_keys: optional list of 'yaml_<name>' keys to run; defaults to all.

    Returns the summary payload dict.
    """
    from quantforge.screener.engine import ScreenerConfig, run_screener
    from quantforge.strategy.yaml_registry import registry

    # Resolve which strategies to run
    all_names = registry.names()
    if strategy_keys:
        # Accept both 'yaml_name' and bare 'name'
        target_names = [k[5:] if k.startswith("yaml_") else k for k in strategy_keys]
    else:
        target_names = list(all_names)

    results: dict = {}
    errors: dict = {}

    for name in target_names:
        config = registry.get_screener_config(name)
        if config is None:
            continue
        sc = registry.as_screener_strategy(name) or {}
        key = f"yaml_{name}"
        try:
            logger.info(f"Screener cache: running {key}...")
            result = await run_screener(config)
            result["strategy"] = {
                "key":          key,
                "display_name": sc.get("display_name", name),
                "category_color": sc.get("category_color", "#6366f1"),
                "rationale":    sc.get("rationale", ""),
                "yaml_name":    name,
            }
            results[key] = result
        except Exception as e:
            logger.warning(f"Strategy {key} failed: {e}")
            errors[key] = str(e)

    payload = {
        "saved_at":       datetime.now().isoformat(),
        "results":        results,
        "errors":         errors,
        "strategy_count": len(results),
    }
    _save(payload)
    logger.info(f"Screener cache: saved {len(results)} strategies")
    return payload
