"""Unified AI client — OpenAI-compatible, backed by ByteDance ARK.

Configure via (priority order):
  1. data/cache/llm_config.json  — runtime config saved via /api/llm-stats/config
  2. Environment variables: ARK_API_KEY, ARK_BASE_URL, AI_MODEL
  3. Hardcoded defaults

LLM cost tracking is stored in data/cache/llm_costs.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import datetime as _dt
from pathlib import Path

_DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
_DEFAULT_API_KEY  = "0b06d2ae-7a7a-45a2-acf6-1c16c3f3c55c"
_DEFAULT_MODEL    = "Doubao-Seed-2.0-Code"

_COST_FILE   = Path("data/cache/llm_costs.json")
_CONFIG_FILE = Path("data/cache/llm_config.json")


def _load_config() -> dict:
    """Load runtime config from JSON file (written by /api/llm-stats/config PUT)."""
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg: dict) -> None:
    """Persist config to JSON file."""
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

# Approximate cost per 1K tokens in USD (adjust as needed)
_COST_PER_1K_INPUT  = 0.001
_COST_PER_1K_OUTPUT = 0.002


def get_base_url() -> str:
    cfg = _load_config()
    return cfg.get("base_url") or os.getenv("ARK_BASE_URL", _DEFAULT_BASE_URL)


def get_api_key() -> str:
    cfg = _load_config()
    return cfg.get("api_key") or os.getenv("ARK_API_KEY", _DEFAULT_API_KEY)


def get_model() -> str:
    cfg = _load_config()
    return cfg.get("model") or os.getenv("AI_MODEL") or _DEFAULT_MODEL


def get_config() -> dict:
    """Return current effective config (for display, api_key masked)."""
    cfg = _load_config()
    key = cfg.get("api_key") or os.getenv("ARK_API_KEY", _DEFAULT_API_KEY)
    return {
        "base_url": cfg.get("base_url") or os.getenv("ARK_BASE_URL", _DEFAULT_BASE_URL),
        "api_key":  key[:8] + "****" + key[-4:] if len(key) > 12 else "****",
        "api_key_raw": key,
        "model":    cfg.get("model") or os.getenv("AI_MODEL") or _DEFAULT_MODEL,
    }


def build_client():
    """Return a configured OpenAI-compatible client."""
    from openai import OpenAI
    return OpenAI(api_key=get_api_key(), base_url=get_base_url())


# ── Cost tracking ──────────────────────────────────────────────────────────────

def _load_costs() -> dict:
    if _COST_FILE.exists():
        try:
            return json.loads(_COST_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0, "calls": []}


def _save_costs(data: dict) -> None:
    try:
        _COST_FILE.parent.mkdir(parents=True, exist_ok=True)
        _COST_FILE.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:
        pass


def _record_cost(caller: str, model: str, input_tokens: int, output_tokens: int) -> None:
    cost_usd = (input_tokens / 1000) * _COST_PER_1K_INPUT + (output_tokens / 1000) * _COST_PER_1K_OUTPUT
    data = _load_costs()
    data["total_input_tokens"]  = data.get("total_input_tokens", 0) + input_tokens
    data["total_output_tokens"] = data.get("total_output_tokens", 0) + output_tokens
    data["total_cost_usd"]      = round(data.get("total_cost_usd", 0.0) + cost_usd, 6)
    entry = {
        "ts":            _dt.datetime.now().isoformat(timespec="seconds"),
        "caller":        caller,
        "model":         model,
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "cost_usd":      round(cost_usd, 6),
    }
    calls: list = data.setdefault("calls", [])
    calls.append(entry)
    # Keep only last 500 call records to bound file size
    if len(calls) > 500:
        data["calls"] = calls[-500:]
    _save_costs(data)


def get_llm_stats() -> dict:
    """Return aggregated LLM usage statistics."""
    data = _load_costs()
    calls = data.get("calls", [])
    # Per-caller summary
    by_caller: dict[str, dict] = {}
    for c in calls:
        key = c.get("caller", "unknown")
        if key not in by_caller:
            by_caller[key] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        by_caller[key]["calls"] += 1
        by_caller[key]["input_tokens"]  += c.get("input_tokens", 0)
        by_caller[key]["output_tokens"] += c.get("output_tokens", 0)
        by_caller[key]["cost_usd"]      = round(by_caller[key]["cost_usd"] + c.get("cost_usd", 0.0), 6)
    return {
        "total_calls":         len(calls),
        "total_input_tokens":  data.get("total_input_tokens", 0),
        "total_output_tokens": data.get("total_output_tokens", 0),
        "total_cost_usd":      data.get("total_cost_usd", 0.0),
        "by_caller":           by_caller,
        "recent_calls":        calls[-20:],
    }


# ── Chat interface ─────────────────────────────────────────────────────────────

async def chat(
    system: str,
    user: str,
    max_tokens: int = 1024,
    caller: str = "unknown",
    images: list[str] | None = None,
) -> str:
    """Send a chat message and return the assistant reply text.

    Args:
        system: System prompt.
        user: User message.
        max_tokens: Max response tokens.
        caller: Label for cost tracking (e.g. 'ai_picks', 'yaml_strategy').
        images: Optional list of base64-encoded images for Vision LLM calls.
    """
    client = build_client()
    model = get_model()

    def _call():
        # Build user message content
        if images:
            content = [{"type": "text", "text": user}]
            for img_b64 in images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                })
        else:
            content = user

        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": content},
            ],
        )
        return resp

    resp = await asyncio.to_thread(_call)
    text = resp.choices[0].message.content or ""

    # Record cost
    usage = getattr(resp, "usage", None)
    if usage:
        _record_cost(
            caller=caller,
            model=model,
            input_tokens=getattr(usage, "prompt_tokens", 0),
            output_tokens=getattr(usage, "completion_tokens", 0),
        )

    return text
