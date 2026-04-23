"""YAML natural-language strategy endpoints.

Endpoints:
  GET    /api/yaml-strategy/list          → list available strategies
  GET    /api/yaml-strategy/template      → starter YAML template
  GET    /api/yaml-strategy/{name}        → get full strategy definition (raw YAML text)
  POST   /api/yaml-strategy/             → create new strategy from YAML text
  PUT    /api/yaml-strategy/{name}        → overwrite strategy YAML
  DELETE /api/yaml-strategy/{name}        → delete strategy file
  POST   /api/yaml-strategy/generate      → AI convert description → YAML
  POST   /api/yaml-strategy/analyze       → run strategy LLM analysis on a symbol
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from quantforge.strategy.yaml_strategy import analyze, list_strategies, load_strategy
from quantforge.strategy.yaml_registry import registry

_YAML_DIR = Path("strategies/yaml")
router = APIRouter(prefix="/yaml-strategy", tags=["yaml-strategy"])


# ── helpers ────────────────────────────────────────────────────────────────────

def _safe_name(name: str) -> str:
    """Sanitize strategy name to a safe filename stem."""
    return re.sub(r"[^\w\-]", "_", name).strip("_").lower()


def _yaml_path(name: str) -> Path:
    return _YAML_DIR / f"{_safe_name(name)}.yaml"


def _validate_yaml(text: str) -> dict:
    """Parse and basic-validate YAML. Raises HTTPException on failure."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML解析失败: {e}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="YAML必须是一个映射对象")
    if not data.get("name"):
        raise HTTPException(status_code=400, detail="YAML缺少必填字段 'name'")
    return data


# ── request models ─────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    symbol: str
    strategy_name: str


class GenerateRequest(BaseModel):
    description: str        # natural language description of the strategy
    name: str | None = None # optional suggested name


class SaveRequest(BaseModel):
    name: str          # logical name / filename stem
    content: str       # raw YAML text


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/list")
async def get_list():
    """List all available YAML strategies with metadata."""
    return {"strategies": list_strategies()}


@router.get("/template")
async def get_template():
    """Return a starter YAML template for a new strategy."""
    tmpl = """\
name: 我的新策略
description: |
  在这里用自然语言描述策略逻辑，例如：
  当股价突破20日均线且成交量放大时买入，跌破10日均线时卖出。

market_condition: 适合震荡上行的市场环境

entry_conditions:
  - 收盘价突破20日均线
  - 当日成交量 > 5日均量的1.5倍
  - MACD金叉（DIF上穿DEA）

exit_conditions:
  - 收盘价跌破10日均线
  - 涨幅超过15%止盈
  - 跌幅超过7%止损

risk_management:
  stop_loss_pct: 7
  take_profit_pct: 15
  max_hold_days: 20

screener:
  category: momentum
  filters:
    min_price: 3.0
    max_pe: 80.0
    min_pe: 5.0
  factor_weights:
    momentum: 8
    liquidity: 5
    value: 2
    quality: 3
    volatility: 2

execution:
  strategy_class: dual_ma
  strategy_params:
    fast_period: 10
    slow_period: 20
"""
    return {"template": tmpl}


@router.get("/{name}")
async def get_strategy(name: str):
    """Get full YAML strategy — returns both parsed dict and raw text."""
    path = _yaml_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"策略 '{name}' 不存在")
    raw = path.read_text(encoding="utf-8")
    parsed = load_strategy(name) or {}
    return {"name": name, "content": raw, "parsed": parsed}


@router.post("/")
async def create_strategy(req: SaveRequest):
    """Create a new YAML strategy file."""
    _YAML_DIR.mkdir(parents=True, exist_ok=True)
    stem = _safe_name(req.name)
    path = _YAML_DIR / f"{stem}.yaml"
    if path.exists():
        raise HTTPException(status_code=409, detail=f"策略 '{stem}' 已存在，请用PUT更新")
    _validate_yaml(req.content)
    path.write_text(req.content, encoding="utf-8")
    registry._load_all()   # refresh singleton
    return {"status": "created", "name": stem}


@router.put("/{name}")
async def update_strategy(name: str, req: SaveRequest):
    """Overwrite an existing YAML strategy file."""
    path = _yaml_path(name)
    _YAML_DIR.mkdir(parents=True, exist_ok=True)
    _validate_yaml(req.content)
    path.write_text(req.content, encoding="utf-8")
    registry._load_all()   # refresh singleton
    return {"status": "updated", "name": _safe_name(name)}


@router.delete("/{name}")
async def delete_strategy(name: str):
    """Delete a YAML strategy file."""
    path = _yaml_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"策略 '{name}' 不存在")
    path.unlink()
    registry._load_all()
    return {"status": "deleted", "name": _safe_name(name)}


_GENERATE_SYSTEM = """\
你是一名专业的A股量化策略设计师。用户会用中文描述一个交易策略，你需要将其转换为结构化YAML配置文件。

YAML必须包含以下字段（按照示例格式）：
- name: 策略名称（中文）
- description: 策略描述（多行）
- market_condition: 适合的市场环境
- entry_conditions: 买入条件列表（中文，具体可操作）
- exit_conditions: 卖出条件列表
- risk_management: 止损止盈参数（stop_loss_pct, take_profit_pct, max_hold_days）
- screener.category: momentum/mean_reversion/value/growth 之一
- screener.filters: min_price, max_pe, min_pe等
- screener.factor_weights: momentum/liquidity/value/quality/volatility（0-10整数）
- execution.strategy_class: dual_ma/rsi_mean_revert/bollinger_breakout之一（选最匹配的）
- execution.strategy_params: 对应策略的参数

只输出纯YAML文本，不要有任何markdown代码块标记，不要有解释文字。
"""


@router.post("/generate")
async def generate_from_description(req: GenerateRequest):
    """Use LLM to convert a natural language strategy description into YAML."""
    from quantforge.api.ai_client import chat
    if not req.description.strip():
        raise HTTPException(status_code=400, detail="description不能为空")

    prompt = f"请将以下策略描述转换为YAML配置：\n\n{req.description}"
    try:
        raw = await chat(
            system=_GENERATE_SYSTEM,
            user=prompt,
            caller="yaml_generate",
            max_tokens=2000,
        )
        # Strip any accidental markdown fences
        yaml_text = raw.strip()
        if yaml_text.startswith("```"):
            lines = yaml_text.split("\n")
            yaml_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        # Validate parseable
        _validate_yaml(yaml_text)

        # Inject name if provided and not in YAML
        if req.name and "name:" not in yaml_text:
            yaml_text = f"name: {req.name}\n" + yaml_text

        return {"yaml": yaml_text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI生成失败: {e}")


@router.post("/analyze")
async def analyze_symbol(req: AnalyzeRequest):
    """Run a YAML strategy against a symbol using LLM analysis."""
    if not req.symbol or not req.strategy_name:
        raise HTTPException(status_code=400, detail="symbol 和 strategy_name 不能为空")
    result = await analyze(req.symbol, req.strategy_name)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result
