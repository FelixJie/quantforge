"""
资金面/筹码 API (基于 a-stock-data 3.1)
- 融资融券明细
- 大宗交易
- 股东户数变化
- 分红送转历史
- 个股资金流向(分钟/120日)
"""

from __future__ import annotations

import asyncio
import requests
from fastapi import APIRouter

router = APIRouter(prefix="/capital", tags=["capital"])

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

# --- 融资融券 ---
@router.get("/margin/{code}")
async def get_margin_trading(code: str, page_size: int = 50):
    """融资融券明细"""
    def fetch():
        return _eastmoney_datacenter(
            "RPTA_APP_MARGINTRADEDETAILS",
            filter_str=f"(SECURITY_CODE=\"{code}\")",
            sort_columns="TRADE_DATE",
            sort_types="-1",
            page_size=page_size,
        )
    data = await asyncio.to_thread(fetch)
    return {"code": code, "count": len(data), "data": data}

# --- 大宗交易 ---
@router.get("/block_trade/{code}")
async def get_block_trades(code: str, page_size: int = 50):
    """大宗交易 — 成交价/量/买卖方/溢价率"""
    def fetch():
        return _eastmoney_datacenter(
            "RPT_DAILYBLOCKTRADE",
            filter_str=f"(SECURITY_CODE=\"{code}\")",
            sort_columns="TRADE_DATE",
            sort_types="-1",
            page_size=page_size,
        )
    data = await asyncio.to_thread(fetch)
    return {"code": code, "count": len(data), "data": data}

# --- 股东户数 ---
@router.get("/holder_count/{code}")
async def get_holder_count(code: str, page_size: int = 20):
    """股东户数变化 — 季度更新"""
    def fetch():
        return _eastmoney_datacenter(
            "RPT_HOLDERNUM",
            filter_str=f"(SECURITY_CODE=\"{code}\")",
            sort_columns="END_DATE",
            sort_types="-1",
            page_size=page_size,
        )
    data = await asyncio.to_thread(fetch)
    return {"code": code, "count": len(data), "data": data}

# --- 分红送转 ---
@router.get("/dividend/{code}")
async def get_dividends(code: str, page_size: int = 30):
    """分红送转历史"""
    def fetch():
        return _eastmoney_datacenter(
            "RPT_SHAREBONUS_DET",
            filter_str=f"(SECURITY_CODE=\"{code}\")",
            sort_columns="NOTICE_DATE",
            sort_types="-1",
            page_size=page_size,
        )
    data = await asyncio.to_thread(fetch)
    return {"code": code, "count": len(data), "data": data}

# --- 个股资金流向 (分钟级 + 120日) ---
def _eastmoney_push2_funds(code: str) -> list[dict]:
    """东财 push2 分钟级资金流向 (主力/大单/中单/小单)"""
    url = f"https://push2.eastmoney.com/api/qt/stock/details/get"
    params = {
        "fields1": "f1,f2,f3,f4,f5",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "ut": "fa5fd1943c7b386f172d6893dbf075e3",
        "klt": "1",
        "secid": f"0.{code}" if code.startswith(("0", "3")) else f"1.{code}",
        "_": str(int(__import__("time").time() * 1000)),
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=10)
        d = r.json()
        return d.get("data", {}).get("klines", [])
    except Exception:
        return []

@router.get("/funds_minute/{code}")
async def get_funds_minute(code: str):
    """个股资金流向 分钟级 — 主力/大单/中单/小单"""
    def fetch():
        return _eastmoney_push2_funds(code)
    data = await asyncio.to_thread(fetch)
    return {"code": code, "count": len(data), "data": data}

def _eastmoney_push2his_funds_120(code: str) -> list[dict]:
    """东财 push2his 120日资金流向"""
    url = f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "lmt": "120",
        "klt": "101",
        "secid": f"0.{code}" if code.startswith(("0", "3")) else f"1.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "_": str(int(__import__("time").time() * 1000)),
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=10)
        d = r.json()
        return d.get("data", {}).get("klines", [])
    except Exception:
        return []

@router.get("/funds_120d/{code}")
async def get_funds_120d(code: str):
    """个股资金流向 120日 — 主力/大单/中单/小单日级净流入"""
    def fetch():
        return _eastmoney_push2his_funds_120(code)
    data = await asyncio.to_thread(fetch)
    return {"code": code, "count": len(data), "data": data}

# --- 综合资金面汇总 ---
@router.get("/summary/{code}")
async def get_capital_summary(code: str):
    """资金面/筹码综合汇总"""
    margin = await get_margin_trading(code, page_size=30)
    block_trade = await get_block_trades(code, page_size=10)
    holder = await get_holder_count(code, page_size=10)
    dividend = await get_dividends(code, page_size=10)
    funds = await get_funds_120d(code)
    
    return {
        "code": code,
        "margin": margin["data"],
        "block_trade": block_trade["data"],
        "holder_count": holder["data"],
        "dividend": dividend["data"],
        "funds_120d": funds["data"],
    }
