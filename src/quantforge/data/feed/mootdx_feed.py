"""
Mootdx + 腾讯财经数据源适配器 (基于 a-stock-data 3.1)
- Mootdx: K线 + 五档盘口 + 逐笔成交 (TCP, 不封IP)
- 腾讯财经: PE/PB/市值/换手率/涨跌停 (HTTP, 不封IP)
- 百度K线: 带MA均线
"""

from __future__ import annotations

import asyncio
import urllib.request
from datetime import datetime
from typing import Optional
import pandas as pd
import requests

from quantforge.core.constants import Exchange, Interval
from quantforge.core.errors import DataError

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _normalize_code(code: str) -> str:
    """归一化股票代码为纯6位数字"""
    code = str(code).strip().upper()
    if code.startswith(("SH", "SZ", "BJ")):
        code = code[2:]
    elif code.endswith((".SH", ".SZ", ".BJ")):
        code = code[:-3]
    return code


def _get_market(code: str) -> int:
    """获取市场: 0=深圳, 1=上海"""
    if code.startswith(("6", "9")):
        return 1
    return 0


class MootdxFeed:
    """
    Mootdx + 腾讯财经数据源
    """

    name = "mootdx"

    def __init__(self):
        try:
            from mootdx.quotes import Quotes
            self._client = Quotes.factory(market='std')
        except Exception as e:
            self._client = None

    async def get_quotes_tencent(self, codes: list[str]) -> dict[str, dict]:
        """批量拉取腾讯财经实时行情 — PE/PB/市值/换手率/涨跌停价/指数/ETF"""
        codes = [_normalize_code(c) for c in codes]
        return await asyncio.to_thread(_tencent_quote, codes)

    async def get_quotes_mootdx(self, codes: list[str]) -> dict[str, dict]:
        """批量拉取Mootdx实时报价 — K线/五档盘口/逐笔成交"""
        codes = [_normalize_code(c) for c in codes]
        return await asyncio.to_thread(_mootdx_quotes, self._client, codes)

    async def get_bars(
        self,
        symbol: str,
        interval: Interval,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        exchange: Optional[Exchange] = None,
    ) -> pd.DataFrame:
        """
        获取历史K线数据
        """
        symbol = _normalize_code(symbol)
        category = _interval_to_mootdx_category(interval)
        offset = 500 if start is None else 5000

        def fetch():
            try:
                klines = self._client.bars(symbol=symbol, category=category, offset=offset)
                return klines
            except Exception as e:
                raise DataError(f"mootdx bars failed for {symbol}: {e}")

        klines = await asyncio.to_thread(fetch)
        
        if klines is None or len(klines) == 0:
            raise DataError(f"No data for {symbol}")

        df = pd.DataFrame(klines)
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
        return df

    async def get_quotes(self, codes: list[str]) -> dict[str, dict]:
        """综合报价: Mootdx(实时交易数据) + 腾讯财经(估值/市值)"""
        q_mootdx = await self.get_quotes_mootdx(codes)
        q_tencent = await self.get_quotes_tencent(codes)
        
        result = {}
        for code in codes:
            c = _normalize_code(code)
            item = {}
            if c in q_mootdx:
                item.update(q_mootdx[c])
            if c in q_tencent:
                item.update(q_tencent[c])
            if item:
                result[c] = item
        return result


def _interval_to_mootdx_category(interval: Interval) -> int:
    mapping = {
        Interval.MINUTE: 7,
        Interval.FIVE_MINUTES: 8,
        Interval.FIFTEEN_MINUTES: 9,
        Interval.THIRTY_MINUTES: 10,
        Interval.HOUR: 11,
        Interval.DAILY: 4,
        Interval.WEEKLY: 5,
        Interval.MONTHLY: 6,
    }
    return mapping.get(interval, 4)


def _mootdx_quotes(client, codes: list[str]) -> dict[str, dict]:
    if client is None:
        return {}
    
    result = {}
    try:
        for code in codes:
            quotes = client.quotes(symbol=[code])
            if len(quotes) > 0:
                q = quotes.iloc[0].to_dict()
                result[code] = q
    except Exception:
        pass
    
    return result


def _tencent_quote(codes: list[str]) -> dict[str, dict]:
    """
    腾讯财经 API - 批量拉取实时行情, 不封IP
    支持个股/指数/ETF
    """
    prefixed = []
    for c in codes:
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode("gbk")
    except Exception:
        return {}

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        result[code] = {
            "name": vals[1],
            "price": float(vals[3]) if vals[3] else 0,
            "last_close": float(vals[4]) if vals[4] else 0,
            "open": float(vals[5]) if vals[5] else 0,
            "change_amt": float(vals[31]) if vals[31] else 0,
            "change_pct": float(vals[32]) if vals[32] else 0,
            "high": float(vals[33]) if vals[33] else 0,
            "low": float(vals[34]) if vals[34] else 0,
            "amount_wan": float(vals[37]) if vals[37] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "pe_ttm": float(vals[39]) if vals[39] else 0,
            "amplitude_pct": float(vals[43]) if vals[43] else 0,
            "mcap_yi": float(vals[44]) if vals[44] else 0,
            "float_mcap_yi": float(vals[45]) if vals[45] else 0,
            "pb": float(vals[46]) if vals[46] else 0,
            "limit_up": float(vals[47]) if vals[47] else 0,
            "limit_down": float(vals[48]) if vals[48] else 0,
            "vol_ratio": float(vals[49]) if vals[49] else 0,
            "pe_static": float(vals[52]) if vals[52] else 0,
        }
    return result


# --- 百度K线带均线 ---
def baidu_kline_with_ma(code: str, start_time: str = "") -> dict:
    """百度股市通K线 — 独有能力: 返回时自带 ma5/ma10/ma20 均价"""
    url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
    params = {
        "all": "1", "isIndex": "false", "isBk": "false", "isBlock": "false",
        "isFutures": "false", "isStock": "true", "newFormat": "1",
        "group": "quotation_kline_ab", "finClientType": "pc",
        "code": code, "start_time": start_time, "ktype": "1",
    }
    headers = {
        "User-Agent": UA,
        "Accept": "application/vnd.finance-web.v1+json",
        "Origin": "https://gushitong.baidu.com",
        "Referer": "https://gushitong.baidu.com/",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        d = r.json()
        result = d.get("Result", {})
        md = result.get("newMarketData", {})
        keys = md.get("keys", [])
        rows = md.get("marketData", "").split(";")
        return {"keys": keys, "rows": rows}
    except Exception:
        return {"keys": [], "rows": []}
