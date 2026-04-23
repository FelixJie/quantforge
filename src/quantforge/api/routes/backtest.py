"""Backtest submission and result retrieval."""

from __future__ import annotations

import asyncio
import importlib
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from quantforge.api.deps import get_backtest_engine
from quantforge.backtest.engine import BacktestEngine
from quantforge.core.constants import Exchange, Interval

router = APIRouter(prefix="/backtest", tags=["backtest"])

# In-memory job store (replace with DB in production)
_jobs: dict[str, dict] = {}


class BacktestRequest(BaseModel):
    strategy: str           # e.g. "strategies.examples.dual_ma_strategy.DualMAStrategy"
    symbols: list[str]
    start: str              # "YYYY-MM-DD"
    end: str
    exchange: str | None = None   # optional — auto-detected from symbol prefix
    initial_capital: float = 1_000_000.0
    params: dict[str, Any] = {}
    enable_risk: bool = True


def _load_strategy_cls(strategy_path: str):
    """Load strategy class by dotted module path."""
    # Ensure project root in path
    project_root = Path(".")
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    parts = strategy_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid strategy path: {strategy_path}")
    module = importlib.import_module(parts[0])
    cls = getattr(module, parts[1], None)
    if cls is None:
        raise ValueError(f"Class {parts[1]} not found in {parts[0]}")
    return cls


async def _run_backtest(job_id: str, req: BacktestRequest, engine: BacktestEngine):
    _jobs[job_id]["status"] = "running"
    try:
        strategy_cls = _load_strategy_cls(req.strategy)
        from quantforge.data.feed.efinance_feed import detect_exchange
        if req.exchange:
            exchange = Exchange(req.exchange.upper())
        else:
            exchange = detect_exchange(req.symbols[0]) if req.symbols else Exchange.SZSE
        start = datetime.strptime(req.start, "%Y-%m-%d")
        end = datetime.strptime(req.end, "%Y-%m-%d")

        result = await engine.run(
            strategy_cls=strategy_cls,
            symbols=req.symbols,
            start=start,
            end=end,
            exchange=exchange,
            interval=Interval.DAILY,
            initial_capital=req.initial_capital,
            params=req.params,
            download_missing=False,
            enable_risk=req.enable_risk,
        )

        # Generate HTML report and store it
        try:
            from quantforge.backtest.report import generate_report
            from quantforge.api.routes.optimizer import store_report
            html = generate_report(result)
            store_report(job_id, html)
        except Exception:
            pass  # report generation is non-critical

        # Build serializable trades list
        trades_list = []
        for t in result.trades:
            try:
                trades_list.append({
                    "date": t.datetime.strftime("%Y-%m-%d") if t.datetime else None,
                    "time": t.datetime.strftime("%H:%M") if t.datetime else None,
                    "symbol": t.symbol,
                    "direction": t.direction.value if hasattr(t.direction, "value") else str(t.direction),
                    "price": round(float(t.price), 3),
                    "volume": float(t.volume),
                })
            except Exception:
                continue

        # Build round-trips (buy→sell pairs) for P&L per trade
        round_trips = []
        opens: list = []
        for tr in trades_list:
            if tr["direction"] == "long":
                opens.append(tr)
            elif tr["direction"] == "short" and opens:
                buy = opens.pop(0)
                pnl_pct = (tr["price"] - buy["price"]) / buy["price"] * 100 if buy["price"] else 0
                round_trips.append({
                    "entry_date": buy["date"], "exit_date": tr["date"],
                    "entry_price": buy["price"], "exit_price": tr["price"],
                    "volume": tr["volume"], "pnl_pct": round(pnl_pct, 2),
                })

        # Extra metrics: avg/max hold days, best/worst trade
        hold_days_list = []
        for rt in round_trips:
            try:
                d1 = datetime.strptime(rt["entry_date"], "%Y-%m-%d")
                d2 = datetime.strptime(rt["exit_date"], "%Y-%m-%d")
                hold_days_list.append((d2 - d1).days)
            except Exception:
                pass
        avg_hold = round(sum(hold_days_list) / len(hold_days_list), 1) if hold_days_list else 0
        max_hold = max(hold_days_list) if hold_days_list else 0
        pnl_pcts = [rt["pnl_pct"] for rt in round_trips]
        best_trade  = max(pnl_pcts) if pnl_pcts else 0
        worst_trade = min(pnl_pcts) if pnl_pcts else 0

        # Load K-line bars for the primary symbol
        bars_list = []
        if req.symbols:
            try:
                from quantforge.core.constants import Interval
                sym0 = req.symbols[0]
                start_dt = datetime.strptime(req.start, "%Y-%m-%d")
                end_dt   = datetime.strptime(req.end,   "%Y-%m-%d")
                df_bars = engine._data_manager.load_bars(sym0, Interval("1d"), start_dt, end_dt)
                if not df_bars.empty:
                    bars_list = (
                        df_bars[["datetime", "open", "high", "low", "close", "volume"]]
                        .assign(date=df_bars["datetime"].dt.strftime("%Y-%m-%d"))
                        .rename(columns={"datetime": "_dt"})
                        [["date", "open", "high", "low", "close", "volume"]]
                        .round(3)
                        .to_dict(orient="records")
                    )
            except Exception:
                pass

        # Store result
        _jobs[job_id].update({
            "status": "done",
            "metrics": result.metrics,
            "equity_curve": result.equity_curve[["date", "equity"]].assign(
                date=lambda df: df["date"].dt.strftime("%Y-%m-%d")
            ).to_dict(orient="records"),
            "trade_count": len(result.trades),
            "has_report": True,
            "trades": trades_list,
            "round_trips": round_trips,
            "bars": bars_list,
            "summary": {
                "total_return": result.total_return,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "final_equity": result.final_equity,
                "avg_hold_days": avg_hold,
                "max_hold_days": max_hold,
                "best_trade_pct": best_trade,
                "worst_trade_pct": worst_trade,
            },
        })
    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error"] = str(e)


@router.post("/run")
async def submit_backtest(
    req: BacktestRequest,
    background_tasks: BackgroundTasks,
    engine: BacktestEngine = Depends(get_backtest_engine),
):
    """Submit a backtest job. Returns job_id for polling."""
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "strategy": req.strategy,
        "symbols": req.symbols,
        "created_at": datetime.now().isoformat(),
    }
    background_tasks.add_task(_run_backtest, job_id, req, engine)
    return {"job_id": job_id, "status": "queued"}


@router.get("/{job_id}")
async def get_backtest_result(job_id: str):
    """Poll backtest job status and retrieve results."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@router.get("/")
async def list_jobs():
    """List all backtest jobs."""
    return [
        {k: v for k, v in job.items() if k not in ("equity_curve",)}
        for job in _jobs.values()
    ]
