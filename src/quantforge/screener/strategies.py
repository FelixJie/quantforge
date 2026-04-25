"""Strategy category metadata — shared across screener and YAML registry.

All actual strategy definitions live in strategies/yaml/*.yaml.
This module only provides category display metadata used for grouping and coloring.
"""

from __future__ import annotations

# Category metadata — ordered for display grouping
# Used by yaml_registry → screener.py route to enrich YAML strategy responses
CATEGORY_META: dict[str, dict] = {
    "momentum":     {"label": "动量趋势",  "color": "#f59e0b", "order": 1},
    "reversal":     {"label": "反转策略",  "color": "#06b6d4", "order": 2},
    "value":        {"label": "价值选股",  "color": "#3b82f6", "order": 3},
    "growth":       {"label": "成长选股",  "color": "#a855f7", "order": 4},
    "quality":      {"label": "质量成长",  "color": "#22c55e", "order": 5},
    "defensive":    {"label": "防御配置",  "color": "#64748b", "order": 6},
    "multi_factor": {"label": "多因子",    "color": "#8b5cf6", "order": 7},
}
