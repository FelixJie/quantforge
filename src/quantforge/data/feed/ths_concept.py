"""同花顺(THS) 概念板块数据源 (q.10jqka.com.cn)。

概念板块改用**同花顺指数**：板块列表、板块涨跌幅(指数)、成分股全部取自同花顺，
取代原新浪概念源(newFLJK —— 词条窄、无指数行情)。行业板块仍走新浪。

数据通路（均经实测）::

    概念名录   ak.stock_board_concept_name_ths()                 → name→code，按天缓存
    板块指数   q.10jqka.com.cn/gn/detail/code/{code}/            → board-infos(最新指数/板块涨幅/涨跌家数/资金净流入/成交额)
    成分股     .../gn/detail/order/desc/page/{p}/ajax/1/code/{code}/  → 现价/涨跌幅/换手/流通市值/市盈率(翻页, 10/页)

反爬：需带 ``v`` cookie，由 akshare 附带的 ``ths.js`` 经 py_mini_racer 生成。
依赖(akshare/py_mini_racer/bs4/lxml/pandas)缺失或抓取失败时返回 None/[]，
调用方(见 :mod:`quantforge.api.routes.sector`)回退到陈旧缓存。
"""

from __future__ import annotations

import datetime as _dt
import math
import re
import threading
import time
import concurrent.futures as cf
from io import StringIO

from loguru import logger

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36"
)
_BASE = "http://q.10jqka.com.cn/gn"

_lock = threading.Lock()
_v_cache: dict = {"code": None, "ts": 0.0}
_name_cache: dict = {"map": None, "day": ""}

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


# ── 反爬 v cookie / 概念名录 ────────────────────────────────────────────────────

def _v_code() -> str | None:
    """生成 10jqka 反爬 ``v`` cookie（5 分钟内复用）。"""
    with _lock:
        if _v_cache["code"] and time.time() - _v_cache["ts"] < 300:
            return _v_cache["code"]
    try:
        import py_mini_racer
        from akshare.stock_feature.stock_board_concept_ths import _get_file_content_ths

        js = py_mini_racer.MiniRacer()
        js.eval(_get_file_content_ths("ths.js"))
        code = js.call("v")
    except Exception as e:
        logger.warning(f"THS v-code 生成失败: {e}")
        return None
    with _lock:
        _v_cache.update(code=code, ts=time.time())
    return code


def _headers(referer: str = f"{_BASE}/") -> dict | None:
    v = _v_code()
    if not v:
        return None
    return {"User-Agent": _UA, "Cookie": f"v={v}", "Referer": referer}


_NAME_DB_KEY = "ths_concept_name_map"
_NAME_DB_TTL = 7 * 24 * 3600  # 名录变动很慢，落库保留 7 天作回退


def name_map() -> dict:
    """概念名 → 概念代码 映射。

    内存按天缓存 → 失败回退「上次落库的名录」(DB, 7 天)。
    akshare 名录接口偶发反爬/解析空（'NoneType'…find_all），重启又丢内存缓存时，
    DB 回退能让概念板块继续可用，而不是整段抓不到。"""
    today = _dt.date.today().isoformat()
    with _lock:
        if _name_cache["map"] and _name_cache["day"] == today:
            return _name_cache["map"]
    try:
        import akshare as ak

        df = ak.stock_board_concept_name_ths()
        m = {str(r["name"]).strip(): str(r["code"]).strip() for _, r in df.iterrows()}
        if m:
            with _lock:
                _name_cache.update(map=m, day=today)
            try:
                from quantforge.data.storage import db_cache
                db_cache.set(_NAME_DB_KEY, m, _NAME_DB_TTL, category="sector")
            except Exception:
                pass
            return m
        logger.warning("THS 概念名录返回空，回退落库名录")
    except Exception as e:
        logger.warning(f"THS 概念名录获取失败: {e}")
    # 回退：先内存，再 DB 名录键，最后从已落库的概念板块快照(name→node)反推。
    if _name_cache["map"]:
        return _name_cache["map"]
    try:
        from quantforge.data.storage import db_cache
        stale = db_cache.get(_NAME_DB_KEY, ttl_seconds=10 ** 9)
        if stale:
            with _lock:
                _name_cache.update(map=stale, day=today)
            logger.info(f"THS 概念名录回退落库缓存: {len(stale)} 个")
            return stale
        # 终极回退：用上次成功的概念板块快照重建名录（自愈，接口被封也可用）
        boards = db_cache.get_sector_boards("concept") or []
        m = {b["name"]: b["node"] for b in boards if b.get("name") and b.get("node")}
        if m:
            with _lock:
                _name_cache.update(map=m, day=today)
            db_cache.set(_NAME_DB_KEY, m, _NAME_DB_TTL, category="sector")
            logger.info(f"THS 概念名录由板块快照重建: {len(m)} 个")
            return m
    except Exception as e:
        logger.debug(f"THS 概念名录 DB 回退失败: {e}")
    return {}


# ── 数值解析 ────────────────────────────────────────────────────────────────────

def _f(v) -> float | None:
    try:
        x = float(str(v).replace(",", ""))
        return None if math.isnan(x) or math.isinf(x) else round(x, 4)
    except (TypeError, ValueError):
        return None


def _pct(s) -> float | None:
    """'4.85%' → 4.85。"""
    m = _NUM_RE.search(str(s))
    return round(float(m.group()), 4) if m else None


def _cn_amount(s) -> float | None:
    """'8.16亿' / '146.65万' / '1285.94' → 元。"""
    txt = str(s)
    m = _NUM_RE.search(txt)
    if not m:
        return None
    x = float(m.group())
    if "亿" in txt:
        x *= 1e8
    elif "万" in txt:
        x *= 1e4
    return round(x, 2)


# ── 板块指数 (board-infos) ──────────────────────────────────────────────────────

def _board_info(code: str, name: str) -> dict | None:
    import requests
    from bs4 import BeautifulSoup

    h = _headers(f"{_BASE}/detail/code/{code}/")
    if not h:
        return None
    r = requests.get(f"{_BASE}/detail/code/{code}/", headers=h, timeout=12)
    r.encoding = "gbk"
    bi = BeautifulSoup(r.text, "lxml").find("div", class_="board-infos")
    if not bi:
        return None
    info = {
        dt.text.strip(): dd.text.strip().replace("\n", "/")
        for dt, dd in zip(bi.find_all("dt"), bi.find_all("dd"))
    }

    def g(key: str):
        for k, v in info.items():
            if key in k:
                return v
        return None

    up = down = 0
    zj = g("涨跌家数")          # '60/0' → 涨/跌
    if zj and "/" in zj:
        a, b = (zj.split("/") + ["0", "0"])[:2]
        up = int(_f(a) or 0)
        down = int(_f(b) or 0)

    change_pct = _pct(g("板块涨幅"))
    # 成交额/资金净流入 的「亿」在标签里，值是裸数字 → 统一换算到元
    amount_yi = _f(g("成交额"))
    amount = round(amount_yi * 1e8, 2) if amount_yi is not None else None
    # board-infos 无「最新」，用 昨收 × (1+涨幅) 推算指数值
    prev = _f(g("昨收"))
    index_value = round(prev * (1 + change_pct / 100), 4) if (prev and change_pct is not None) else None
    return {
        "name":          name,
        "node":          code,
        "change_pct":    change_pct,
        "index_value":   index_value,
        "net_flow":      _f(g("资金净流入")),  # 亿元
        "amount":        amount,
        "market_cap":    amount,               # 热力图面积代理（概念无板块市值）
        "up_count":      up,
        "down_count":    down,
        "total":         up + down,
        "turnover_rate": None,
        "avg_pe":        None,
        "median_pe":     None,
        "avg_pb":        None,
        "leader":        "",
        "leader_change": None,
    }


def concept_boards(max_workers: int = 6) -> list[dict] | None:
    """全部概念板块（含同花顺指数涨跌幅），并发抓取。"""
    m = name_map()
    if not m:
        return None

    def task(item):
        name, code = item
        try:
            return _board_info(code, name)
        except Exception as e:
            logger.debug(f"THS 概念 board-info 失败 {name}: {e}")
            return None

    out: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for res in ex.map(task, list(m.items())):
            if res:
                out.append(res)
    # 残缺护栏：同花顺间歇 403 时大多数详情页失败，只回少数板块。若直接返回，调用方的
    # replace_sector_boards(DELETE+INSERT) 会用残缺结果覆盖掉完整快照(曾把 373→1)。
    # 成功率过低视为「抓取失败」返回 None，让调用方保留上次完整快照。
    attempted = len(m)
    if attempted and len(out) < attempted * 0.6:
        logger.warning(
            f"THS 概念板块抓取残缺 {len(out)}/{attempted}(疑似被封)，"
            f"按失败处理以保护已有完整快照"
        )
        return None
    out.sort(key=lambda b: b.get("change_pct") or -1e9, reverse=True)
    return out or None


# ── 成分股 ──────────────────────────────────────────────────────────────────────
# 列定位: 0序号 1代码 2名称 3现价 4涨跌幅(%) 5涨跌 6涨速 7换手(%)
#         8量比 9振幅(%) 10成交额 11流通股 12流通市值 13市盈率

def concept_stocks(name: str, max_pages: int = 80) -> list[dict] | None:
    """某概念的成分股（同花顺，翻页 10/页）。"""
    import requests
    import pandas as pd
    from bs4 import BeautifulSoup

    code = name_map().get(name)
    if not code:
        return None

    def fetch(page: int) -> str | None:
        h = _headers(f"{_BASE}/detail/code/{code}/")
        if not h:
            return None
        url = f"{_BASE}/detail/order/desc/page/{page}/ajax/1/code/{code}/"
        r = requests.get(url, headers=h, timeout=12)
        r.encoding = "gbk"
        return r.text

    first = fetch(1)
    if not first:
        return None

    # 总页数
    pages = 1
    try:
        pi = BeautifulSoup(first, "lxml").find("span", class_="page_info")
        if pi and "/" in pi.text:
            pages = min(int(pi.text.split("/")[1]), max_pages)
    except Exception:
        pages = 1

    out: list[dict] = []

    def parse(text: str) -> None:
        try:
            df = pd.read_html(StringIO(text))[0]
        except Exception:
            return
        for _, row in df.iterrows():
            try:
                raw = str(row.iloc[1]).split(".")[0].strip()
                code_s = raw.zfill(6) if raw.isdigit() else raw
                out.append({
                    "code":          code_s,
                    "name":          str(row.iloc[2]).strip(),
                    "price":         _f(row.iloc[3]),
                    "change_pct":    _f(row.iloc[4]),
                    "turnover_rate": _f(row.iloc[7]),
                    "turnover":      _cn_amount(row.iloc[10]),
                    "market_cap":    _cn_amount(row.iloc[12]),
                    "pe":            _f(row.iloc[13]),
                    "pb":            None,  # 同花顺成分股列表不含 PB
                })
            except Exception:
                continue

    parse(first)
    for page in range(2, pages + 1):
        txt = fetch(page)
        if not txt:
            break
        parse(txt)

    out.sort(key=lambda s: s.get("change_pct") or -1e9, reverse=True)
    return out or None
