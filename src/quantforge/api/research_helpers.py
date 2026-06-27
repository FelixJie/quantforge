"""研报路由纯辅助逻辑（从 routes/research.py 抽出，降低单文件体积）。

本模块只放**无 FastAPI 路由、无跨 worker 运行态**的纯辅助：
- 东财/同花顺/腾讯等外部数据抓取（requests 同步函数，供 to_thread 调用）；
- 研报记录字段标准化、入库前转换；
- LLM 返回 JSON 的容错解析（_strip_json/_repair_json_text/_loads_lenient/_chat_json）；
- 事实块/摘要格式化、BOM 叶子遍历、ETA 估算等纯计算。

运行态进度表 _DbBackedTasks / _RUNNING_TASKS、任务文件读写、所有 @router 端点、
后台调度器、prompt 常量仍留在 routes/research.py（与端点/状态强耦合）。
routes/research.py 通过 `from ..research_helpers import ...` 复用并 re-export，
故 ai_picks/stock_analysis 等对 routes.research 的既有 import 路径保持不变。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta

from loguru import logger
import pandas as pd
import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
REPORT_API = "https://reportapi.eastmoney.com/report/list"

# 研报采集回溯窗口：近一年（365 天）。全市场研报已落库（见 report_sync_scheduler），
# 分析优先读库，故窗口拉到一年覆盖完整景气周期。
_REPORT_LOOKBACK_DAYS = 365

# 东财数据中心通用查询
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# 东财研报行业分类（/report/bk）—— 用于把关键词映射到 industryCode 做服务端过滤
_BK_URL = "https://reportapi.eastmoney.com/report/bk"
_INDUSTRY_CACHE: list[dict] = []  # [{"code","name"}]


# ── 东财数据中心通用查询 ──
def _eastmoney_datacenter(report_name: str, columns: str = "ALL",
                          filter_str: str = "", page_size: int = 50,
                          sort_columns: str = "", sort_types: str = "-1") -> list[dict]:
    """东财数据中心统一查询 — 龙虎榜/解禁/融资融券/大宗交易/股东户数/分红 共用"""
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


# ── 研报查询 ──
def _eastmoney_reports(code: str, max_pages: int = 10, page_size: int = 100,
                        begin_time: str = None, end_time: str = None) -> list[dict]:
    """拉取指定股票的研报列表

    Args:
        code: 股票代码
        max_pages: 最大页数
        page_size: 每页数量
        begin_time: 开始时间 YYYY-MM-DD，默认近半年
        end_time: 结束时间 YYYY-MM-DD，默认今天
    """
    if not begin_time:
        begin_time = (datetime.now() - timedelta(days=_REPORT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    if not end_time:
        end_time = "2030-01-01"

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
    all_records = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": str(page_size), "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": begin_time, "endTime": end_time,
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": code, "rcode": "",
            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
        }
        try:
            r = session.get(REPORT_API, params=params, timeout=30)
            d = r.json()
            rows = d.get("data") or []
            if not rows:
                break
            all_records.extend(rows)
            if page >= (d.get("TotalPage", 1) or 1):
                break
            time.sleep(0.1)  # 减少延迟
        except Exception as e:
            print(f"第 {page} 页获取失败: {e}")
            break
    return all_records


def _rf(v):
    """研报字段 → float（空串/None → None）。"""
    try:
        if v in (None, "", "-"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm_report_row(code: str, r: dict) -> dict:
    """东财研报记录 → stock_reports 行。"""
    return {
        "info_code":     r.get("infoCode"),
        "code":          code,
        "title":         r.get("title", ""),
        "org":           r.get("orgSName") or r.get("orgName") or "",
        "rating":        r.get("emRatingName") or r.get("sRatingName") or "",
        "rating_change": str(r.get("ratingChange") or ""),
        "publish_date":  (r.get("publishDate") or "")[:10],
        "target_price":  _rf(r.get("indvAimPriceT")) or _rf(r.get("indvAimPriceL")),
        "eps_this":      _rf(r.get("predictThisYearEps")),
        "pe_this":       _rf(r.get("predictThisYearPe")),
        "eps_next":      _rf(r.get("predictNextYearEps")),
        "pe_next":       _rf(r.get("predictNextYearPe")),
        "eps_next2":     _rf(r.get("predictNextTwoYearEps")),
        "pe_next2":      _rf(r.get("predictNextTwoYearPe")),
    }


def _norm_industry_report_row(r: dict) -> dict:
    """东财行业研报记录 → industry_reports 行。"""
    return {
        "info_code":     r.get("infoCode"),
        "industry_code": str(r.get("industryCode") or r.get("emIndustryCode") or ""),
        "industry_name": r.get("industryName") or r.get("indvInduName") or "",
        "title":         r.get("title", ""),
        "org":           r.get("orgSName") or r.get("orgName") or "",
        "rating":        r.get("emRatingName") or r.get("sRatingName") or "",
        "publish_date":  (r.get("publishDate") or "")[:10],
    }


def _fetch_all_reports_pages(qtype: str, begin_time: str, end_time: str = "2030-01-01",
                             max_pages: int = 400, page_size: int = 100,
                             sleep_s: float = 0.12) -> list[dict]:
    """全市场翻页拉取研报（qType=0 个股 / qType=1 行业），同步阻塞，供 to_thread 调用。

    单页失败重试 1 次后跳过该页（劫持是间歇性的，不让单页拖垮整轮）。
    """
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
    out: list[dict] = []
    total_pages = max_pages
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": str(page_size), "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": begin_time, "endTime": end_time,
            "pageNo": str(page), "qType": qtype,
        }
        rows = None
        for attempt in range(2):
            try:
                r = session.get(REPORT_API, params=params, timeout=40)
                d = r.json()
                rows = d.get("data") or []
                total_pages = min(total_pages, d.get("TotalPage", max_pages) or max_pages)
                break
            except Exception as e:
                if attempt == 1:
                    logger.debug(f"sync qType={qtype} page {page} failed: {e}")
        if not rows:
            if page >= total_pages:
                break
            continue  # 单页失败，继续下一页
        out.extend(rows)
        if page >= total_pages:
            break
        time.sleep(sleep_s)
    return out


# ── 研报入库（按 feed 类型 / 混合分流）──
def _store_reports(code: str, raw: list[dict]) -> int:
    """把东财研报原始记录入库（stock_reports），返回入库篇数。"""
    from quantforge.data.storage import db_cache
    rows = [_norm_report_row(code, r) for r in raw if r.get("infoCode")]
    return db_cache.reports_upsert_many(rows) if rows else 0


def _store_stock_reports(raw: list[dict]) -> int:
    """qType=0 个股研报原始记录 → stock_reports（按 stockCode）。无 stockCode 的丢弃。"""
    from quantforge.data.storage import db_cache
    rows = []
    for r in raw:
        sc = (r.get("stockCode") or "").strip()
        if r.get("infoCode") and sc and sc.isdigit():
            rows.append(_norm_report_row(sc, r))
    return db_cache.reports_upsert_many(rows) if rows else 0


def _store_industry_reports(raw: list[dict]) -> int:
    """qType=1 行业研报原始记录 → industry_reports。"""
    from quantforge.data.storage import db_cache
    rows = [_norm_industry_report_row(r) for r in raw if r.get("infoCode")]
    return db_cache.industry_reports_upsert_many(rows) if rows else 0


def _store_reports_mixed(raw: list[dict]) -> tuple[int, int]:
    """实时回补混合结果分流入库：有 stockCode → stock_reports，否则 → industry_reports。

    仅用于 _collect_reports 的 gap-fill（来源混合，按 stockCode 区分）；全量同步走
    _store_stock_reports / _store_industry_reports 按 feed 类型显式入库。
    返回 (个股篇数, 行业篇数)。
    """
    from quantforge.data.storage import db_cache
    stock_rows, ind_rows = [], []
    for r in raw:
        if not r.get("infoCode"):
            continue
        sc = (r.get("stockCode") or "").strip()
        if sc and sc.isdigit():
            stock_rows.append(_norm_report_row(sc, r))
        else:
            ind_rows.append(_norm_industry_report_row(r))
    n_stock = db_cache.reports_upsert_many(stock_rows) if stock_rows else 0
    n_ind = db_cache.industry_reports_upsert_many(ind_rows) if ind_rows else 0
    return n_stock, n_ind


# ── 同花顺一致预期EPS ──
def _ths_consensus_eps(code: str) -> list[dict]:
    """同花顺一致预期EPS — 直连 basic.10jqka.com.cn"""
    url = f"https://basic.10jqka.com.cn/{code}/gsyj.html"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')
        rows = soup.select("table tbody tr")
        result = []
        for tr in rows:
            tds = tr.select("td")
            if len(tds) >= 4:
                result.append({
                    "year": tds[0].text.strip(),
                    "eps": tds[1].text.strip(),
                    "institution_count": tds[2].text.strip(),
                    "rating": tds[3].text.strip(),
                })
        return result
    except Exception:
        return []


# ── 概念板块相关 ──
def _get_concept_stocks(concept_name: str) -> list[dict]:
    """根据概念名称获取成分股 (使用百度股市通或同花顺)"""
    try:
        # 简单实现：先尝试获取百度概念
        search_url = f"https://finance.pae.baidu.com/api/getrelatedstock?code=&market=ab&newFormat=1&finClientType=pc&query={concept_name}"
        headers = {"User-Agent": UA, "Origin": "https://gushitong.baidu.com", "Referer": "https://gushitong.baidu.com/"}
        r = requests.get(search_url, headers=headers, timeout=10)
        data = r.json()
        if data.get("Result") and data["Result"].get("list"):
            return [{"code": s["code"], "name": s["name"]} for s in data["Result"]["list"][:30]]
    except Exception as e:
        logger.warning(f"Failed to fetch concept {concept_name}: {e}")
    return []


def _normalise_cons_stocks(df: "pd.DataFrame") -> list[dict]:
    """标准化成分股数据"""
    result = []
    for _, row in df.iterrows():
        try:
            result.append({
                "code": str(row.iloc[1]),
                "name": str(row.iloc[2]),
                "price": float(row.iloc[3]) if pd.notna(row.iloc[3]) else None,
                "change_pct": float(row.iloc[5]) if pd.notna(row.iloc[5]) else None,
                "volume": float(row.iloc[6]) if pd.notna(row.iloc[6]) else None,
                "turnover": float(row.iloc[7]) if pd.notna(row.iloc[7]) else None,
                "high": float(row.iloc[9]) if pd.notna(row.iloc[9]) else None,
                "low": float(row.iloc[10]) if pd.notna(row.iloc[10]) else None,
                "turnover_rate": float(row.iloc[13]) if len(row) > 13 and pd.notna(row.iloc[13]) else None,
                "pe": float(row.iloc[14]) if len(row) > 14 and pd.notna(row.iloc[14]) else None,
                "pb": float(row.iloc[15]) if len(row) > 15 and pd.notna(row.iloc[15]) else None,
            })
        except Exception:
            continue
    return result


# ── 研报行业分类 / industryCode 匹配 ──
def _report_industries() -> list[dict]:
    """获取并缓存东财研报行业分类列表（约 500 个）。"""
    global _INDUSTRY_CACHE
    if _INDUSTRY_CACHE:
        return _INDUSTRY_CACHE
    try:
        r = requests.get(_BK_URL, params={"bkCode": "016"},
                         headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"}, timeout=15)
        data = r.json().get("data") or []
        _INDUSTRY_CACHE = [{"code": x.get("bkCode"), "name": x.get("bkName", "")}
                           for x in data if x.get("bkCode")]
    except Exception as e:
        logger.debug(f"report industries fetch failed: {e}")
    return _INDUSTRY_CACHE


def _match_industry_codes(terms, limit: int = 12) -> list[str]:
    """把关键词/细分词模糊匹配到研报行业代码（双向子串匹配）。"""
    if isinstance(terms, str):
        terms = [terms]
    terms = [t.strip() for t in (terms or []) if t and t.strip()]
    if not terms:
        return []
    inds = _report_industries()
    codes: list[str] = []
    for ind in inds:
        name = ind["name"]
        for t in terms:
            # 行业名包含关键词，或关键词包含行业名（行业名通常更短，如“电池”⊂“固态电池”）
            if (t in name) or (len(name) >= 2 and name in t):
                if ind["code"] not in codes:
                    codes.append(ind["code"])
                break
        if len(codes) >= limit:
            break
    return codes


def _eastmoney_reports_by_industry(industry_codes: list[str], qtype: str = "1",
                                   max_pages: int = 10, page_size: int = 100,
                                   begin_time: str = None) -> list[dict]:
    """按 industryCode 服务端过滤拉取研报（qType=1 行业 / qType=0 个股），逐行业翻页。

    这是“上千篇”的主力来源：行业研报按板块归类，单板块一年可达数百~上千篇，
    远多于逐只个股累加的量，且无需标题子串匹配。
    """
    if not industry_codes:
        return []
    if not begin_time:
        begin_time = (datetime.now() - timedelta(days=_REPORT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
    out: list[dict] = []
    for ic in industry_codes:
        for page in range(1, max_pages + 1):
            params = {
                "industryCode": ic, "pageSize": str(page_size), "industry": "*",
                "rating": "*", "ratingChange": "*",
                "beginTime": begin_time, "endTime": "2030-01-01",
                "pageNo": str(page), "qType": qtype,
            }
            try:
                r = session.get(REPORT_API, params=params, timeout=30)
                d = r.json()
                rows = d.get("data") or []
                if not rows:
                    break
                out.extend(rows)
                if page >= (d.get("TotalPage", 1) or 1):
                    break
                time.sleep(0.05)
            except Exception as e:
                logger.debug(f"industry {ic} page {page} failed: {e}")
                break
    return out


def _eastmoney_industry_reports(terms, max_pages: int = 8, page_size: int = 100,
                                begin_time: str = None) -> list[dict]:
    """拉取行业研报(qType=1)并按标题/行业名包含任一关键词过滤（默认近半年）。

    terms: 字符串或字符串列表，命中其中任一即收录。
    """
    if isinstance(terms, str):
        terms = [terms]
    terms = [t for t in (terms or []) if t]
    if not begin_time:
        begin_time = (datetime.now() - timedelta(days=_REPORT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
    out = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": str(page_size), "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": begin_time, "endTime": "2030-01-01",
            "pageNo": str(page), "qType": "1",
        }
        try:
            r = session.get(REPORT_API, params=params, timeout=30)
            rows = r.json().get("data") or []
            if not rows:
                break
            for x in rows:
                blob = f"{x.get('title','')}{x.get('industryName','')}"
                if any(t in blob for t in terms):
                    out.append(x)
            time.sleep(0.1)
        except Exception as e:
            logger.debug(f"industry reports page {page} failed: {e}")
            break
    return out


def _smartbox(query: str) -> list[dict]:
    """腾讯 smartbox 股票检索：名称/代码 → [{code,name}]（仅 A 股 GP）。"""
    try:
        r = requests.get(f"https://smartbox.gtimg.cn/s3/?q={query}&t=all",
                         headers={"User-Agent": UA}, timeout=10)
        r.encoding = "gbk"
        text = r.text
    except Exception:
        return []
    m = re.search(r'v_hint="(.*)"', text)
    if not m or m.group(1) == "N":
        return []
    out = []
    for rec in m.group(1).split("^"):
        parts = rec.split("~")
        if len(parts) >= 5 and parts[4].startswith("GP") and parts[1].isdigit():
            name = parts[2]
            if "\\u" in name:  # smartbox 返回的是 \uXXXX 字面量
                try:
                    name = json.loads(f'"{name}"')
                except Exception:
                    pass
            out.append({"code": parts[1], "name": name})
    return out


# ── 已入库研报 → 东财原始字段形态（供 MAP/REDUCE 管线消费）──
def _stored_stock_report_to_raw(r: dict) -> dict:
    """stock_reports 行 → 东财原始字段形态。"""
    return {
        "infoCode": r.get("info_code"), "stockCode": r.get("code"),
        "title": r.get("title", ""), "orgSName": r.get("org", ""),
        "emRatingName": r.get("rating", ""), "publishDate": r.get("publish_date", ""),
        "predictThisYearEps": r.get("eps_this"), "predictThisYearPe": r.get("pe_this"),
        "predictNextYearEps": r.get("eps_next"), "predictNextYearPe": r.get("pe_next"),
    }


def _stored_industry_report_to_raw(r: dict) -> dict:
    """industry_reports 行 → 东财原始字段形态。"""
    return {
        "infoCode": r.get("info_code"), "title": r.get("title", ""),
        "orgSName": r.get("org", ""), "emRatingName": r.get("rating", ""),
        "publishDate": r.get("publish_date", ""),
        "industryName": r.get("industry_name", ""),
        "industryCode": r.get("industry_code", ""),
    }


# ── LLM JSON 容错解析 ──
def _strip_json(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    if text.endswith("```"):
        text = text[:text.rfind("```")].strip()
    return text


def _repair_json_text(s: str) -> str:
    """结构化修复 LLM 产出的近似 JSON 中段缺陷（截断由 _loads_lenient 的括号补全兜底）。

    思考型模型（如 MiniMax）在深层嵌套 schema 上常犯**中段**错误，现有的“补尾部”
    修复救不回，这里单遍扫描专治三类：
      1) 字符串内的裸控制符（真实换行/制表符）→ 转义；
      2) 字符串内的裸双引号（启发式：后面紧跟的非空白不是 , } ] : 或结尾，就当正文转义掉）；
      3) 相邻值之间漏逗号（}{、]"、"a""b"、数字后接新值等）→ 补逗号；并删掉 } ] 前的尾随逗号。
    """
    start = min([i for i in (s.find("{"), s.find("[")) if i >= 0], default=-1)
    if start < 0:
        return s
    s = s[start:]
    out: list[str] = []
    in_str = False
    esc = False
    prev = ""            # 串外最近一个有意义字符的“类别”：{ [ } ] : , S(闭合串) V(标量)
    _closers = {"S", "}", "]", "V"}
    _ctrl = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
    n = len(s)
    i = 0
    while i < n:
        ch = s[i]
        if in_str:
            if esc:
                out.append(ch); esc = False; i += 1; continue
            if ch == "\\":
                out.append(ch); esc = True; i += 1; continue
            if ch == '"':
                j = i + 1
                while j < n and s[j] in " \t\r\n":
                    j += 1
                nxt = s[j] if j < n else ""
                # 后接 , } ] : " 或结尾 → 视为真正的闭合引号（含两个字符串值间漏逗号的情况）
                if nxt in ',}]:"' or nxt == "":
                    out.append('"'); in_str = False; prev = "S"; i += 1; continue
                out.append('\\"'); i += 1; continue  # 裸内引号 → 转义为正文
            if ch in _ctrl:
                out.append(_ctrl[ch]); i += 1; continue
            if ord(ch) < 0x20:
                out.append("\\u%04x" % ord(ch)); i += 1; continue
            out.append(ch); i += 1; continue
        # 串外
        if ch in " \t\r\n":
            out.append(ch); i += 1; continue
        if ch == '"':
            if prev in _closers:
                out.append(",")
            out.append('"'); in_str = True; i += 1; continue
        if ch in "{[":
            if prev in _closers:
                out.append(",")
            out.append(ch); prev = ch; i += 1; continue
        if ch in "}]":
            k = len(out) - 1                         # 删尾随逗号
            while k >= 0 and out[k] in " \t\r\n":
                k -= 1
            if k >= 0 and out[k] == ",":
                del out[k]
            out.append(ch); prev = ch; i += 1; continue
        if ch == ":":
            out.append(ch); prev = ":"; i += 1; continue
        if ch == ",":
            out.append(ch); prev = ","; i += 1; continue
        # 标量整体消费（数字/true/false/null），避免在标量内部误插逗号
        m = re.match(r"[^\s,{}\[\]\":]+", s[i:])
        tok = m.group(0) if m else ch
        if prev in _closers:
            out.append(",")
        out.append(tok); prev = "V"; i += len(tok)
    return "".join(out)


def _loads_lenient(text: str):
    """解析 AI 返回的 JSON；先结构化修复中段缺陷，再补全尾部截断的字符串/括号。"""
    s = _strip_json(text)
    try:
        return json.loads(s)
    except Exception:
        pass
    # 结构化修复中段缺陷（漏逗号/裸引号/裸控制符）后再试
    try:
        return json.loads(_repair_json_text(s))
    except Exception:
        pass
    # 截取从首个 { 或 [ 开始，并先做结构化修复，再处理尾部截断
    start = min([i for i in (s.find("{"), s.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no json found")
    s = _repair_json_text(s[start:])
    # 逐步回退到最后一个能解析的平衡点
    stack, in_str, esc, last_ok = [], False, False, -1
    pairs = {"}": "{", "]": "["}
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack and stack[-1] == pairs[ch]:
                stack.pop()
                if not stack:
                    last_ok = i
    if last_ok >= 0:
        try:
            return json.loads(s[:last_ok + 1])
        except Exception:
            pass
    # 用补全括号的方式兜底（补括号前先去掉尾随逗号，否则会变成非法的 ,] / ,}）
    repair = s
    if in_str:
        repair += '"'
    else:
        repair = re.sub(r",\s*$", "", repair)
    repair += "".join("}" if c == "{" else "]" for c in reversed(stack))
    return json.loads(repair)


async def _chat_json(system: str, user: str, max_tokens: int, caller: str, retries: int = 2,
                     provider: str | None = None, timeout: float | None = None,
                     patient: bool = False, cancel_cb=None, on_wait=None):
    """调用 AI 并解析 JSON；解析失败时重试（附加"只输出合法 JSON"的提示）。

    ``provider`` 可指定本次调用的主 provider（如 "claude-code" 走本地 Opus 4.8），
    不可用时 chat() 会自动跌回 HTTP 链。
    ``timeout`` 覆盖单次调用超时（秒）；REDUCE 等大上下文调用应传更宽松的值。
    ``patient``/``cancel_cb``/``on_wait`` 透传给 chat()：开「耐心重试」让 429 限流不中断
    流程（REDUCE 等长任务用），长等待期间可取消并刷新心跳。
    """
    from quantforge.api.ai_client import chat
    last_err = None
    for attempt in range(retries + 1):
        u = user if attempt == 0 else (
            user + "\n\n注意：上次输出不是合法 JSON。请只输出**严格合法**的 JSON，"
                   "确保所有字符串闭合、对象/数组括号配对、键值之间有逗号。")
        try:
            txt = await chat(system=system, user=u, max_tokens=max_tokens, caller=caller,
                             provider=provider, timeout=timeout,
                             patient=patient, cancel_cb=cancel_cb, on_wait=on_wait)
            return _loads_lenient(txt)
        except Exception as e:
            last_err = e
            logger.debug(f"{caller} JSON parse failed (attempt {attempt}): {e}")
    raise last_err


# ── 事实块/摘要格式化、BOM 叶子遍历、ETA 估算等纯计算 ──
def _bom_leaves(bom: list) -> list[dict]:
    """收集 BOM 所有叶子节点，返回 [{path, node}]（path 为层级路径字符串）。"""
    leaves = []

    def walk(nodes, trail):
        for n in nodes or []:
            name = n.get("name", "")
            path = trail + [name]
            children = n.get("children") or []
            if children:
                walk(children, path)
            else:
                leaves.append({"path": ">".join(path), "node": n})

    walk(bom, [])
    return leaves


def _bom_all_nodes(bom: list) -> list[dict]:
    """收集 BOM **所有层级**节点（含中间环节，非仅叶子），返回 [{path, node}]。

    供「成本构成每个层级都挂龙头/弹性票」：从顶层大类到最细环节，每个节点都要推荐个股。
    """
    nodes_out: list[dict] = []

    def walk(nodes, trail):
        for n in nodes or []:
            name = n.get("name", "")
            path = trail + [name]
            nodes_out.append({"path": ">".join(path), "node": n})
            children = n.get("children") or []
            if children:
                walk(children, path)

    walk(bom, [])
    return nodes_out


def _slug(keyword: str) -> str:
    """关键词 → 稳定且文件名安全的 slug。"""
    norm = (keyword or "").strip().lower()
    return "kw_" + hashlib.md5(norm.encode("utf-8")).hexdigest()[:10]


def _s(v) -> str:
    """把 LLM 可能返回的 dict/list/标量统一成短字符串。

    MAP 抽取由模型生成，字段类型并不保证：约定是 string 的 leaders 可能回成
    [{"name":..}]，约定是 object 的 segments 可能回成纯字符串。join 前一律过这里，
    避免 `expected str instance, dict found` 之类的类型崩溃。
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        for k in ("name", "company", "event", "module", "tech", "title", "desc"):
            if v.get(k):
                return str(v[k])
        return "/".join(str(x) for x in v.values() if x not in (None, ""))[:40]
    if isinstance(v, (list, tuple)):
        return ", ".join(_s(x) for x in v)
    return str(v)


def _as_dict(x) -> dict:
    """列表项规整成 dict：本就是 dict 直接用；纯字符串当成 {'name': x}。"""
    return x if isinstance(x, dict) else {"name": _s(x)}


def _fact_block(f: dict) -> str:
    """单篇事实 → 详细文本块（多行，含环节占比/卡脖子/目标价/里程碑/替代风险等）。

    所有列表字段对元素类型做兜底（_as_dict/_s），容忍模型返回的类型抖动。
    """
    segs = [_as_dict(s) for s in (f.get("segments") or [])[:8]]
    seg = "; ".join(
        f"{_s(s.get('name'))}={s.get('percent')}%({_s(s.get('note'))})" if s.get("percent") is not None
        else f"{_s(s.get('name'))}({_s(s.get('note'))})"
        for s in segs
    )
    parts = [f"·[{_s(f.get('_org'))}|{_s(f.get('_date'))}] {_s(f.get('key_points'))}"]
    if seg:
        parts.append(f"  环节占比: {seg}")
    if f.get("bottleneck"):
        parts.append(f"  卡脖子: {_s(f['bottleneck'])}")
    if f.get("irreplaceable"):
        parts.append(f"  不可替代: {_s(f['irreplaceable'])}")
    if f.get("fastest_catchup"):
        parts.append(f"  追赶最快: {_s(f['fastest_catchup'])}")
    if f.get("leaders"):
        parts.append(f"  龙头: {_s(f['leaders'][:5] if isinstance(f['leaders'], list) else f['leaders'])}")
    if f.get("leader_gap"):
        parts.append(f"  差距: {_s(f['leader_gap'])}")
    if f.get("targets"):
        tgs = [_as_dict(t) for t in f["targets"][:5]]
        tg = "; ".join(f"{_s(t.get('name'))}目标价{t.get('target_price')}({_s(t.get('rating'))})"
                       for t in tgs if t.get("name"))
        if tg:
            parts.append(f"  目标价: {tg}")
    if f.get("milestones"):
        mss = [_as_dict(m) for m in f["milestones"][:4]]
        ms = "; ".join(f"{_s(m.get('date'))}:{_s(m.get('event'))}" for m in mss)
        parts.append(f"  里程碑: {ms}")
    if f.get("substitution"):
        subs = [_as_dict(s) for s in f["substitution"][:4]]
        sub = "; ".join(f"{_s(s.get('module'))}-{_s(s.get('tech'))}({_s(s.get('risk'))})"
                        for s in subs)
        parts.append(f"  替代风险: {sub}")
    if f.get("equipment"):
        eqs = [_as_dict(e) for e in f["equipment"][:6]]
        eq = "; ".join(
            f"{_s(e.get('name'))}[{_s(e.get('process'))}]厂商:{_s(e.get('makers'))}"
            f"{('国产化:' + _s(e.get('localization'))) if e.get('localization') else ''}"
            for e in eqs if e.get("name")
        )
        if eq:
            parts.append(f"  生产设备: {eq}")
    return "\n".join(parts)


def _fact_line(f: dict) -> str:
    """单篇事实 → 单行紧凑表示（仅核心：机构/日期/结论 + 前 3 个占比环节）。"""
    segs = [_as_dict(s) for s in (f.get("segments") or [])[:3]]
    seg = "; ".join(
        f"{_s(s.get('name'))}{('=' + str(s.get('percent')) + '%') if s.get('percent') is not None else ''}"
        for s in segs if s.get("name")
    )
    line = f"·[{_s(f.get('_org'))}|{_s(f.get('_date'))}] {_s(f.get('key_points'))}"
    if seg:
        line += f" 〔{seg}〕"
    return line


def _facts_digest(facts: list[dict], limit_chars: int = 60000) -> str:
    """把**全部**逐篇事实压缩成文本，供 REDUCE 阶段使用（不丢弃任何研报）。

    优先用详细块；若全部详细块超出预算，则自动降级为「1 篇 1 行」紧凑表示，
    确保数百~上千篇研报的事实都能进入合成，而不是被截断丢弃（全量分析）。
    """
    if not facts:
        return ""
    blocks = [_fact_block(f) for f in facts]
    if sum(len(b) + 1 for b in blocks) <= limit_chars:
        return "\n".join(blocks)
    # 预算不足：降级为单行表示，保证全量覆盖
    lines = [_fact_line(f) for f in facts]
    if sum(len(l) + 1 for l in lines) <= limit_chars:
        return ("（研报较多，已压缩为每篇一行的关键结论，覆盖全部研报）\n"
                + "\n".join(lines))
    # 仍超预算（极端海量）：按预算等距抽样到单行上限，并标注实际覆盖比例
    longest = max(len(l) for l in lines) + 1
    per = max(1, limit_chars // longest)
    if per >= len(lines):
        return "\n".join(lines)[:limit_chars]
    step = len(lines) / per
    picked = [lines[int(i * step)] for i in range(per)]
    return (f"（研报极多，共 {len(facts)} 篇，已等距抽样 {per} 篇关键结论以适配上下文上限）\n"
            + "\n".join(picked))


def _fmt_eta(seconds: float) -> str:
    """秒 → 人类可读的预计时长。"""
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    if m <= 0:
        return f"约 {max(s, 5)} 秒"
    return f"约 {m} 分钟" if not s else f"约 {m} 分 {s} 秒"


# 经验系数：单篇平均下载+抽取耗时、单个 MAP 批次耗时（秒）
_T_PER_PDF = 0.45      # 16 并行下,单篇均摊
# 一个并发波次(=concurrency 个批次并发)的真实墙钟耗时。MAP 每批要让 LLM 读 8 篇研报
# 正文并抽事实，思考型模型(MiniMax 等)单批可达 40~80s，整波也就一批量级。原值 7s 是
# 严重低估的来源（实测一次全量精读 MAP 段 8~13 分钟，旧公式只估 1~2 分钟）。这里取偏
# 保守的经验值作「开跑前的初值」；任务一旦进入 MAP，ETA 改由实测吞吐自适应外推(见
# research.py 的 _map_progress)，不再吃这个静态系数。可经 QF_T_PER_MAP_WAVE 调。
_T_PER_MAP_WAVE = float(os.getenv("QF_T_PER_MAP_WAVE") or 55.0)
# MAP 之后还有 REDUCE 六路合成 + BOM/上中下游/链主个股匹配，这段固定尾巴单独计。
# 思考型模型单路 REDUCE 可达数分钟(QF_LLM_TIMEOUT 常设 240)，给个保守尾段。
_T_REDUCE_TAIL = float(os.getenv("QF_T_REDUCE_TAIL") or 120.0)
# MAP 并发可经环境变量下调：单 LLM 号(如 MiniMax 单扛)高并发会触发 529 限流，
# _MAP_CONC×_MAP_BATCH 个请求同时打过去会全卡在重试/超时里 → 任务卡死。
# 默认保持 8/8/16(多号/高配场景)，单号部署用 QF_MAP_CONC=3 之类下调即可。
_MAP_BATCH = int(os.getenv("QF_MAP_BATCH") or 8)
_MAP_CONC = int(os.getenv("QF_MAP_CONC") or 8)
_DL_WORKERS = int(os.getenv("QF_DL_WORKERS") or 16)
# MAP 单批输出上限：一批 _MAP_BATCH 篇研报的事实 JSON 若超过 max_tokens 会被硬截断
# (中文 JSON ~2 字符/token，4096 token≈8500 字符，batch=8 常溢出 → 解析失败、整批丢)。
# 默认抬到 8192 给 batch=8 留足头寸；批量调用用此值，失败重试再 +2048。可经环境变量调。
_MAP_MAX_TOKENS = int(os.getenv("QF_MAP_MAX_TOKENS") or 8192)


def _estimate_eta(n_reports: int) -> int:
    """根据研报篇数粗估「精读全部」总耗时（秒）——仅作 MAP 开跑前的初值。

    任务进入 MAP 后由实测吞吐自适应外推取代（远比静态系数准），见
    research.py `_map_progress`。
    """
    dl = n_reports * _T_PER_PDF / 4          # 下载+抽取(16 并行、缓存命中多,取经验系数)
    batches = max(1, (n_reports + _MAP_BATCH - 1) // _MAP_BATCH)
    waves = (batches + _MAP_CONC - 1) // _MAP_CONC
    return int(dl + waves * _T_PER_MAP_WAVE + _T_REDUCE_TAIL)
