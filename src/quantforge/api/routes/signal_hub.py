"""
信号 API (基于 a-stock-data 3.1)
- 同花顺热点/强势股
- 同花顺北向资金
- 百度概念板块
- 龙虎榜
- 限售解禁
- 东财行业板块
"""

from __future__ import annotations

import asyncio
import requests
from fastapi import APIRouter

router = APIRouter(prefix="/signal", tags=["signal"])

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

def _eastmoney_datacenter(report_name: str, columns: str = "ALL",
                          filter_str: str = "", page_size: int = 50,
                          sort_columns: str = "", sort_types: str = "-1") -> list[dict]:
    """东财数据中心统一查询"""
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    try:
        r = requests.get(DATACENTER_URL, params=params, headers={"User-Agent": UA}, timeout=15)
        d = r.json()
        if d.get("result") and d["result"].get("data"):
            return d["result"]["data"]
    except Exception:
        pass
    return []

# --- 同花顺热点/强势股 + 题材归因 ---
def _ths_hot_stocks() -> list[dict]:
    """同花顺当日强势股 + 题材归因 — 零鉴权, 73ms"""
    url = "https://dq.10jqka.com.cn/funds/blocknewbk/data/dataList.html"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        import json
        d = r.json()
        return d.get("info", {}).get("data", [])
    except Exception:
        return []

@router.get("/hot_stocks")
async def get_hot_stocks():
    """同花顺当日强势股 + 题材归因"""
    def fetch():
        return _ths_hot_stocks()
    data = await asyncio.to_thread(fetch)
    return {"count": len(data), "data": data}

# --- 同花顺北向资金 ---
def _ths_northbound_flow(market: str = "hk") -> dict:
    """同花顺北向资金 — hg沪股通/sg深股通/min分钟"""
    url = f"https://dcfm.eastmoney.com/em_mutisvcexpandinterface/api/js/get"
    params = {
        "type": "HSGT_NORTH",
        "js": "var lzrXWmXk={data:((x))}",
        "token": "70f12f2f4f091e459a276f1e6e1a1b9c",
        "rtntype": "6",
        "_": str(int(__import__("time").time() * 1000)),
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=10)
        import json
        d = r.json()
        return d
    except Exception:
        return {}

@router.get("/northbound")
async def get_northbound():
    """同花顺北向资金 — 沪股通/深股通"""
    def fetch():
        return _ths_northbound_flow()
    data = await asyncio.to_thread(fetch)
    return data

# --- 百度概念板块 ---
def _baidu_concepts(code: str) -> dict:
    """百度股市通概念板块归属"""
    url = "https://finance.pae.baidu.com/api/getrelatedstock"
    params = {
        "code": code,
        "market": "ab",
        "newFormat": "1",
        "finClientType": "pc",
    }
    headers = {
        "User-Agent": UA,
        "Origin": "https://gushitong.baidu.com",
        "Referer": "https://gushitong.baidu.com/",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        d = r.json()
        return d.get("Result", {})
    except Exception:
        return {}

@router.get("/concepts/{code}")
async def get_concepts(code: str):
    """百度股市通概念板块归属"""
    def fetch():
        return _baidu_concepts(code)
    data = await asyncio.to_thread(fetch)
    return {"code": code, "data": data}

# --- 龙虎榜 ---
@router.get("/dragon_board/{code}")
async def get_dragon_board(code: str, page_size: int = 50):
    """个股龙虎榜席位 — 上榜记录 + 买卖方TOP5 + 机构动向"""
    def fetch():
        return _eastmoney_datacenter(
            "RPTA_APP_BILLBOARDDETAIL",
            filter_str=f"(SECURITY_CODE=\"{code}\")",
            sort_columns="TRADE_DATE",
            sort_types="-1",
            page_size=page_size,
        )
    data = await asyncio.to_thread(fetch)
    return {"code": code, "count": len(data), "data": data}

@router.get("/dragon_board_all")
async def get_dragon_board_all(page_size: int = 100):
    """全市场龙虎榜 — 当日所有上榜股票 + 净买额排名"""
    def fetch():
        return _eastmoney_datacenter(
            "RPTA_APP_BILLBOARDSTOCKLIST",
            sort_columns="BUY_NET_AMOUNT",
            sort_types="-1",
            page_size=page_size,
        )
    data = await asyncio.to_thread(fetch)
    return {"count": len(data), "data": data}

# --- 限售解禁 ---
@router.get("/unlock/{code}")
async def get_unlock(code: str, page_size: int = 50):
    """限售解禁 — 历史解禁 + 未来90天待解禁"""
    def fetch():
        return _eastmoney_datacenter(
            "RPTA_APP_NONTRADABLESHARE",
            filter_str=f"(SECURITY_CODE=\"{code}\")",
            sort_columns="UNBAN_DATE",
            sort_types="-1",
            page_size=page_size,
        )
    data = await asyncio.to_thread(fetch)
    return {"code": code, "count": len(data), "data": data}

@router.get("/unlock_upcoming")
async def get_unlock_upcoming(page_size: int = 50):
    """未来90天限售解禁日历"""
    from datetime import datetime, timedelta
    start_date = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
    
    def fetch():
        return _eastmoney_datacenter(
            "RPTA_APP_NONTRADABLESHARE",
            filter_str=f"(UNBAN_DATE>='{start_date}')(UNBAN_DATE<='{end_date}')",
            sort_columns="UNBAN_DATE",
            sort_types="1",
            page_size=page_size,
        )
    data = await asyncio.to_thread(fetch)
    return {"count": len(data), "data": data}

# --- 东财行业板块 ---
@router.get("/industry_rank")
async def get_industry_rank(page_size: int = 100):
    """东财行业板块涨跌排名 + 上涨下跌家数"""
    def fetch():
        return _eastmoney_datacenter(
            "RPTA_APP_INDUSTRYPLATE",
            sort_columns="CHANGE_RATE",
            sort_types="-1",
            page_size=page_size,
        )
    data = await asyncio.to_thread(fetch)
    return {"count": len(data), "data": data}

# --- 综合信号汇总 ---
@router.get("/summary")
async def get_signal_summary():
    """信号综合汇总"""
    hot = await get_hot_stocks()
    northbound = await get_northbound()
    industry = await get_industry_rank()
    dragon_all = await get_dragon_board_all()
    unlock_upcoming = await get_unlock_upcoming()
    
    return {
        "hot_stocks": hot,
        "northbound": northbound,
        "industry_rank": industry,
        "dragon_board_all": dragon_all,
        "unlock_upcoming": unlock_upcoming,
    }
