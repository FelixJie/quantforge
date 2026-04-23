"""Optimizer and report endpoints."""

from __future__ import annotations

import asyncio
import importlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from quantforge.api.deps import get_backtest_engine
from quantforge.backtest.optimizer import ParamGrid, WalkForwardOptimizer

router = APIRouter(prefix="/optimizer", tags=["optimizer"])

# In-memory job store for optimizer runs
_opt_jobs: dict[str, dict] = {}
_reports: dict[str, str] = {}   # job_id → HTML


# ── Request models ────────────────────────────────────────────────────────────

class ParamSpec(BaseModel):
    name: str
    values: list[Any]


class GridSearchRequest(BaseModel):
    strategy: str                      # dotted module path
    symbols: list[str]
    exchange: str = "SZSE"
    start: str = "2022-01-01"
    end: str = "2023-11-30"
    initial_capital: float = 1_000_000.0
    params: list[ParamSpec]
    optimize_metric: str = "sharpe"    # sharpe | total_return | max_drawdown


class WalkForwardRequest(GridSearchRequest):
    in_sample_days: int = 365
    out_sample_days: int = 90
    step_days: int = 90


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/jobs")
async def list_jobs():
    return list(_opt_jobs.values())


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = _opt_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/grid")
async def run_grid_search(req: GridSearchRequest, background_tasks: BackgroundTasks):
    """Start a grid-search optimization job (runs in background)."""
    job_id = str(uuid.uuid4())[:8]
    _opt_jobs[job_id] = {
        "job_id": job_id,
        "type": "grid",
        "status": "queued",
        "strategy": req.strategy,
        "symbols": req.symbols,
        "metric": req.optimize_metric,
        "created_at": datetime.now().isoformat(),
        "results": [],
        "best": None,
        "error": None,
        "progress": 0,
        "total": 0,
    }
    background_tasks.add_task(_run_grid, job_id, req)
    return {"job_id": job_id, "status": "queued"}


@router.post("/walk-forward")
async def run_walk_forward(req: WalkForwardRequest, background_tasks: BackgroundTasks):
    """Start a walk-forward optimization job (runs in background)."""
    job_id = str(uuid.uuid4())[:8]
    _opt_jobs[job_id] = {
        "job_id": job_id,
        "type": "walk_forward",
        "status": "queued",
        "strategy": req.strategy,
        "symbols": req.symbols,
        "metric": req.optimize_metric,
        "created_at": datetime.now().isoformat(),
        "windows": [],
        "best_params": None,
        "mean_oos_sharpe": None,
        "mean_oos_return": None,
        "param_stability": {},
        "error": None,
        "progress": 0,
        "total": 0,
    }
    background_tasks.add_task(_run_walk_forward, job_id, req)
    return {"job_id": job_id, "status": "queued"}


@router.get("/report/{job_id}", response_class=HTMLResponse)
async def download_report(job_id: str):
    """Return the HTML report for a completed backtest job (from backtest router)."""
    html = _reports.get(job_id)
    if not html:
        raise HTTPException(status_code=404, detail="Report not found or not yet generated")
    return HTMLResponse(content=html)


@router.get("/plugins")
async def list_plugins():
    from quantforge.plugin.manager import get_plugin_manager
    return get_plugin_manager().list_plugins()


# ── Background task runners ───────────────────────────────────────────────────

async def _run_grid(job_id: str, req: GridSearchRequest) -> None:
    job = _opt_jobs[job_id]
    job["status"] = "running"

    try:
        strategy_cls = _load_strategy(req.strategy)
        engine = get_backtest_engine()
        opt = WalkForwardOptimizer(engine)

        grid = ParamGrid()
        for ps in req.params:
            grid.add(ps.name, ps.values)

        job["total"] = len(grid)

        def on_progress(done: int, total: int):
            job["progress"] = done

        from quantforge.core.constants import Exchange
        exc = Exchange(req.exchange.upper())

        results = await opt.grid_search(
            strategy_cls=strategy_cls,
            param_grid=grid,
            symbols=req.symbols,
            start=datetime.strptime(req.start, "%Y-%m-%d"),
            end=datetime.strptime(req.end, "%Y-%m-%d"),
            initial_capital=req.initial_capital,
            optimize_metric=req.optimize_metric,
            progress_callback=on_progress,
        )

        job["results"] = [
            {
                "params": r.params,
                "sharpe": round(r.sharpe, 4),
                "total_return": round(r.total_return, 4),
                "max_drawdown": round(r.max_drawdown, 4),
                "win_rate": round(r.win_rate, 4),
                "trade_count": r.trade_count,
            }
            for r in results[:50]  # cap at 50 for API response size
        ]
        job["best"] = job["results"][0] if job["results"] else None
        job["progress"] = job["total"]
        job["status"] = "done"

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


async def _run_walk_forward(job_id: str, req: WalkForwardRequest) -> None:
    job = _opt_jobs[job_id]
    job["status"] = "running"

    try:
        strategy_cls = _load_strategy(req.strategy)
        engine = get_backtest_engine()
        opt = WalkForwardOptimizer(engine)

        grid = ParamGrid()
        for ps in req.params:
            grid.add(ps.name, ps.values)

        from quantforge.core.constants import Exchange
        _ = Exchange(req.exchange.upper())

        in_days = req.in_sample_days
        out_days = req.out_sample_days
        step = req.step_days
        total_days = (
            datetime.strptime(req.end, "%Y-%m-%d")
            - datetime.strptime(req.start, "%Y-%m-%d")
        ).days
        n_windows = max(1, (total_days - in_days - out_days) // step + 1)
        job["total"] = n_windows

        def on_progress(done: int, total: int):
            job["progress"] = done

        wf_result = await opt.walk_forward(
            strategy_cls=strategy_cls,
            param_grid=grid,
            symbols=req.symbols,
            start=datetime.strptime(req.start, "%Y-%m-%d"),
            end=datetime.strptime(req.end, "%Y-%m-%d"),
            in_sample_days=in_days,
            out_sample_days=out_days,
            step_days=step,
            initial_capital=req.initial_capital,
            optimize_metric=req.optimize_metric,
            progress_callback=on_progress,
        )

        job["windows"] = [
            {
                "in_start": w.in_start.strftime("%Y-%m-%d"),
                "in_end": w.in_end.strftime("%Y-%m-%d"),
                "out_start": w.out_start.strftime("%Y-%m-%d"),
                "out_end": w.out_end.strftime("%Y-%m-%d"),
                "best_params": w.best_in_params,
                "in_sharpe": round(w.in_sharpe, 4),
                "oos_sharpe": round(w.oos_sharpe, 4),
                "oos_return": round(w.oos_return, 4),
                "oos_drawdown": round(w.oos_drawdown, 4),
                "oos_trades": w.oos_trade_count,
            }
            for w in wf_result.windows
        ]
        job["best_params"] = wf_result.best_params_overall
        job["mean_oos_sharpe"] = round(wf_result.mean_oos_sharpe, 4)
        job["mean_oos_return"] = round(wf_result.mean_oos_return, 4)
        job["mean_oos_drawdown"] = round(wf_result.mean_oos_drawdown, 4)
        job["param_stability"] = {
            k: {"mean": v.get("mean"), "stdev": v.get("stdev"), "values": v.get("values", [])}
            for k, v in wf_result.param_stability.items()
        }
        job["progress"] = n_windows
        job["status"] = "done"

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


def _load_strategy(module_path: str):
    parts = module_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid strategy path: {module_path}")
    mod = importlib.import_module(parts[0])
    return getattr(mod, parts[1])


# ── Report generation helper (called from backtest route) ─────────────────────

def store_report(job_id: str, html: str) -> None:
    _reports[job_id] = html
