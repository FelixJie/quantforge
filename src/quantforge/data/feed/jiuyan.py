"""韭研公社（jiuyangongshe.com）行情社区抓取。

韭研公社是 A 股题材/复盘社区，「题材行业」「个股研究」「资讯荟萃」等版块里
常含**产品涨价/调价/供需紧张**等一手线索，是「涨价逻辑」板块的重要源之一。

鉴权
====
站点用**固定密钥防爬签名**（非用户登录态），公开版块免登录即可读：

    headers = {
        "platform": 3,
        "timestamp": <毫秒时间戳>,
        "token": md5("Uu0KfOB8iUP69d3c:" + <毫秒时间戳>),
    }

接口
====
``POST https://app.jiuyangongshe.com/jystock-app/api/v2/article/community``
    社区文章流，body ``{category_id, type, order, start, limit, back_garden}``；
    ``order=0`` 最新发布、``type=0`` 全部、``start`` 从 0 起翻页。
    返回 ``{"errCode":"0","data":{"result":[{article_id,title,subtitle,create_time,...}]}}``。

``POST .../api/v2/article/detail`` body ``{article_id}``
    单篇正文，含 ``content``（HTML）与 ``stock_list:[{name, code:"sh603538"}]``。
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import date, datetime, timedelta

import requests
from loguru import logger

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_BASE = "https://app.jiuyangongshe.com/jystock-app"
_SECRET = "Uu0KfOB8iUP69d3c"
_TIMEOUT = 15
_TAG_RE = re.compile(r"<[^>]+>")


class JiuyanError(Exception):
    """抓取失败（接口异常 / 签名失效 / 网络问题）。"""


def _headers() -> dict:
    ts = str(int(time.time() * 1000))
    token = hashlib.md5(f"{_SECRET}:{ts}".encode()).hexdigest()
    return {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "platform": "3",
        "timestamp": ts,
        "token": token,
        "User-Agent": _UA,
        "Origin": "https://www.jiuyangongshe.com",
        "Referer": "https://www.jiuyangongshe.com/",
    }


def _post(path: str, body: dict, session: requests.Session | None = None) -> dict:
    sess = session or requests
    resp = sess.post(f"{_BASE}{path}", json=body, headers=_headers(), timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if str(data.get("errCode")) not in ("0", "None", ""):
        raise JiuyanError(f"{path} errCode={data.get('errCode')} msg={data.get('msg')}")
    return data.get("data") or {}


def _strip_html(html: str) -> str:
    return _TAG_RE.sub(" ", html or "").replace("&nbsp;", " ").strip()


def fetch_community(
    *, pages: int = 6, page_size: int = 20, order: int = 0,
    type_: int = 0, category_id: str = "", session: requests.Session | None = None,
    begin_date: str | None = None,
) -> list[dict]:
    """拉取社区文章流（最新发布优先）。

    ``begin_date`` 给定时，翻到比它更早的文章即停（流按发布时间倒序）。
    返回归一化列表：``[{article_id, title, subtitle, date, category_ids}]``。
    """
    out: list[dict] = []
    for i in range(max(1, pages)):
        body = {
            "category_id": category_id, "type": type_, "order": order,
            "start": i, "limit": page_size, "back_garden": False,
        }
        try:
            data = _post("/api/v2/article/community", body, session)
        except Exception as e:
            logger.debug(f"jiuyan community page {i} failed: {e}")
            break
        rows = data.get("result") or []
        if not rows:
            break
        stop = False
        for r in rows:
            d = (r.get("create_time") or "")[:10]
            if begin_date and d and d < begin_date:
                stop = True
                continue
            out.append({
                "article_id": r.get("article_id") or "",
                "title": (r.get("title") or "").strip(),
                "subtitle": (r.get("subtitle") or "").strip(),
                "date": d,
                "category_ids": r.get("categoryIdSet") or [],
            })
        if stop:
            break
    return out


def fetch_detail(article_id: str, session: requests.Session | None = None) -> dict:
    """单篇正文 + 关联个股。返回 ``{content_text, stocks:[{name, code}]}``。

    ``code`` 已剥离 ``sh/sz`` 前缀，统一成 6 位数字。
    """
    if not article_id:
        return {"content_text": "", "stocks": []}
    data = _post("/api/v2/article/detail", {"article_id": article_id}, session)
    stocks: list[dict] = []
    for s in (data.get("stock_list") or []):
        raw = str(s.get("code") or "")
        m = re.search(r"(\d{6})", raw)
        stocks.append({"name": (s.get("name") or "").strip(), "code": m.group(1) if m else ""})
    return {
        "content_text": _strip_html(data.get("content") or ""),
        "stocks": stocks,
        "title": (data.get("title") or "").strip(),
    }


def harvest_keyword_signals(
    keywords: list[str], *, lookback_days: int = 12, pages: int = 8,
    detail_cap: int = 30,
) -> list[dict]:
    """采集近期含**任一关键词**的韭研社区文章，补正文/个股后归一化输出。

    流程：翻 ``pages`` 页最新发布 → 标题/副标题命中关键词的入候选 → 取详情正文与
    关联个股（最多 ``detail_cap`` 篇，控延时）→ 复核正文也命中后输出。

    返回 ``[{title, snippet, date, keywords, stocks, article_id}]``，由上层归一化为线索。
    """
    kws = [str(k).strip() for k in (keywords or []) if str(k).strip()]
    if not kws:
        return []
    begin = (date.today() - timedelta(days=lookback_days)).isoformat()
    sess = requests.Session()

    try:
        articles = fetch_community(pages=pages, begin_date=begin, session=sess)
    except Exception as e:
        logger.debug(f"jiuyan harvest list failed: {e}")
        return []

    def _hit(text: str) -> list[str]:
        t = text or ""
        return [k for k in kws if k in t]

    out: list[dict] = []
    detail_used = 0
    for a in articles:
        head = f"{a['title']} {a['subtitle']}"
        head_kws = _hit(head)
        stocks: list[str] = []
        body = ""
        # 标题命中：取详情拿正文与关联个股；标题未命中也补少量详情兜底正文级线索。
        if head_kws and detail_used < detail_cap:
            try:
                det = fetch_detail(a["article_id"], session=sess)
                detail_used += 1
                body = det.get("content_text") or ""
                stocks = [
                    f"{s['name']}({s['code']})" if s.get("code") else s["name"]
                    for s in det.get("stocks") or [] if s.get("name")
                ]
            except Exception as e:
                logger.debug(f"jiuyan detail {a['article_id']} failed: {e}")
            time.sleep(0.15)
        hit_kws = _hit(f"{head} {body}")
        if not hit_kws:
            continue
        out.append({
            "title": a["title"] or a["subtitle"] or head[:40],
            "snippet": (body[:120] if body else a["subtitle"][:120]),
            "date": a["date"],
            "keywords": hit_kws,
            "stocks": stocks,
            "article_id": a["article_id"],
        })
    return out
