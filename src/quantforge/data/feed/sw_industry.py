"""申万一级行业分类：``code(zfill6) → 申万一级行业名``。

数据源 akshare：``sw_index_first_info()`` 取 31 个申万一级行业(代码/名称)，逐个
``index_component_sw(代码)`` 取成分股；落库到 ``sector_*`` 表 ``kind="sw_industry"``，
按周刷新（申万重分类很少发生）。efinance/push2 自带的行业分类被代理劫持不可用，故
单独用 akshare 申万口径作 AI 荐股「动能买点」页的行业筛选维度。

读写分离：
- ``build_sw_industry_map()`` 触网构建并落库（后台 warmer / 手动刷新调用）。
- ``get_sw_industry_map()`` 只读 DB，不触网（请求链路用，缺数据时优雅退化）。
"""
from __future__ import annotations

import threading
import time

from loguru import logger

from quantforge.data.storage import db_cache as _db

_KIND = "sw_industry"
_TTL = 7 * 86400  # 一周；申万一级行业归属变动罕见
_build_lock = threading.Lock()


def _normalize_code(v) -> str:
    """``'000505.SZ'`` / ``'000505'`` → ``'000505'``（取 6 位数字、去市场后缀）。"""
    s = str(v or "").strip().split(".")[0]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits.zfill(6) if digits else ""


def build_sw_industry_map(force: bool = False) -> dict[str, str]:
    """拉申万一级行业成分并落库，返回 ``code→行业名``。

    DB 仍新鲜(``force=False`` 且 < 一周)则直接返回已落库映射，不触网。任一环节失败
    都回落到已落库数据，不抛异常（warmer / 请求链路都不该被它打断）。
    """
    if not force and _db.sector_boards_fresh(_KIND, _TTL):
        return get_sw_industry_map()
    with _build_lock:
        # 双检：等锁期间别的线程可能已建好
        if not force and _db.sector_boards_fresh(_KIND, _TTL):
            return get_sw_industry_map()
        try:
            import akshare as ak
        except Exception as e:  # pragma: no cover - 依赖缺失
            logger.warning(f"sw_industry: akshare 不可用: {e}")
            return get_sw_industry_map()
        try:
            first = ak.sw_index_first_info()
        except Exception as e:
            logger.warning(f"sw_industry: sw_index_first_info 失败: {e}")
            return get_sw_industry_map()

        boards: list[dict] = []
        code_map: dict[str, str] = {}
        # 位置取列规避中文列名编码坑：first 列序 = [行业代码(801010.SI), 行业名称, ...]
        for _, row in first.iterrows():
            sym = str(row.iloc[0] or "").strip().split(".")[0]
            name = str(row.iloc[1] or "").strip()
            if not sym or not name:
                continue
            try:
                comp = ak.index_component_sw(symbol=sym)
            except Exception as e:
                logger.warning(f"sw_industry: 成分 {sym}/{name} 拉取失败: {e}")
                time.sleep(0.5)
                continue
            # comp 列序 = [序号, 证券代码, 证券名称, 最新权重, 调入日期]
            stocks: list[dict] = []
            for _, c in comp.iterrows():
                code = _normalize_code(c.iloc[1])
                cname = str(c.iloc[2] or "").strip() if comp.shape[1] > 2 else ""
                if not code:
                    continue
                stocks.append({"code": code, "name": cname})
                code_map[code] = name
            if stocks:
                _db.replace_sector_constituents(_KIND, name, stocks)
                boards.append({"name": name, "node": sym, "total": len(stocks)})
            time.sleep(0.3)  # 轻限速，别把 akshare 网关打挂

        if boards:
            _db.replace_sector_boards(_KIND, boards)
            logger.info(
                f"sw_industry: 申万一级行业落库完成 —— {len(boards)} 个行业 / {len(code_map)} 只个股"
            )
        return code_map or get_sw_industry_map()


def get_sw_industry_map() -> dict[str, str]:
    """只读：从 DB(``kind=sw_industry``)取 ``code→行业名``，不触网。"""
    out: dict[str, str] = {}
    try:
        for b in (_db.get_sector_boards(_KIND) or []):
            name = (b.get("name") or "").strip()
            if not name:
                continue
            for s in (_db.get_sector_constituents(_KIND, name) or []):
                code = str(s.get("code") or "").strip().zfill(6)
                if code:
                    out[code] = name
    except Exception as e:  # pragma: no cover
        logger.debug(f"sw_industry.get_sw_industry_map failed: {e}")
    return out


async def sw_industry_warmer():
    """后台 warmer：启动补一次，之后每天检查、过期(一周)才重建。"""
    import asyncio

    while True:
        try:
            await asyncio.to_thread(build_sw_industry_map)
        except Exception as e:  # pragma: no cover
            logger.warning(f"sw_industry warmer 轮次失败: {e}")
        await asyncio.sleep(86400)
