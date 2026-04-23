"""Portfolio and paper-trading endpoints."""

from __future__ import annotations

import base64
import json
import uuid

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from loguru import logger

from quantforge.api.deps import get_portfolio_manager
from quantforge.core.constants import Exchange

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ── Request / response models ─────────────────────────────────────────────────

class StartSessionRequest(BaseModel):
    strategy: str
    symbols: list[str]
    exchange: str = "SZSE"
    initial_capital: float = 1_000_000.0
    params: dict = {}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
async def get_portfolio():
    """Aggregate view across all live paper-trading sessions."""
    mgr = get_portfolio_manager()
    return mgr.aggregate_summary()


@router.get("/sessions")
async def list_sessions():
    """List all paper-trading sessions."""
    mgr = get_portfolio_manager()
    return mgr.list_sessions()


@router.post("/sessions")
async def start_session(req: StartSessionRequest):
    """Start a new paper-trading session."""
    mgr = get_portfolio_manager()
    try:
        exc = Exchange(req.exchange.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid exchange: {req.exchange}")

    session_id = str(uuid.uuid4())[:8]
    try:
        session = await mgr.start_session(
            session_id=session_id,
            strategy_module_path=req.strategy,
            symbols=req.symbols,
            exchange=exc,
            initial_capital=req.initial_capital,
            strategy_params=req.params or {},
        )
    except (ImportError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return session.summary()


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get a single paper-trading session."""
    mgr = get_portfolio_manager()
    session = mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return session.summary()


@router.get("/sessions/{session_id}/detail")
async def get_session_detail(session_id: str):
    """Get full session detail: trades, orders, and strategy logs."""
    mgr = get_portfolio_manager()
    session = mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return session.detail()


@router.delete("/sessions/{session_id}")
async def stop_session(session_id: str):
    """Stop (pause) a paper-trading session."""
    mgr = get_portfolio_manager()
    session = mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    mgr.stop_session(session_id)
    return {"status": "stopped", "session_id": session_id}


@router.post("/sessions/{session_id}/resume")
async def resume_session(session_id: str):
    """Resume a stopped paper-trading session."""
    mgr = get_portfolio_manager()
    try:
        session = await mgr.resume_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return session.summary()


@router.get("/quotes")
async def get_quotes():
    """Return latest cached real-time quotes from all subscribed symbols."""
    mgr = get_portfolio_manager()
    rt = mgr._rt_stream
    if rt is None:
        return {"quotes": {}, "note": "No active session — quotes not yet available"}
    return {"quotes": rt.get_all_quotes()}


# ── Vision LLM import ─────────────────────────────────────────────────────────

_VISION_SYSTEM_PROMPT = """你是一个持仓数据提取助手。
用户会发送一张持仓截图（来自券商App、交易软件或Excel截图等）。
请从图片中提取所有持仓记录，输出为JSON格式。

输出格式：
{
  "holdings": [
    {
      "code": "股票代码（6位，如000001）",
      "name": "股票名称",
      "volume": 持仓数量（股，整数）,
      "cost_price": 成本价（元，浮点数）,
      "current_price": 当前价（元，浮点数，如果图中有的话）,
      "market_value": 市值（元，浮点数，如果图中有的话）,
      "profit_loss": 盈亏（元，浮点数，如果图中有的话）,
      "confidence": 置信度0-100整数
    }
  ],
  "total_market_value": 总市值（如果图中有的话，否则null）,
  "notes": "备注（如图片质量说明、无法识别的字段等）"
}

注意事项：
1. 股票代码必须是6位数字，沪市600/601/603开头，深市000/002/300开头
2. 如果无法识别某字段，填null而不是猜测
3. confidence反映你对整条记录识别准确性的判断
"""


@router.post("/import/image")
async def import_from_image(file: UploadFile = File(...)):
    """Import holdings from a screenshot using Vision LLM.

    Upload a JPG/PNG screenshot of your brokerage holdings page.
    The Vision LLM will extract position data with confidence scores.
    """
    # Validate file type
    content_type = file.content_type or ""
    if not any(t in content_type for t in ("image/jpeg", "image/png", "image/webp")):
        raise HTTPException(
            status_code=400,
            detail="Only JPG/PNG/WebP images are supported"
        )

    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 10MB)")

    img_b64 = base64.b64encode(raw).decode("utf-8")

    try:
        from quantforge.api.ai_client import chat
        raw_response = await chat(
            system=_VISION_SYSTEM_PROMPT,
            user="请从这张持仓截图中提取所有持仓数据。",
            max_tokens=2000,
            caller="vision_import",
            images=[img_b64],
        )
        text = raw_response.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        if text.endswith("```"):
            text = text[:text.rfind("```")].strip()

        result = json.loads(text)
        holdings = result.get("holdings", [])

        # Annotate confidence tiers
        for h in holdings:
            conf = h.get("confidence", 0)
            h["review_required"] = conf < 80

        return {
            "status":           "success",
            "holdings":         holdings,
            "total_market_value": result.get("total_market_value"),
            "notes":            result.get("notes", ""),
            "review_count":     sum(1 for h in holdings if h.get("review_required")),
        }

    except json.JSONDecodeError as e:
        logger.warning(f"vision_import: JSON parse failed: {e}")
        raise HTTPException(status_code=422, detail="AI无法从图片中提取持仓数据，请检查图片清晰度")
    except Exception as e:
        logger.warning(f"vision_import: error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
