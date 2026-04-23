"""Screener API routes.

All strategies are YAML-defined (strategies/yaml/*.yaml).
Built-in hardcoded strategies have been removed — YAML is the single source of truth.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from quantforge.screener.engine import ScreenerConfig, run_screener
from quantforge.screener.factors.fundamental import FACTOR_REGISTRY

router = APIRouter(prefix="/screener", tags=["screener"])


class ScreenerRequest(BaseModel):
    # Filters
    min_price: float = 2.0
    max_price: float | None = None
    min_pe: float | None = None
    max_pe: float | None = 200.0
    min_pb: float | None = None
    max_pb: float | None = None
    min_market_cap: float | None = None   # 亿元
    max_market_cap: float | None = None
    min_change_pct: float | None = None
    max_change_pct: float | None = None
    exchange: str | None = None           # "SSE" / "SZSE" / "BSE" / None

    # Factor weights
    factor_weights: dict[str, float] | None = None

    # Output
    top_n: int = 50
    enrich_fundamentals: bool = False


@router.post("/run")
async def screen_stocks(req: ScreenerRequest):
    """Run multi-factor stock screening with custom weights."""
    config = ScreenerConfig(
        min_price=req.min_price,
        max_price=req.max_price,
        min_pe=req.min_pe,
        max_pe=req.max_pe,
        min_pb=req.min_pb,
        max_pb=req.max_pb,
        min_market_cap=req.min_market_cap,
        max_market_cap=req.max_market_cap,
        min_change_pct=req.min_change_pct,
        max_change_pct=req.max_change_pct,
        exchange=req.exchange,
        factor_weights=req.factor_weights or {},
        top_n=req.top_n,
        enrich_fundamentals=req.enrich_fundamentals,
    )
    return await run_screener(config)


@router.post("/run-strategy/{strategy_key}")
async def run_named_strategy(strategy_key: str, exchange: str | None = None, top_n: int | None = None):
    """Run a YAML screening strategy by key.

    strategy_key: the YAML strategy name (with or without 'yaml_' prefix).
    """
    from quantforge.strategy.yaml_registry import registry

    # Normalise key: strip legacy 'yaml_' prefix if present
    name = strategy_key[5:] if strategy_key.startswith("yaml_") else strategy_key

    config = registry.get_screener_config(name)
    if config is None:
        raise HTTPException(
            status_code=404,
            detail=f"策略 '{name}' 不存在或未配置 screener 选股参数"
        )
    if top_n:
        config.top_n = top_n
    if exchange:
        config.exchange = exchange

    sc = registry.as_screener_strategy(name) or {}
    result = await run_screener(config)
    result["strategy"] = {
        "key":            f"yaml_{name}",
        "display_name":   sc.get("display_name", name),
        "rationale":      sc.get("rationale", ""),
        "suitable":       sc.get("suitable", ""),
        "risk":           sc.get("risk", ""),
        "holding_period": sc.get("holding_period", ""),
        "yaml_name":      name,
    }
    return result


@router.get("/strategies")
def get_strategies():
    """Return all YAML-defined screening strategies."""
    from quantforge.strategy.yaml_registry import registry
    from quantforge.screener.strategies import CATEGORY_META

    strategies = []
    for name in registry.names():
        sc = registry.as_screener_strategy(name)
        if not sc:
            continue
        cat = sc.get("category", "")
        cat_meta = CATEGORY_META.get(cat, {})
        strategies.append({
            "key":            f"yaml_{name}",
            "display_name":   sc["display_name"],
            "category":       cat,
            "category_label": cat_meta.get("label", cat or "其他"),
            "category_color": sc.get("category_color") or cat_meta.get("color", "#6366f1"),
            "category_order": cat_meta.get("order", 99),
            "icon":           sc.get("icon", "file-text"),
            "description":    sc.get("description", ""),
            "rationale":      sc.get("rationale", ""),
            "suitable":       sc.get("suitable", ""),
            "risk":           sc.get("risk", ""),
            "holding_period": sc.get("holding_period", ""),
            "top_n":          sc.get("top_n", 30),
            "yaml_name":      name,
        })

    # Sort by category order then display_name
    strategies.sort(key=lambda s: (s["category_order"], s["display_name"]))
    return strategies


class AIGenerateRequest(BaseModel):
    description: str


@router.post("/ai-generate")
async def ai_generate_strategy(req: AIGenerateRequest):
    """Use AI to generate a screener config from natural language description."""
    import json
    from quantforge.api.ai_client import chat

    factor_names = list(FACTOR_REGISTRY.keys())

    system = (
        "你是一名专业量化金融助手，专注于A股选股。"
        "根据用户的自然语言描述，生成JSON选股配置。"
        "只返回合法JSON，不要任何解释或代码块标记。"
    )
    user_msg = f"""用户的选股需求：{req.description}

生成一个JSON对象，包含以下可选字段（不需要约束的字段直接省略）：
- min_price, max_price: float（股价区间，元）
- min_pe, max_pe: float（市盈率区间）
- min_pb, max_pb: float（市净率区间）
- min_market_cap, max_market_cap: float（市值，单位亿元）
- exchange: "SSE" | "SZSE" | "BSE" | null
- top_n: integer 10-100
- factor_weights: dict，键来自 {factor_names}，值为0-10整数（0=禁用）

因子含义：
- value: PE值因子（PE低=高分）
- pb: PB值因子（PB低=高分）
- momentum: 价格动量（近期上涨=高分）
- size: 小市值偏好
- large_cap: 大市值偏好
- liquidity: 流动性/换手率
- quality: 盈利质量
- graham: 格雷厄姆价值
- value_composite: 综合价值
- float_ratio: 流通比例

只返回JSON对象，不要任何其他内容。"""

    try:
        raw = await chat(system, user_msg, max_tokens=1024)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        config = json.loads(raw.strip())
        return {"config": config, "description": req.description}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI生成失败: {e}")


# ── Summary / cache endpoints ──────────────────────────────────────────────────

@router.get("/summary")
async def get_summary():
    """Return cached summary of all strategy results (< 24h old)."""
    from quantforge.screener.cache import get_cached, cache_info
    cached = get_cached()
    if cached:
        return {**cached, "from_cache": True, "info": cache_info()}
    return {"from_cache": False, "results": {}, "info": cache_info()}


@router.post("/summary/run")
async def run_summary(background_tasks: BackgroundTasks, force: bool = False):
    """Run all strategies and cache results."""
    from quantforge.screener.cache import get_cached, run_all, cache_info

    if not force:
        cached = get_cached()
        if cached:
            return {**cached, "from_cache": True, "info": cache_info()}

    result = await run_all()
    return {**result, "from_cache": False, "info": cache_info()}


@router.get("/factors")
def list_factors():
    """Return available factor definitions."""
    return [
        {
            "name": name,
            "label": meta["label"],
            "description": meta["description"],
            "default_weight": meta["default_weight"],
            "data_source": meta.get("data_source", "实时行情"),
        }
        for name, meta in FACTOR_REGISTRY.items()
    ]
