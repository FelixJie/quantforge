"""YamlStrategyRegistry — single source of truth for YAML-defined strategies.

Loads all *.yaml files from strategies/yaml/ and exposes them to:
  1. Screener module  → get_screener_config(name) → ScreenerConfig
  2. Strategy library → list_for_strategy_lib()   → merged strategy list
  3. YAML signal LLM  → get_yaml_dict(name)        → raw dict for LLM prompt

Responsibilities:
  - Parse and cache YAML files (reloads on file change in dev mode)
  - Convert YAML screener section → ScreenerConfig dataclass
  - Map YAML execution.strategy_class → built-in strategy path
  - Provide unified metadata for UI display

Usage:
    from quantforge.strategy.yaml_registry import registry

    # In screener
    cfg = registry.get_screener_config("ma_golden_cross")

    # In strategy library API
    strats = registry.list_for_strategy_lib()

    # In YAML signal analysis
    raw = registry.get_yaml_dict("ma_golden_cross")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from loguru import logger

_YAML_DIR = Path("strategies/yaml")

# Maps YAML execution.strategy_class → built-in strategy metadata path
_CLASS_MAP: dict[str, dict] = {
    "dual_ma": {
        "path": "strategies.examples.dual_ma_strategy.DualMAStrategy",
        "display_name": "双均线策略",
    },
    "rsi_mean_revert": {
        "path": "strategies.examples.rsi_mean_revert.RSIMeanRevertStrategy",
        "display_name": "RSI均值回归",
    },
    "bollinger_breakout": {
        "path": "strategies.examples.bollinger_breakout.BollingerBreakoutStrategy",
        "display_name": "布林带突破",
    },
    "macd": {
        "path": "strategies.examples.macd_strategy.MACDStrategy",
        "display_name": "MACD趋势跟随",
    },
    "turtle_breakout": {
        "path": "strategies.examples.turtle_breakout.TurtleBreakoutStrategy",
        "display_name": "海龟突破系统",
    },
    "volume_price_breakout": {
        "path": "strategies.examples.volume_price_breakout.VolumePriceBreakoutStrategy",
        "display_name": "量价突破",
    },
}


class YamlStrategyRegistry:
    """Loads, caches, and exposes all YAML strategy definitions."""

    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load (or reload) all YAML files from strategies/yaml/."""
        self._cache.clear()
        if not _YAML_DIR.exists():
            return
        for f in sorted(_YAML_DIR.glob("*.yaml")):
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8"))
                name = data.get("name", f.stem)
                self._cache[name] = data
            except Exception as e:
                logger.warning(f"yaml_registry: failed to load {f.name}: {e}")
        logger.info(f"yaml_registry: loaded {len(self._cache)} strategies")

    def reload(self) -> None:
        self._load_all()

    # ── Accessors ──────────────────────────────────────────────────────────────

    def names(self) -> list[str]:
        return list(self._cache.keys())

    def get_yaml_dict(self, name: str) -> dict | None:
        return self._cache.get(name)

    def get_screener_config(self, name: str):
        """Convert YAML screener section to ScreenerConfig. Returns None if no screener section."""
        from quantforge.screener.engine import ScreenerConfig

        data = self._cache.get(name)
        if not data or "screener" not in data:
            return None

        sc = data["screener"]
        filters = sc.get("filters", {})
        fw_raw = sc.get("factor_weights", {})

        # Normalise factor_weights: int values → float, scale to 0-1 range
        total = sum(v for v in fw_raw.values() if v and v > 0) or 1
        factor_weights = {k: round(v / total, 4) for k, v in fw_raw.items() if v}

        return ScreenerConfig(
            min_price=filters.get("min_price", 2.0),
            max_price=filters.get("max_price"),
            min_pe=filters.get("min_pe"),
            max_pe=filters.get("max_pe", 200.0),
            min_pb=filters.get("min_pb"),
            max_pb=filters.get("max_pb"),
            min_market_cap=filters.get("min_market_cap"),
            max_market_cap=filters.get("max_market_cap"),
            min_change_pct=filters.get("min_change_pct"),
            max_change_pct=filters.get("max_change_pct"),
            factor_weights=factor_weights,
            top_n=sc.get("top_n", 30),
            enrich_fundamentals=sc.get("enrich_fundamentals", False),
        )

    def get_execution_info(self, name: str) -> dict | None:
        """Return execution class path and params, or None if no execution section."""
        data = self._cache.get(name)
        if not data or "execution" not in data:
            return None
        ex = data["execution"]
        cls_key = ex.get("strategy_class", "")
        cls_info = _CLASS_MAP.get(cls_key, {})
        return {
            "strategy_class":  cls_key,
            "strategy_path":   cls_info.get("path", ""),
            "strategy_params": ex.get("strategy_params", {}),
            "class_display":   cls_info.get("display_name", cls_key),
        }

    # ── UI metadata ────────────────────────────────────────────────────────────

    def list_metadata(self) -> list[dict]:
        """Return display metadata for all YAML strategies (for strategy-lib UI)."""
        result = []
        for name, data in self._cache.items():
            sc = data.get("screener", {})
            ex = data.get("execution", {})
            cls_key = ex.get("strategy_class", "")
            cls_info = _CLASS_MAP.get(cls_key, {})
            result.append({
                "name":           name,
                "display_name":   data.get("display_name", name),
                "description":    (data.get("description") or "").strip()[:300],
                "source":         "yaml",                       # distinguish from hardcoded
                "category":       sc.get("category", ""),
                "category_color": sc.get("category_color", "#6366f1"),
                "icon":           sc.get("icon", "file-text"),
                "risk":           sc.get("risk", "-"),
                "suitable":       sc.get("suitable", ""),
                "holding_period": sc.get("holding_period", ""),
                "has_screener":   "screener" in data,
                "has_execution":  "execution" in data,
                "execution_class":    cls_key,
                "execution_display":  cls_info.get("display_name", cls_key),
                "execution_path":     cls_info.get("path", ""),
                "execution_params":   ex.get("strategy_params", {}),
            })
        return result

    def as_screener_strategy(self, name: str) -> dict | None:
        """Return dict compatible with SCREENING_STRATEGIES format, or None."""
        data = self._cache.get(name)
        if not data or "screener" not in data:
            return None
        sc = data["screener"]
        filters = sc.get("filters", {})
        fw_raw = sc.get("factor_weights", {})
        return {
            "id":             f"YAML_{name.upper()[:6]}",
            "display_name":   data.get("display_name", name),
            "category":       sc.get("category", "momentum"),
            "category_color": sc.get("category_color", "#6366f1"),
            "icon":           sc.get("icon", "file"),
            "description":    (data.get("description") or "").strip(),
            "rationale":      f"YAML策略: {data.get('display_name', name)}",
            "source":         "YAML自定义策略",
            "suitable":       sc.get("suitable", ""),
            "risk":           sc.get("risk", "中"),
            "holding_period": sc.get("holding_period", ""),
            "filters":        filters,
            "factor_weights": fw_raw,
            "top_n":          sc.get("top_n", 30),
            "enrich_fundamentals": sc.get("enrich_fundamentals", False),
            "yaml_name":      name,   # link back to YAML for signal analysis
        }


# Singleton
registry = YamlStrategyRegistry()
