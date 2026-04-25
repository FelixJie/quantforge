"""Walk-forward optimizer for strategy parameter search.

Supports two modes:
- Grid search: exhaustive parameter combination sweep
- Walk-forward: time-series cross-validation (in-sample + out-of-sample windows)

Walk-forward overview
---------------------
  Total period: [─────────────────────────────────]
  Window 1:     [──in──|─out─]
  Window 2:          [──in──|─out─]
  Window 3:               [──in──|─out─]
  ...

For each window the best in-sample parameters are found via grid search,
then applied on the out-of-sample period.  Final score = mean out-of-sample
metric across all windows.
"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

import pandas as pd
from loguru import logger

if TYPE_CHECKING:
    from quantforge.backtest.engine import BacktestEngine


# ── Parameter space ───────────────────────────────────────────────────────────

@dataclass
class ParamGrid:
    """Defines the search space for one or more parameters.

    Example:
        grid = ParamGrid()
        grid.add("fast_period", [5, 10, 20])
        grid.add("slow_period", [30, 60, 90])
        # → 9 combinations
    """
    _params: dict[str, list[Any]] = field(default_factory=dict)

    def add(self, name: str, values: list[Any]) -> ParamGrid:
        self._params[name] = values
        return self

    def combinations(self) -> list[dict[str, Any]]:
        """Return all parameter combinations as a list of dicts."""
        if not self._params:
            return [{}]
        keys = list(self._params.keys())
        values = list(self._params.values())
        return [dict(zip(keys, combo)) for combo in itertools.product(*values)]

    def __len__(self) -> int:
        if not self._params:
            return 0
        result = 1
        for v in self._params.values():
            result *= len(v)
        return result


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class GridSearchResult:
    """Result from a single parameter combination run."""
    params: dict[str, Any]
    sharpe: float
    total_return: float
    max_drawdown: float
    win_rate: float
    trade_count: int
    start: datetime
    end: datetime

    def score(self, metric: str = "sharpe") -> float:
        return getattr(self, metric, self.sharpe)


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward optimization result."""
    windows: list["WalkForwardWindow"]
    best_params_overall: dict[str, Any]      # most frequent best params
    mean_oos_sharpe: float
    mean_oos_return: float
    mean_oos_drawdown: float
    param_stability: dict[str, Any]          # how stable each param is
    all_runs: list[GridSearchResult] = field(default_factory=list)


@dataclass
class WalkForwardWindow:
    in_start: datetime
    in_end: datetime
    out_start: datetime
    out_end: datetime
    best_in_params: dict[str, Any]
    in_sharpe: float
    oos_sharpe: float
    oos_return: float
    oos_drawdown: float
    oos_trade_count: int


# ── Optimizer ─────────────────────────────────────────────────────────────────

class WalkForwardOptimizer:
    """Runs grid search and walk-forward optimization over a strategy."""

    def __init__(self, engine: BacktestEngine):
        self._engine = engine

    # ── Grid search ───────────────────────────────────────────────────

    async def grid_search(
        self,
        strategy_cls,
        param_grid: ParamGrid,
        symbols: list[str],
        start: datetime,
        end: datetime,
        initial_capital: float = 1_000_000.0,
        optimize_metric: str = "sharpe",
        max_workers: int = 4,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[GridSearchResult]:
        """Run all parameter combinations and return sorted results."""
        combos = param_grid.combinations()
        total = len(combos)
        logger.info(f"Grid search: {total} combinations for {strategy_cls.__name__}")

        results: list[GridSearchResult] = []
        semaphore = asyncio.Semaphore(max_workers)

        async def run_one(params: dict, idx: int) -> GridSearchResult | None:
            async with semaphore:
                try:
                    result = await self._engine.run(
                        strategy_cls=strategy_cls,
                        symbols=symbols,
                        start=start,
                        end=end,
                        initial_capital=initial_capital,
                        params=params,
                        download_missing=False,
                        enable_risk=False,
                    )
                    if progress_callback:
                        progress_callback(idx + 1, total)
                    return GridSearchResult(
                        params=params,
                        sharpe=result.sharpe_ratio,
                        total_return=result.total_return,
                        max_drawdown=result.max_drawdown,
                        win_rate=result.win_rate,
                        trade_count=len(result.trades),
                        start=start,
                        end=end,
                    )
                except Exception as e:
                    logger.debug(f"Grid run failed for params {params}: {e}")
                    return None

        tasks = [run_one(p, i) for i, p in enumerate(combos)]
        raw = await asyncio.gather(*tasks)
        results = [r for r in raw if r is not None]
        results.sort(key=lambda r: r.score(optimize_metric), reverse=True)
        logger.info(
            f"Grid search done. Best {optimize_metric}="
            f"{results[0].score(optimize_metric):.3f} params={results[0].params}"
            if results else "Grid search returned no results"
        )
        return results

    # ── Walk-forward ──────────────────────────────────────────────────

    async def walk_forward(
        self,
        strategy_cls,
        param_grid: ParamGrid,
        symbols: list[str],
        start: datetime,
        end: datetime,
        in_sample_days: int = 365,
        out_sample_days: int = 90,
        step_days: int = 90,
        initial_capital: float = 1_000_000.0,
        optimize_metric: str = "sharpe",
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> WalkForwardResult:
        """Run rolling walk-forward optimization.

        Args:
            in_sample_days: length of in-sample training window
            out_sample_days: length of out-of-sample test window
            step_days: how many days to advance the window each iteration
        """
        windows = self._generate_windows(
            start, end, in_sample_days, out_sample_days, step_days
        )
        if not windows:
            raise ValueError(
                f"Not enough data for walk-forward with "
                f"in={in_sample_days}d out={out_sample_days}d "
                f"over {(end - start).days} days"
            )

        total_windows = len(windows)
        logger.info(
            f"Walk-forward: {total_windows} windows, "
            f"in={in_sample_days}d, out={out_sample_days}d"
        )

        wf_windows: list[WalkForwardWindow] = []
        all_runs: list[GridSearchResult] = []

        for i, (in_start, in_end, out_start, out_end) in enumerate(windows):
            logger.info(
                f"Window {i+1}/{total_windows}: "
                f"IS {in_start:%Y-%m-%d}→{in_end:%Y-%m-%d} "
                f"OOS {out_start:%Y-%m-%d}→{out_end:%Y-%m-%d}"
            )

            # In-sample grid search
            in_results = await self.grid_search(
                strategy_cls=strategy_cls,
                param_grid=param_grid,
                symbols=symbols,
                start=in_start,
                end=in_end,
                initial_capital=initial_capital,
                optimize_metric=optimize_metric,
            )

            if not in_results:
                logger.warning(f"Window {i+1}: no in-sample results, skipping")
                continue

            best_params = in_results[0].params
            all_runs.extend(in_results)

            # Out-of-sample evaluation with best params
            try:
                oos_result = await self._engine.run(
                    strategy_cls=strategy_cls,
                    symbols=symbols,
                    start=out_start,
                    end=out_end,
                    initial_capital=initial_capital,
                    params=best_params,
                    download_missing=False,
                    enable_risk=False,
                )
                wf_windows.append(WalkForwardWindow(
                    in_start=in_start,
                    in_end=in_end,
                    out_start=out_start,
                    out_end=out_end,
                    best_in_params=best_params,
                    in_sharpe=in_results[0].sharpe,
                    oos_sharpe=oos_result.sharpe_ratio,
                    oos_return=oos_result.total_return,
                    oos_drawdown=oos_result.max_drawdown,
                    oos_trade_count=len(oos_result.trades),
                ))
            except Exception as e:
                logger.warning(f"Window {i+1} OOS failed: {e}")

            if progress_callback:
                progress_callback(i + 1, total_windows)

        if not wf_windows:
            raise ValueError("Walk-forward produced no valid windows")

        # Aggregate statistics
        mean_oos_sharpe = sum(w.oos_sharpe for w in wf_windows) / len(wf_windows)
        mean_oos_return = sum(w.oos_return for w in wf_windows) / len(wf_windows)
        mean_oos_drawdown = sum(w.oos_drawdown for w in wf_windows) / len(wf_windows)

        # Most common best params (parameter stability analysis)
        best_params_overall = self._most_common_params(
            [w.best_in_params for w in wf_windows]
        )
        param_stability = self._param_stability(
            [w.best_in_params for w in wf_windows]
        )

        logger.info(
            f"Walk-forward complete | "
            f"Mean OOS Sharpe={mean_oos_sharpe:.3f} | "
            f"Mean OOS Return={mean_oos_return:.2%} | "
            f"Best params={best_params_overall}"
        )

        return WalkForwardResult(
            windows=wf_windows,
            best_params_overall=best_params_overall,
            mean_oos_sharpe=mean_oos_sharpe,
            mean_oos_return=mean_oos_return,
            mean_oos_drawdown=mean_oos_drawdown,
            param_stability=param_stability,
            all_runs=all_runs,
        )

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _generate_windows(
        start: datetime,
        end: datetime,
        in_days: int,
        out_days: int,
        step_days: int,
    ) -> list[tuple[datetime, datetime, datetime, datetime]]:
        windows = []
        in_start = start
        while True:
            in_end = in_start + timedelta(days=in_days)
            out_start = in_end
            out_end = out_start + timedelta(days=out_days)
            if out_end > end:
                break
            windows.append((in_start, in_end, out_start, out_end))
            in_start += timedelta(days=step_days)
        return windows

    @staticmethod
    def _most_common_params(param_list: list[dict]) -> dict:
        """Return the most frequently selected parameter set."""
        if not param_list:
            return {}
        from collections import Counter
        keys = list(param_list[0].keys())
        result = {}
        for key in keys:
            values = [str(p.get(key)) for p in param_list]
            most_common = Counter(values).most_common(1)[0][0]
            # Try to convert back to original type
            original_values = [p.get(key) for p in param_list]
            for v in original_values:
                if str(v) == most_common:
                    result[key] = v
                    break
        return result

    @staticmethod
    def _param_stability(param_list: list[dict]) -> dict[str, Any]:
        """Compute stability stats for each parameter across windows."""
        if not param_list:
            return {}
        from collections import Counter
        keys = list(param_list[0].keys())
        stability = {}
        for key in keys:
            values = [p.get(key) for p in param_list]
            try:
                numeric = [float(v) for v in values if v is not None]
                if numeric:
                    import statistics
                    stability[key] = {
                        "mean": statistics.mean(numeric),
                        "stdev": statistics.stdev(numeric) if len(numeric) > 1 else 0.0,
                        "values": values,
                        "most_common": Counter(str(v) for v in values).most_common(3),
                    }
            except (TypeError, ValueError):
                stability[key] = {
                    "values": values,
                    "most_common": Counter(str(v) for v in values).most_common(3),
                }
        return stability
