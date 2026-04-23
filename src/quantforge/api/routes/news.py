"""News and announcements API routes.

Data sources:
  - 东方财富快讯 (flash news, real-time)
  - 东方财富公告 (announcements)
  - 股票个股新闻
Cache: disk-based, tiered TTL (flash=3min, announcements=15min)
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import re
from pathlib import Path

import requests
from fastapi import APIRouter, Query
from loguru import logger

router = APIRouter(prefix="/news", tags=["news"])

# ── Source URLs ────────────────────────────────────────────────────────────────
_EM_ANN_URL   = "https://np-anotice-stock.eastmoney.com/api/security/ann"
_SINA_FLASH   = "https://feed.mix.sina.com.cn/api/roll/get"   # 新浪财经快讯
_THS_FLASH    = "https://news.10jqka.com.cn/tapp/news/push/stock/"  # 同花顺快讯

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

_CACHE_DIR = Path("data/cache/news")

# ── Sentiment keywords ─────────────────────────────────────────────────────────
_POSITIVE_KW = [
    "增长", "盈利", "利好", "业绩提升", "回购", "增持", "超预期", "创新高", "突破",
    "合作", "签约", "获批", "中标", "分红", "扩张", "上调", "涨停", "获奖", "新品",
    "战略", "超预期", "高增长", "新高", "翻倍", "扭亏", "减税", "降准", "降息",
    "加息利好", "政策支持", "财政刺激", "放开", "复苏", "爆款", "重磅", "利多",
]
_NEGATIVE_KW = [
    "亏损", "下滑", "风险", "处罚", "违规", "诉讼", "减持", "解禁", "问询", "警示",
    "下跌", "降级", "退市", "停牌", "调查", "起诉", "纠纷", "赔偿", "下调", "崩盘",
    "暴雷", "爆雷", "债务", "违约", "拖欠", "丑闻", "造假", "被查", "失联", "跑路",
    "大跌", "熔断", "利空", "衰退", "通胀", "加息", "制裁",
]

# Category keywords
_CATEGORY_MAP = {
    "宏观": ["央行", "美联储", "CPI", "PPI", "GDP", "汇率", "货币政策", "财政", "国债", "利率", "降准", "降息", "加息", "外汇"],
    "公司": ["公告", "年报", "季报", "增持", "减持", "回购", "分红", "定增", "募资", "并购", "重组"],
    "行业": ["板块", "概念", "赛道", "新能源", "半导体", "医药", "消费", "地产", "金融", "科技", "军工"],
    "监管": ["证监会", "交易所", "监管", "处罚", "立案", "问询", "退市", "ST", "违规"],
}


# ── Cache ──────────────────────────────────────────────────────────────────────

def _cache_path(key: str) -> Path:
    return _CACHE_DIR / f"{key}.json"


def _load_cache(key: str, ttl_minutes: int = 15) -> dict | None:
    f = _cache_path(key)
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        ts = _dt.datetime.fromisoformat(data.get("_cached_at", "2000-01-01"))
        if (_dt.datetime.now() - ts).total_seconds() > ttl_minutes * 60:
            return None
        return data
    except Exception:
        return None


def _save_cache(key: str, data: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data["_cached_at"] = _dt.datetime.now().isoformat()
        _cache_path(key).write_text(
            json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception as e:
        logger.debug(f"Cache save failed: {e}")


def _load_stale(key: str) -> dict | None:
    f = _cache_path(key)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _score_sentiment(text: str) -> str:
    t = text or ""
    pos = sum(1 for kw in _POSITIVE_KW if kw in t)
    neg = sum(1 for kw in _NEGATIVE_KW if kw in t)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def _detect_category(text: str) -> str:
    for cat, keywords in _CATEGORY_MAP.items():
        if any(kw in text for kw in keywords):
            return cat
    return "市场"


def _clean_content(html: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&[a-z]+;", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:800]  # cap at 800 chars for display


def _fmt_time(raw: str) -> tuple[str, str]:
    """Return (date_str, time_str) from various EM datetime formats."""
    if not raw:
        return "", ""
    raw = raw.strip()
    if len(raw) >= 16:
        return raw[:10], raw[11:16]
    if len(raw) >= 10:
        return raw[:10], ""
    return "", raw


# ── Flash news — 新浪 + 同花顺双源合并 ────────────────────────────────────────

def _ts_to_datetime(ts) -> tuple[str, str]:
    """Convert Unix timestamp (int or str) to (date, time) strings."""
    try:
        dt = _dt.datetime.fromtimestamp(int(ts))
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    except Exception:
        return "", ""


def _fetch_sina_flash(page_size: int = 30) -> list[dict]:
    """新浪财经快讯 — lid=2516 财经要闻。"""
    try:
        r = requests.get(
            _SINA_FLASH,
            params={"pageid": "153", "lid": "2516", "num": str(page_size), "page": "1"},
            headers=_HEADERS, timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("result", {}).get("data", []) or []
        result = []
        for it in items:
            title = it.get("title", "") or it.get("stitle", "")
            content = _clean_content(it.get("intro", "") or it.get("summary", ""))
            date_str, time_str = _ts_to_datetime(it.get("ctime") or it.get("intime", 0))
            url = it.get("url", "") or it.get("wapurl", "")
            source = it.get("media_name", "") or "新浪财经"
            result.append({
                "id": str(it.get("docid", "") or it.get("oid", "")),
                "title": title,
                "content": content,
                "date": date_str,
                "time": time_str,
                "source": source,
                "url": url,
                "type": "flash",
                "category": _detect_category(title + content),
                "sentiment": _score_sentiment(title + content),
                "stocks": [],
            })
        return result
    except Exception as e:
        logger.warning(f"Sina flash fetch failed: {e}")
        return []


def _fetch_ths_flash(page_size: int = 30) -> list[dict]:
    """同花顺快讯 — 含个股关联和情绪色值。"""
    try:
        r = requests.get(
            _THS_FLASH,
            params={"page": 1, "limit": page_size, "ver": "3",
                    "fields": "id,title,digest,url,ctime,source,stock,tags,color"},
            headers=_HEADERS, timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("data", {}).get("list", []) or []
        result = []
        for it in items:
            title = it.get("title", "")
            content = _clean_content(it.get("digest", ""))
            date_str, time_str = _ts_to_datetime(it.get("ctime", 0))
            # color: "1"=red(positive in A-share), "2"=green(negative), "0"=neutral
            color = str(it.get("color", "0"))
            sentiment = "positive" if color == "1" else "negative" if color == "2" else _score_sentiment(title + content)
            stocks_raw = it.get("stock", []) or []
            stocks = [{"code": s.get("code", ""), "name": s.get("name", "")} for s in stocks_raw]
            tags = [t.get("name", "") for t in (it.get("tags") or []) if t.get("name")]
            category = tags[0] if tags else _detect_category(title + content)
            result.append({
                "id": str(it.get("id", "") or it.get("seq", "")),
                "title": title,
                "content": content,
                "date": date_str,
                "time": time_str,
                "source": it.get("source", "") or "同花顺",
                "url": it.get("url", ""),
                "type": "flash",
                "category": category,
                "sentiment": sentiment,
                "stocks": stocks,
            })
        return result
    except Exception as e:
        logger.warning(f"THS flash fetch failed: {e}")
        return []


def _fetch_flash(page_size: int = 40) -> list[dict]:
    """合并新浪 + 同花顺快讯，去重后按时间降序。"""
    sina = _fetch_sina_flash(page_size)
    ths  = _fetch_ths_flash(page_size)
    seen = set()
    merged = []
    for item in ths + sina:   # THS has stocks info, put first
        key = item["title"][:30]
        if key not in seen and item["title"]:
            seen.add(key)
            merged.append(item)
    # Sort by date+time descending
    merged.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
    return merged[:page_size]


# ── Announcements (东方财富公告) ───────────────────────────────────────────────

def _fetch_announcements(stock_code: str = "", page_size: int = 30) -> list[dict]:
    params = {
        "sr": -1, "page": 1, "page_index": 1,
        "page_size": page_size, "ann_type": "A", "client_source": "web",
    }
    if stock_code:
        params["stock_list"] = stock_code
    try:
        r = requests.get(_EM_ANN_URL, params=params, headers=_HEADERS, timeout=12)
        r.raise_for_status()
        return r.json().get("data", {}).get("list", []) or []
    except Exception as e:
        logger.warning(f"Announcement fetch failed: {e}")
        return []


def _format_announcement(it: dict) -> dict:
    title = it.get("title_ch") or it.get("title", "")
    codes = it.get("codes", [])
    stock_name = codes[0].get("short_name", "") if codes else ""
    stock_code = codes[0].get("stock_code", "") if codes else ""
    art_code = it.get("art_code", "")
    date_str, time_str = _fmt_time(it.get("display_time", "") or it.get("notice_date", ""))
    ann_types = it.get("ann_types_display", [])
    category = ann_types[0] if ann_types else _detect_category(title)
    return {
        "id": art_code,
        "title": title or f"{stock_name} 公告",
        "content": "",
        "date": date_str,
        "time": time_str,
        "source": stock_name or "上市公司",
        "url": f"https://data.eastmoney.com/notices/detail/{art_code}.html" if art_code else "",
        "type": "announcement",
        "category": category or "公告",
        "sentiment": _score_sentiment(title),
        "stocks": [{"code": stock_code, "name": stock_name}] if stock_code else [],
    }


# ── Stock-specific news ────────────────────────────────────────────────────────

def _fetch_ths_stock_news(symbol: str, page_size: int = 20) -> list[dict]:
    """同花顺个股新闻。"""
    try:
        r = requests.get(
            "https://news.10jqka.com.cn/tapp/news/push/stock/",
            params={"page": 1, "limit": page_size, "ver": "3",
                    "stock": symbol,
                    "fields": "id,title,digest,url,ctime,source,stock,tags,color"},
            headers=_HEADERS, timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("data", {}).get("list", []) or []
        result = []
        for it in items:
            title = it.get("title", "")
            content = _clean_content(it.get("digest", ""))
            date_str, time_str = _ts_to_datetime(it.get("ctime", 0))
            color = str(it.get("color", "0"))
            sentiment = "positive" if color == "1" else "negative" if color == "2" else _score_sentiment(title + content)
            tags = [t.get("name", "") for t in (it.get("tags") or []) if t.get("name")]
            result.append({
                "id": str(it.get("id", "")),
                "title": title,
                "content": content,
                "date": date_str,
                "time": time_str,
                "source": it.get("source", "") or "同花顺",
                "url": it.get("url", ""),
                "type": "news",
                "category": tags[0] if tags else _detect_category(title + content),
                "sentiment": sentiment,
                "stocks": [{"code": symbol, "name": ""}],
            })
        return result
    except Exception as e:
        logger.warning(f"THS stock news fetch failed ({symbol}): {e}")
        return []


def _fetch_stock_news(symbol: str, page_size: int = 20) -> list[dict]:
    """THS个股新闻 + 东财公告合并。"""
    ths = _fetch_ths_stock_news(symbol, page_size)
    anns = _fetch_announcements(symbol, min(page_size, 20))
    ann_items = [_format_announcement(it) for it in anns]
    # Merge, deduplicate by title prefix
    seen = set()
    merged = []
    for item in ths + ann_items:
        key = item["title"][:30]
        if key not in seen and item["title"]:
            seen.add(key)
            merged.append(item)
    merged.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
    return merged[:page_size]


# ── Sentiment score builder ────────────────────────────────────────────────────

def _build_sentiment(items: list[dict]) -> dict:
    sentiments = [it["sentiment"] for it in items]
    pos = sentiments.count("positive")
    neg = sentiments.count("negative")
    neu = sentiments.count("neutral")
    total = max(len(sentiments), 1)
    score = round((pos - neg) / total * 100, 1)

    # Strength thresholds
    if score > 20:
        label, level = "强势偏多", "bullish"
    elif score > 5:
        label, level = "偏多", "mild_bullish"
    elif score < -20:
        label, level = "强势偏空", "bearish"
    elif score < -5:
        label, level = "偏空", "mild_bearish"
    else:
        label, level = "中性", "neutral"

    return {
        "positive": pos, "negative": neg, "neutral": neu,
        "total": total, "score": score, "label": label, "level": level,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/flash")
async def get_flash_news(count: int = Query(40, le=60)):
    """新浪+同花顺双源快讯，3分钟缓存。"""
    ck = f"flash_{count}"
    cached = _load_cache(ck, ttl_minutes=3)
    if cached:
        return cached

    items = await asyncio.to_thread(_fetch_flash, count)

    result = {
        "items": items,
        "total": len(items),
        "sentiment": _build_sentiment(items),
        "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }

    if items:
        _save_cache(ck, result)
    else:
        stale = _load_stale(ck)
        if stale:
            return stale

    return result


@router.get("/market")
async def get_market_news(count: int = Query(40, le=60)):
    """Market-wide announcements."""
    ck = f"market_{count}"
    cached = _load_cache(ck, ttl_minutes=15)
    if cached:
        return cached

    raw = await asyncio.to_thread(_fetch_announcements, "", count)
    items = [_format_announcement(it) for it in raw]

    result = {
        "items": items,
        "total": len(items),
        "sentiment": _build_sentiment(items),
        "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }

    if items:
        _save_cache(ck, result)
    else:
        stale = _load_stale(ck)
        if stale:
            return stale

    return result


@router.get("/sentiment")
async def get_market_sentiment():
    """Quick market sentiment gauge from latest announcements."""
    ck = "market_sentiment"
    cached = _load_cache(ck, ttl_minutes=10)
    if cached:
        return cached

    raw = await asyncio.to_thread(_fetch_announcements, "", 50)
    items = [_format_announcement(it) for it in raw]
    sent = _build_sentiment(items)

    result = {
        **sent,
        "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "recent_headlines": [it["title"] for it in items[:6] if it["title"]],
    }

    if items:
        _save_cache(ck, result)
    else:
        stale = _load_stale(ck)
        if stale:
            return stale

    return result


@router.get("/stock/{symbol}")
async def get_stock_news(symbol: str, count: int = Query(20, le=50)):
    """News and announcements for a specific stock."""
    ck = f"stock_{symbol}_{count}"
    cached = _load_cache(ck, ttl_minutes=10)
    if cached:
        return cached

    items = await asyncio.to_thread(_fetch_stock_news, symbol, count)
    result = {
        "symbol": symbol,
        "items": items,
        "total": len(items),
        "sentiment": _build_sentiment(items),
        "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }

    if items:
        _save_cache(ck, result)
    else:
        stale = _load_stale(ck)
        if stale:
            return stale

    return result


@router.post("/ai-summary")
async def ai_news_summary(symbol: str | None = None):
    """AI-powered market/stock summary from latest news."""
    from quantforge.api.ai_client import chat

    if symbol:
        items = await asyncio.to_thread(_fetch_stock_news, symbol, 20)
    else:
        flash_items = await asyncio.to_thread(_fetch_flash, 20)
        anns = await asyncio.to_thread(_fetch_announcements, "", 20)
        items = flash_items + [_format_announcement(it) for it in anns]

    if not items:
        return {"summary": "暂无可分析的新闻数据", "symbol": symbol,
                "generated_at": _dt.datetime.now().isoformat(timespec="seconds")}

    headlines = "\n".join(
        f"- [{it['date']} {it['time']}][{it['sentiment']}] {it['title']}"
        for it in items[:25] if it["title"]
    )
    subject = f"股票 {symbol}" if symbol else "A股市场"

    system = "你是一名专业A股市场分析师，擅长从公告和快讯中快速提炼核心信号。回答简洁专业。"
    user_msg = f"""以下是{subject}最新新闻标题（含情绪标注）：

{headlines}

请完成：
1. 【核心概况】2句话概括当前市场/公司核心动态
2. 【关键信号】列出1-2条最重要消息及潜在影响（一句话每条）
3. 【情绪判断】给出短期市场情绪（⬆️偏多 / ➡️中性 / ⬇️偏空）及1句理由

用中文回答，总字数控制在150字内，每段换行。"""

    try:
        summary = await chat(system, user_msg, max_tokens=512, caller="news_ai")
        return {
            "summary": summary,
            "symbol": symbol,
            "item_count": len(items),
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        }
    except Exception as e:
        return {
            "summary": f"AI分析暂时不可用：{e}",
            "symbol": symbol,
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        }
