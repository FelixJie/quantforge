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
    base_url: str = ""
    api_key: str = ""
    model: str = ""


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
    # Return masked key for display
    return {
        "base_url": cfg["base_url"],
        "api_key":  cfg["api_key"],   # masked
        "model":    cfg["model"],
    }


@router.put("/config")
async def update_llm_config(req: ConfigRequest):
    """Save AI API configuration. Empty fields keep existing values."""
    from quantforge.api.ai_client import _load_config
    existing = _load_config()
    if req.base_url.strip():
        existing["base_url"] = req.base_url.strip()
    if req.api_key.strip() and not req.api_key.strip().endswith("****"):
        existing["api_key"] = req.api_key.strip()
    if req.model.strip():
        existing["model"] = req.model.strip()
    save_config(existing)
    return {"status": "saved", "model": existing.get("model", ""), "base_url": existing.get("base_url", "")}
