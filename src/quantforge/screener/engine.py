"""Screener engine — orchestrates universe → filter → score → rank."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pandas as pd
from loguru import logger

from quantforge.screener.universe import fetch_universe, enrich_with_fundamentals
from quantforge.screener.scorer import score_universe


@dataclass
class ScreenerConfig:
    # Filters
    min_price: float = 2.0
    max_price: float | None = None
    min_pe: float | None = None
    max_pe: float | None = 200.0
    min_pb: float | None = None
    max_pb: float | None = None
    min_market_cap: float | None = None    # in 亿元
    max_market_cap: float | None = None
    min_change_pct: float | None = None
    max_change_pct: float | None = None
    exchange: str | None = None            # "SSE" | "SZSE" | "BSE" | None

    # Factor weights (0 = disabled)
    factor_weights: dict[str, float] = field(default_factory=lambda: {
        "value": 0.30,
        "pb": 0.15,
        "graham": 0.00,
        "value_composite": 0.00,
        "momentum": 0.20,
        "size": 0.10,
        "large_cap": 0.00,
        "liquidity": 0.10,
        "quality": 0.00,
        "float_ratio": 0.00,
    })

    # Output
    top_n: int = 50
    enrich_fundamentals: bool = False  # slower, adds ROE + industry


async def run_screener(config: ScreenerConfig) -> dict:
    """Run the full screening pipeline.

    Returns dict with:
        stocks: list of stock dicts (top N)
        total_universe: int (stocks before filtering)
        total_after_filter: int
        factors_used: list[str]
        run_time_ms: int
    """
    t0 = time.monotonic()
    logger.info("Screener: fetching universe...")

    universe = await fetch_universe()
    if universe.empty:
        return {"stocks": [], "error": "Failed to fetch market data", "run_time_ms": 0}

    total_universe = len(universe)
    logger.info(f"Screener: universe size = {total_universe}")

    # Apply exchange filter (infer from code prefix)
    if config.exchange:
        ex = config.exchange.upper()
        if ex == "SSE":
            universe = universe[universe["code"].str.startswith("6")]
        elif ex == "SZSE":
            universe = universe[universe["code"].str.startswith(("0", "3"))]
        elif ex == "BSE":
            universe = universe[universe["code"].str.startswith(("8", "4"))]

    # Apply numeric filters
    filters = [
        ("price", ">=", config.min_price),
        ("price", "<=", config.max_price),
        ("pe",    ">=", config.min_pe),
        ("pe",    "<=", config.max_pe),
        ("pb",    ">=", config.min_pb),
        ("pb",    "<=", config.max_pb),
        ("change_pct", ">=", config.min_change_pct),
        ("change_pct", "<=", config.max_change_pct),
    ]

    for col, op, val in filters:
        if val is None or col not in universe.columns:
            continue
        numeric = pd.to_numeric(universe[col], errors="coerce")
        if op == ">=":
            mask = numeric.isna() | (numeric >= val)
        else:
            mask = numeric.isna() | (numeric <= val)
        universe = universe[mask]

    # Market cap filter (input in 亿元, data in 元)
    if config.min_market_cap is not None and "market_cap" in universe.columns:
        universe = universe[
            universe["market_cap"].isna() |
            (universe["market_cap"] >= config.min_market_cap * 1e8)
        ]
    if config.max_market_cap is not None and "market_cap" in universe.columns:
        universe = universe[
            universe["market_cap"].isna() |
            (universe["market_cap"] <= config.max_market_cap * 1e8)
        ]

    total_after_filter = len(universe)
    logger.info(f"Screener: after filters = {total_after_filter}")

    if universe.empty:
        return {
            "stocks": [],
            "total_universe": total_universe,
            "total_after_filter": 0,
            "factors_used": [],
            "run_time_ms": int((time.monotonic() - t0) * 1000),
        }

    # Optional fundamental enrichment (ROE + industry)
    if config.enrich_fundamentals:
        universe = await enrich_with_fundamentals(universe)

    # Score and rank
    scored = score_universe(universe, config.factor_weights)

    # Extract top N
    top = scored.head(config.top_n)

    # Build sector distribution from full scored universe
    sector_dist = _sector_distribution(scored)

    # Factors that were used (non-zero weight)
    factors_used = [k for k, v in config.factor_weights.items() if v and v > 0]

    # Serialize to list of dicts
    keep_cols = ["rank", "code", "name", "price", "change_pct", "pe", "pb",
                 "market_cap", "circulating_cap", "turnover_rate", "score", "score_pct"]
    if "industry" in top.columns:
        keep_cols.append("industry")
    if "roe" in top.columns:
        keep_cols.append("roe")

    available = [c for c in keep_cols if c in top.columns]
    stocks = _to_serializable(top[available])

    run_ms = int((time.monotonic() - t0) * 1000)
    logger.info(f"Screener: done in {run_ms}ms, top {len(stocks)} returned")

    return {
        "stocks": stocks,
        "total_universe": total_universe,
        "total_after_filter": total_after_filter,
        "factors_used": factors_used,
        "sector_distribution": sector_dist,
        "run_time_ms": run_ms,
    }


def _sector_distribution(df: pd.DataFrame) -> list[dict]:
    """Count stocks and avg score by exchange prefix as sector proxy."""
    if df.empty:
        return []

    def prefix_to_board(code: str) -> str:
        code = str(code)
        if code.startswith("6"):
            return "上证主板"
        elif code.startswith("3"):
            return "创业板/科创"
        elif code.startswith("0"):
            return "深证主板"
        elif code.startswith(("8", "4")):
            return "北交所"
        return "其他"

    df = df.copy()
    df["board"] = df["code"].apply(prefix_to_board)

    agg = (
        df.groupby("board")
        .agg(count=("code", "count"), avg_score=("score", "mean"))
        .reset_index()
    )
    return agg.rename(columns={"board": "name"}).to_dict("records")


def _to_serializable(df: pd.DataFrame) -> list[dict]:
    """Convert DataFrame to JSON-safe list of dicts, rounding floats."""
    import math
    records = df.to_dict("records")
    clean = []
    for row in records:
        r = {}
        for k, v in row.items():
            if isinstance(v, float):
                r[k] = None if math.isnan(v) else round(v, 4)
            else:
                r[k] = v
        clean.append(r)
    return clean
