"""Prediction tracking and next-day verification endpoints.

Endpoints:
  GET    /api/predictions          → list predictions (filterable)
  GET    /api/predictions/stats    → accuracy statistics
  POST   /api/predictions/verify   → trigger verification (single or date range)
  DELETE /api/predictions          → bulk delete by id list
"""

from __future__ import annotations

import datetime as _dt

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from quantforge.prediction.tracker import PredictionTracker

router = APIRouter(prefix="/predictions", tags=["predictions"])


class DeleteRequest(BaseModel):
    ids: list[str]


class VerifyRequest(BaseModel):
    date: str | None = None        # single date YYYY-MM-DD; if omitted → all pending up to yesterday
    date_from: str | None = None   # range start (inclusive)
    date_to: str | None = None     # range end (inclusive)
    force: bool = False            # re-verify already verified predictions


@router.get("/")
async def list_predictions(
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    verified: bool | None = None,
    limit: int = 200,
):
    """List predictions, optionally filtered by date / range / status."""
    preds = PredictionTracker.get_all()
    if date:
        preds = [p for p in preds if p.get("date") == date]
    if date_from:
        preds = [p for p in preds if p.get("date", "") >= date_from]
    if date_to:
        preds = [p for p in preds if p.get("date", "") <= date_to]
    if verified is not None:
        preds = [p for p in preds if p.get("verified") == verified]
    preds.sort(key=lambda p: p.get("date", ""), reverse=True)
    return {"predictions": preds[:limit], "total": len(preds)}


@router.get("/stats")
async def get_stats(
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Return accuracy statistics, optionally scoped to a date range."""
    return PredictionTracker.get_stats(date_from=date_from, date_to=date_to)


@router.post("/verify")
async def trigger_verify(req: VerifyRequest, background_tasks: BackgroundTasks):
    """Trigger verification in background.

    - No body → verify all pending predictions up to yesterday
    - date → verify only that specific date
    - date_from / date_to → verify all pending in range
    """
    today     = _dt.date.today().isoformat()
    date_from = req.date or req.date_from
    date_to   = req.date or req.date_to or today

    background_tasks.add_task(
        PredictionTracker.verify_pending,
        date_from=date_from,
        date_to=date_to,
        force=req.force,
    )

    if req.date:
        msg = f"正在验证 {req.date} 的预测"
    elif req.date_from or req.date_to:
        msg = f"正在验证 {date_from or '最早'} ~ {date_to} 的预测"
    else:
        msg = f"正在验证所有待验证预测（截至 {today}）"

    return {"status": "started", "message": msg}


@router.post("/backfill-strategies")
async def backfill_strategies():
    """Backfill hit_strategies from screener cache for predictions missing it."""
    count = PredictionTracker.backfill_hit_strategies()
    return {"backfilled": count, "message": f"已为 {count} 条预测补充策略数据"}


@router.delete("/")
async def delete_predictions(req: DeleteRequest):
    """Bulk delete predictions by ID list."""
    count = PredictionTracker.delete(req.ids)
    return {"deleted": count}
