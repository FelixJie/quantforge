"""Prediction tracking and verification endpoints.

Endpoints:
  GET    /api/predictions/            → list predictions (filterable)
  GET    /api/predictions/stats       → accuracy + grouped breakdowns + benchmark
  GET    /api/predictions/{id}/detail → single prediction settlement + per-day path
  POST   /api/predictions/verify      → trigger (re)settlement in background
  GET    /api/predictions/verify/status → background verify progress (cross-worker)
  POST   /api/predictions/backfill-strategies
  DELETE /api/predictions/            → bulk delete by id list
"""

from __future__ import annotations

import datetime as _dt

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from quantforge.prediction.tracker import PredictionTracker
from quantforge.data.storage import db_cache as _db

router = APIRouter(prefix="/predictions", tags=["predictions"])

_VERIFY_STATUS_KEY = "predictions:verify:status"


class DeleteRequest(BaseModel):
    ids: list[str]


class VerifyRequest(BaseModel):
    date: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    force: bool = False


@router.get("/")
async def list_predictions(
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    verified: bool | None = None,
    pick_strategy: str | None = None,
    limit: int = 200,
):
    """List predictions, optionally filtered by date / range / status / 荐股策略."""
    preds = PredictionTracker.get_all()
    if date:
        preds = [p for p in preds if p.get("date") == date]
    if date_from:
        preds = [p for p in preds if p.get("date", "") >= date_from]
    if date_to:
        preds = [p for p in preds if p.get("date", "") <= date_to]
    if verified is not None:
        preds = [p for p in preds if p.get("verified") == verified]
    if pick_strategy:
        preds = [p for p in preds if (p.get("pick_strategy") or "momentum") == pick_strategy]
    preds.sort(key=lambda p: p.get("date", ""), reverse=True)
    return {"predictions": preds[:limit], "total": len(preds)}


@router.get("/stats")
async def get_stats(date_from: str | None = None, date_to: str | None = None,
                    pick_strategy: str | None = None):
    """Accuracy + grouped breakdowns (荐股策略/命中策略/置信度/风险) + benchmark。"""
    return PredictionTracker.get_stats(date_from=date_from, date_to=date_to,
                                       pick_strategy=pick_strategy)


@router.get("/recent-winrate")
async def get_recent_winrate(pick_strategy: str | None = None, days: int = 1):
    """昨日(默认)或最近 N 日推荐股票的胜率+平均收益——首页「昨日策略命中率」卡专用。

    ``days=1`` 为昨日(最近一个过去推荐日)；``days>1`` 合并近 N 自然日推荐统计。
    """
    return PredictionTracker.get_recent_winrate(pick_strategy=pick_strategy, days=days)


@router.get("/strategy-winrate")
async def get_strategy_winrate(pick_strategy: str | None = None):
    """某策略「今日胜率」多周期面板：实时(今日开盘价→现价) + 持有 3/7/30 交易日聚合。

    AI 荐股页每个策略 Tab 与首页「策略命中率」卡共用。``pick_strategy`` 省略=合并全部策略。
    """
    return PredictionTracker.get_strategy_winrate(pick_strategy=pick_strategy)


@router.get("/verify/status")
async def verify_status():
    """Background verification progress (stored in DB → visible across workers)."""
    return _db.get_stale(_VERIFY_STATUS_KEY) or {"running": False, "done": 0, "total": 0}


@router.get("/{pred_id}/detail")
async def prediction_detail(pred_id: str):
    """Single prediction: settlement summary + per-day path + context bars.

    Runs the SAME path-based engine as the list, so详情与列表结果一致。
    """
    detail = PredictionTracker.get_detail(pred_id)
    if not detail:
        raise HTTPException(status_code=404, detail="预测记录不存在")
    return detail


def _run_verify(date_from, date_to, force):
    """Background entry (runs in FastAPI's worker thread): drive the async
    settlement coroutine and mirror progress into the DB for cross-worker reads."""
    import asyncio

    def _progress(done, total):
        _db.set(_VERIFY_STATUS_KEY,
                {"running": done < total, "done": done, "total": total,
                 "updated_at": _dt.datetime.now().isoformat(timespec="seconds")},
                3600, "predictions")

    _progress(0, 0)
    try:
        count = asyncio.run(
            PredictionTracker.verify_pending(date_from=date_from, date_to=date_to,
                                             force=force, progress_cb=_progress)
        )
    except Exception as exc:
        from loguru import logger
        logger.warning(f"predictions verify failed: {exc}")
        count = -1
    _db.set(_VERIFY_STATUS_KEY,
            {"running": False, "settled": max(count, 0),
             "finished_at": _dt.datetime.now().isoformat(timespec="seconds")},
            3600, "predictions")


@router.post("/verify")
async def trigger_verify(req: VerifyRequest, background_tasks: BackgroundTasks):
    """Trigger (re)settlement in background.

    - No body → settle all pending up to today
    - date → only that date
    - date_from / date_to → settle pending in range
    - force → re-settle already-frozen rows too
    """
    today     = _dt.date.today().isoformat()
    date_from = req.date or req.date_from
    date_to   = req.date or req.date_to or today

    background_tasks.add_task(_run_verify, date_from, date_to, req.force)

    if req.date:
        msg = f"正在验证 {req.date} 的预测"
    elif req.date_from or req.date_to:
        msg = f"正在验证 {date_from or '最早'} ~ {date_to} 的预测"
    else:
        msg = f"正在验证所有待验证预测（截至 {today}）"
    return {"status": "started", "message": msg}


async def daily_verify_scheduler():
    """每日收盘后自动结算所有待验证预测，用户进来即最新。

    启动后先补一次（覆盖停机期间到期的窗口），之后每天 16:00 复算。结算引擎
    幂等：已定格的不动，仅推进仍在窗口内的。走专属线程池不阻塞事件循环。
    """
    import asyncio

    async def _settle_all():
        try:
            def _progress(done, total):
                _db.set(_VERIFY_STATUS_KEY,
                        {"running": done < total, "done": done, "total": total,
                         "updated_at": _dt.datetime.now().isoformat(timespec="seconds")},
                        3600, "predictions")
            n = await PredictionTracker.verify_pending(progress_cb=_progress)
            from loguru import logger
            logger.info(f"daily_verify_scheduler: settled {n} predictions")
        except Exception as exc:
            from loguru import logger
            logger.warning(f"daily_verify_scheduler failed: {exc}")

    await asyncio.sleep(30)          # 让启动其它预热先跑
    await _settle_all()
    while True:
        now = _dt.datetime.now()
        nxt = now.replace(hour=16, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += _dt.timedelta(days=1)
        await asyncio.sleep(max(60, (nxt - now).total_seconds()))
        await _settle_all()


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
