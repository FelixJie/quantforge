"""Stock universe management — fetch A-share market snapshot.

Primary source is the local ``stock_quote`` snapshot table (refreshed in the
background via Tencent/Sina), which is reliable here; efinance (EastMoney) is
only a cold-start fallback since it is intermittently blocked in this
environment.
"""

from __future__ import annotations

import asyncio

import pandas as pd
from loguru import logger


# Snapshot columns → universe columns. ``market_cap`` is in 元 in both the
# snapshot table and the screener engine (which compares against 亿 * 1e8).
_SNAPSHOT_FIELDS = [
    "code", "name", "price", "change_pct", "high", "low", "open",
    "volume", "turnover", "pe", "pb", "turnover_rate", "market_cap",
]


async def fetch_universe() -> pd.DataFrame:
    """Fetch real-time snapshot of all A-share stocks.

    Returns DataFrame with columns:
        code, name, price, change_pct, high, low, open,
        volume, turnover, pe, pb, turnover_rate, market_cap, circulating_cap
    """
    # 1) Local snapshot table — fast and reliable, no upstream dependency.
    try:
        df = await asyncio.to_thread(_fetch_from_snapshot)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        logger.warning(f"fetch_universe: snapshot read failed, falling back: {e}")

    # 2) Cold-start fallback — efinance (EastMoney), may be unavailable.
    try:
        df = await asyncio.to_thread(_fetch_sync)
        return _parse(df)
    except Exception as e:
        logger.error(f"fetch_universe failed: {e}")
        return pd.DataFrame()


def _fetch_from_snapshot() -> pd.DataFrame:
    """Build the universe DataFrame from the local ``stock_quote`` snapshot."""
    from quantforge.data.storage import db_cache as _db

    if _db.quote_count() == 0:
        return pd.DataFrame()

    # Pull the whole table via the paginated query (page_size caps at 500).
    rows: list[dict] = []
    page = 1
    while True:
        chunk, total = _db.quote_query(page=page, page_size=500)
        if not chunk:
            break
        rows.extend(chunk)
        if len(rows) >= total:
            break
        page += 1

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    available = [c for c in _SNAPSHOT_FIELDS if c in df.columns]
    df = df[available].copy()

    numeric_cols = ["price", "change_pct", "high", "low", "open",
                    "volume", "turnover", "pe", "pb", "turnover_rate", "market_cap"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[df["price"].notna() & (df["price"] > 0)].reset_index(drop=True)
    logger.info(f"fetch_universe: loaded {len(df)} stocks from snapshot")
    return df


def _fetch_sync() -> pd.DataFrame:
    import efinance as ef
    return ef.stock.get_realtime_quotes()


def _parse(df: pd.DataFrame) -> pd.DataFrame:
    """Map positional columns — robust to Chinese encoding issues."""
    if df.empty:
        return df

    cols = df.columns.tolist()

    # Known positional layout for ef.stock.get_realtime_quotes()
    # 0=名称  1=代码  2=涨跌幅  3=最新价  4=最高  5=最低  6=今开
    # 7=涨跌额  8=成交量  9=成交额  10=市盈率(动)  11=量比
    # 12=换手率  13=市净率  14=总市值  15=流通市值
    pos_map = {
        0: "name",
        1: "code",
        2: "change_pct",
        3: "price",
        4: "high",
        5: "low",
        6: "open",
        7: "change_amount",
        8: "volume",
        9: "turnover",
        10: "pe",
        12: "turnover_rate",
        13: "pb",
        14: "market_cap",
        15: "circulating_cap",
    }

    rename = {cols[i]: name for i, name in pos_map.items() if i < len(cols)}
    df = df.rename(columns=rename)

    keep = ["code", "name", "price", "change_pct", "high", "low", "open",
            "volume", "turnover", "pe", "pb", "turnover_rate",
            "market_cap", "circulating_cap"]
    available = [c for c in keep if c in df.columns]
    df = df[available].copy()

    numeric_cols = ["price", "change_pct", "high", "low", "open",
                    "volume", "turnover", "pe", "pb", "turnover_rate",
                    "market_cap", "circulating_cap"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Remove invalid rows (no price or ST/delisting noise)
    df = df[df["price"].notna() & (df["price"] > 0)].reset_index(drop=True)

    return df


async def enrich_with_fundamentals(
    df: pd.DataFrame,
    codes: list[str] | None = None,
) -> pd.DataFrame:
    """Enrich universe DataFrame with ROE and industry via get_base_info.

    This is slower (one API call per batch), so only call for filtered subsets.
    """
    targets = codes if codes else df["code"].tolist()

    try:
        info_df = await asyncio.to_thread(_fetch_base_info, targets)
        if info_df.empty:
            return df

        # Map positional: 0=代码, 1=名称, 2=总市值, 3=流通值, 4=行业,
        #                  5=每股收益, 6=市净率, 7=ROE, 8=毛利率, 9=市盈率(动)
        cols = info_df.columns.tolist()
        pos_map = {0: "code", 4: "industry", 6: "pb_info", 7: "roe", 9: "pe_info"}
        rename = {cols[i]: name for i, name in pos_map.items() if i < len(cols)}
        info_df = info_df.rename(columns=rename)

        for col in ["roe", "pb_info", "pe_info"]:
            if col in info_df.columns:
                info_df[col] = pd.to_numeric(info_df[col], errors="coerce")

        # Merge on code
        info_keep = ["code"] + [c for c in ["industry", "roe"] if c in info_df.columns]
        df = df.merge(info_df[info_keep], on="code", how="left")

    except Exception as e:
        logger.warning(f"enrich_with_fundamentals failed: {e}")

    return df


def _fetch_base_info(codes: list[str]) -> pd.DataFrame:
    import efinance as ef
    try:
        result = ef.stock.get_base_info(codes)
        if isinstance(result, pd.Series):
            # Single stock returns a Series — convert to DataFrame
            return result.to_frame().T
        return result
    except Exception:
        return pd.DataFrame()
