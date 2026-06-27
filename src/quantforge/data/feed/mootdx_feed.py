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
    """腾讯财经 API — 批量拉取实时行情，不封IP。

    支持 A股/指数/ETF + 港股(HK前缀，如 HK00700) + 美股(US前缀，如 USAAPL)。
    港股/美股由调用方传入 HK*/US* 前缀代码；内部转换为腾讯格式再解析回来。
    """
    # prefix_map: 腾讯API格式 → 原始入参代码，用于解析响应时还原
    prefix_map: dict[str, str] = {}
    prefixed: list[str] = []
    for c in codes:
        cu = c.strip().upper()
        if cu.startswith("HK"):
            # 港股：HK00700 → hk00700
            p = "hk" + c[2:]
            prefix_map[p] = c
            prefixed.append(p)
        elif cu.startswith("US"):
            # 美股：USAAPL → usAAPL（保留大小写，腾讯区分）
            p = "us" + c[2:]
            prefix_map[p] = c
            prefix_map[p.lower()] = c  # 腾讯响应有时全小写
            prefixed.append(p)
        elif c.startswith(("6", "9", "5")):
            # SH: 6xxxx(股), 9xxxx(债), 5xxxx(ETF/基金)
            p = f"sh{c}"
            prefix_map[p] = c
            prefixed.append(p)
        elif c.startswith(("8", "4")):
            # BJ: 8xxxx/4xxxx
            p = f"bj{c}"
            prefix_map[p] = c
            prefixed.append(p)
        else:
            # SZ: 0xxxx/1xxxx/2xxxx/3xxxx
            p = f"sz{c}"
            prefix_map[p] = c
            prefixed.append(p)

    # gtimg is intermittently blocked behind some proxies on one scheme but not
    # the other; try http then https (one pass, short timeout) to ride out blips
    # without tying up a worker thread for long when the network is down.
    query = ",".join(prefixed)
    data = ""
    for scheme in ("http", "https"):
        try:
            req = urllib.request.Request(f"{scheme}://qt.gtimg.cn/q=" + query)
            req.add_header("User-Agent", UA)
            req.add_header("Referer", "https://gu.qq.com/")
            data = urllib.request.urlopen(req, timeout=5).read().decode("gbk")
            if data:
                break
        except Exception:
            data = ""
    if not data:
        return {}

    def _flt(v: str) -> float:
        try:
            return float(v) if v else 0
        except (ValueError, TypeError):
            return 0

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        # 用 prefix_map 还原原始代码（支持 HK/US/A股）
        orig_code = prefix_map.get(key) or prefix_map.get(key.lower())
        if orig_code is None:
            continue
        vals = line.split('"')[1].split("~")
        if len(vals) < 4:
            continue
        result[orig_code] = {
            "name": vals[1] if len(vals) > 1 else "",
            "price": _flt(vals[3]) if len(vals) > 3 else 0,
            "last_close": _flt(vals[4]) if len(vals) > 4 else 0,
            "open": _flt(vals[5]) if len(vals) > 5 else 0,
            "change_amt": _flt(vals[31]) if len(vals) > 31 else 0,
            "change_pct": _flt(vals[32]) if len(vals) > 32 else 0,
            "high": _flt(vals[33]) if len(vals) > 33 else 0,
            "low": _flt(vals[34]) if len(vals) > 34 else 0,
            "amount_wan": _flt(vals[37]) if len(vals) > 37 else 0,
            "turnover_pct": _flt(vals[38]) if len(vals) > 38 else 0,
            "pe_ttm": _flt(vals[39]) if len(vals) > 39 else 0,
            "amplitude_pct": _flt(vals[43]) if len(vals) > 43 else 0,
            "mcap_yi": _flt(vals[44]) if len(vals) > 44 else 0,
            "float_mcap_yi": _flt(vals[45]) if len(vals) > 45 else 0,
            "pb": _flt(vals[46]) if len(vals) > 46 else 0,
            "limit_up": _flt(vals[47]) if len(vals) > 47 else 0,
            "limit_down": _flt(vals[48]) if len(vals) > 48 else 0,
            "vol_ratio": _flt(vals[49]) if len(vals) > 49 else 0,
            "pe_static": _flt(vals[52]) if len(vals) > 52 else 0,
        }
    return result


def _tencent_smartbox_search(q: str, limit: int = 20) -> list[dict]:
    """腾讯 smartbox 跨市场搜索 — 返回 A股/ETF/指数/港股/美股 匹配项。

    API 响应格式: v_hint="market~code~\\uXXXX_name~pinyin~category^..."
    返回列表每项: {code, name, market, exchange}
      A股/ETF/指数 → 6位纯数字
      港股 → HK + 5位零填充 (如 HK00700)
      美股 → US + 大写代码 (如 USAAPL)
    """
    import json as _json
    import urllib.parse as _up
    url = "https://smartbox.gtimg.cn/s3/?v=2&q=" + _up.quote(q) + "&t=all&c=1"
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        req.add_header("Referer", "https://gu.qq.com/")
        raw = urllib.request.urlopen(req, timeout=5).read().decode("utf-8", errors="replace")
    except Exception:
        return []

    # v_hint="market~code~\uXXXX~pinyin~category^..."
    if "v_hint=" not in raw:
        return []
    # 去掉 v_hint=" 和结尾 "
    inner = raw.split("v_hint=", 1)[1]
    if inner.startswith('"'):
        inner = inner[1:]
    if inner.endswith('"'):
        inner = inner[:-1]

    def _decode_name(s: str) -> str:
        """把 \\uXXXX 序列解码为中文字符。"""
        try:
            return _json.loads(f'"{s}"')
        except Exception:
            return s

    items: list[dict] = []
    for entry in inner.split("^"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("~")
        if len(parts) < 3:
            continue
        market_raw = parts[0].lower()   # sh / sz / bj / hk / us
        short_code = parts[1]           # 00700 / aapl.oq / 510300
        raw_name = parts[2]             # \\u817e\\u8baf\\u63a7\\u80a1
        category = parts[4].upper() if len(parts) > 4 else ""

        # 跳过不需要的品种（如权证 QZ、认购证等）
        if category in ("QZ", "WR"):
            continue

        name = _decode_name(raw_name)
        if not name or not short_code:
            continue

        if market_raw == "hk":
            stored = "HK" + short_code.zfill(5).upper()
            mkt = "港股"
            exchange = "HK"
        elif market_raw == "us":
            # 去除 .oq / .n / .ps 交易所后缀
            ticker = short_code.split(".")[0].upper()
            stored = "US" + ticker
            mkt = "美股"
            exchange = "US"
        elif market_raw in ("sh", "sz", "bj"):
            stored = short_code
            exchange = market_raw.upper()
            if category == "ETF" or (stored.startswith(("5", "1")) and len(stored) == 6):
                mkt = "ETF"
            elif category in ("ZS", "ZSZ") or stored.startswith(("000", "399")):
                mkt = "指数"
            else:
                mkt = "A股"
        else:
            continue

        items.append({"code": stored, "name": name, "market": mkt, "exchange": exchange})
        if len(items) >= limit:
            break
    return items


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
