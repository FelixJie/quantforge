"""Stock universe management — fetch A-share market snapshot via efinance."""

from __future__ import annotations

import asyncio

import pandas as pd
from loguru import logger


async def fetch_universe() -> pd.DataFrame:
    """Fetch real-time snapshot of all A-share stocks.

    Returns DataFrame with columns:
        code, name, price, change_pct, high, low, open,
        volume, turnover, pe, market_cap, circulating_cap
    """
    try:
        df = await asyncio.to_thread(_fetch_sync)
        return _parse(df)
    except Exception as e:
        logger.error(f"fetch_universe failed: {e}")
        return pd.DataFrame()


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
