"""LLM configuration and cost tracking endpoints.

Endpoints:
  GET    /api/llm-stats/          → aggregated usage and cost statistics
  DELETE /api/llm-stats/          → reset cost history
  GET    /api/llm-stats/config    → get current AI API config (key masked)
  PUT    /api/llm-stats/config    → save AI API config to JSON file
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from quantforge.api.ai_client import get_llm_stats, get_config, save_config, _COST_FILE

router = APIRouter(prefix="/llm-stats", tags=["llm-stats"])


class ConfigRequest(BaseModel):
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    # 产业链分析专用 provider（如 "claude-code" 走本地 Opus 4.8）。空字符串=清空
    # （回到全局链）；不传该字段则保留原值。用 None 区分“未传”与“显式清空”。
    research_provider: str | None = None


@router.get("/")
async def get_stats():
    """Return aggregated LLM usage and estimated cost statistics."""
    return get_llm_stats()


@router.delete("/")
async def reset_stats():
    """Reset LLM cost history."""
    stats = get_llm_stats()
    if _COST_FILE.exists():
        _COST_FILE.write_text(
            '{"total_input_tokens":0,"total_output_tokens":0,"total_cost_usd":0.0,"calls":[]}',
            encoding="utf-8",
        )
    return {
        "status": "reset",
        "archived": {
            "total_calls":        stats["total_calls"],
            "total_cost_usd":     stats["total_cost_usd"],
            "total_input_tokens": stats["total_input_tokens"],
        },
    }


@router.get("/config")
async def get_llm_config():
    """Return current AI API configuration (api_key is masked)."""
    cfg = get_config()
    from quantforge.api.ai_client import get_research_provider
    # Return masked key for display
    return {
        "provider": cfg["provider"],
        "base_url": cfg["base_url"],
        "api_key":  cfg["api_key"],   # masked
        "model":    cfg["model"],
        "presets":  cfg["presets"],
        "research_provider": get_research_provider() or "",
    }


@router.put("/config")
async def update_llm_config(req: ConfigRequest):
    """Save AI API configuration. Empty fields keep existing values.

    Selecting a known provider preset switches to it wholesale (clears any
    per-field overrides). Use provider="custom" to edit base_url/api_key/model.
    """
    from quantforge.api.ai_client import _load_config, _PRESETS
    existing = _load_config()
    # research_provider 与全局 provider 正交，需跨预设切换保留。None=未传(保留原值)，
    # ""=显式清空(回全局链)，其它=设置(如 "claude-code")。
    if req.research_provider is not None:
        rp = req.research_provider.strip()
        if rp:
            existing["research_provider"] = rp
        else:
            existing.pop("research_provider", None)
    provider = req.provider.strip()
    if provider and provider in _PRESETS:
        # Switch to a built-in preset; drop chat overrides but keep research_provider.
        existing["provider"] = provider
        for k in ("base_url", "api_key", "model"):
            existing.pop(k, None)
        return _saved(existing)
    if provider:
        existing["provider"] = provider  # e.g. "custom" / "claude-code"
    if req.base_url.strip():
        existing["base_url"] = req.base_url.strip()
    if req.api_key.strip() and not req.api_key.strip().endswith("****"):
        existing["api_key"] = req.api_key.strip()
    if req.model.strip():
        existing["model"] = req.model.strip()
    return _saved(existing)


def _saved(cfg: dict) -> dict:
    save_config(cfg)
    from quantforge.api.ai_client import get_config
    eff = get_config()
    return {"status": "saved", "provider": eff["provider"],
            "model": eff["model"], "base_url": eff["base_url"]}
