"""News and announcements API routes.

Data sources (4个数据源):
  1. akshare·个股新闻 - 东财个股新闻 (stock_news_em)
  2. akshare·财联社快讯 - 电报 (stock_info_global_cls)
  3. akshare·东财全球资讯 - 全球财经新闻聚合 (stock_info_global_em)
  4. 东方财富公告 (announcements)
Cache: disk-based, tiered TTL (flash=3min, announcements=15min)
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import json
import re
from pathlib import Path

import requests
from fastapi import APIRouter, Query
from loguru import logger
from pydantic import BaseModel

router = APIRouter(prefix="/news", tags=["news"])

# ── Source URLs ────────────────────────────────────────────────────────────────
_EM_ANN_URL   = "https://np-anotice-stock.eastmoney.com/api/security/ann"
_THS_FLASH    = "https://news.10jqka.com.cn/tapp/news/push/stock/"  # 同花顺快讯(含财联社内容)
_SINA_FLASH   = "https://feed.mix.sina.com.cn/api/roll/get"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# ── Akshare数据源初始化 ─────────────────────────────────────────────────────────
_AKSHARE_AVAILABLE = False
try:
    import akshare as ak
    _AKSHARE_AVAILABLE = True
    logger.info("akshare数据源已加载")
except ImportError:
    logger.warning("akshare未安装，将使用备用数据源")

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


# ── Akshare数据源1: 个股新闻 (stock_news_em) ────────────────────────────────────

def _fetch_akshare_stock_news(symbol: str = "", page_size: int = 30) -> list[dict]:
    """akshare·个股新闻 - 东财个股新闻"""
    if not _AKSHARE_AVAILABLE:
        return []
    try:
        df = None
        if symbol:
            df = ak.stock_news_em(symbol=symbol)
        else:
            # 如果没有指定股票，获取市场新闻
            df = ak.stock_news_em(symbol="000001")  # 默认拿一个股票的
        if df is None or df.empty:
            return []
        
        result = []
        for _, row in df.head(page_size).iterrows():
            title = str(row.get("新闻标题", ""))
            content = _clean_content(str(row.get("新闻内容", "")))
            pub_time = str(row.get("发布时间", ""))
            date_str, time_str = _parse_time(pub_time)
            source = "akshare·个股新闻"
            
            result.append({
                "id": f"stock_news_{_}",
                "title": title,
                "content": content,
                "date": date_str,
                "time": time_str,
                "source": source,
                "url": str(row.get("文章链接", "")),
                "type": "news",
                "category": "个股",
                "sentiment": _score_sentiment(title + content),
                "stocks": [{"code": symbol, "name": ""}] if symbol else [],
            })
        return result
    except Exception as e:
        logger.warning(f"akshare个股新闻获取失败: {e}")
        return []

# ── Akshare数据源2: 财联社快讯 (stock_info_global_cls) ──────────────────────────

def _fetch_akshare_cls_telegraph(page_size: int = 40) -> list[dict]:
    """akshare·财联社快讯 - 电报"""
    if not _AKSHARE_AVAILABLE:
        return []
    try:
        df = ak.stock_info_global_cls()
        if df is None or df.empty:
            return []
        
        result = []
        for _, row in df.head(page_size).iterrows():
            title = str(row.get("标题", ""))
            content = _clean_content(str(row.get("内容", "")))
            pub_time = str(row.get("发布时间", ""))
            date_str, time_str = _parse_time(pub_time)
            
            result.append({
                "id": f"cls_telegraph_{_}",
                "title": title,
                "content": content,
                "date": date_str,
                "time": time_str,
                "source": "akshare·财联社快讯",
                "url": "",
                "type": "flash",
                "category": "快讯",
                "sentiment": _score_sentiment(title + content),
                "stocks": [],
            })
        return result
    except Exception as e:
        logger.warning(f"akshare财联社快讯获取失败: {e}")
        return []

# ── Akshare数据源3: 东财全球资讯 (stock_info_global_em) ─────────────────────────

def _fetch_akshare_global_news(page_size: int = 40) -> list[dict]:
    """akshare·东财全球资讯 - 全球财经新闻聚合"""
    if not _AKSHARE_AVAILABLE:
        return []
    try:
        df = ak.stock_info_global_em()
        if df is None or df.empty:
            return []
        
        result = []
        for _, row in df.head(page_size).iterrows():
            title = str(row.get("标题", ""))
            content = _clean_content(str(row.get("内容", "")))
            pub_time = str(row.get("发布时间", ""))
            date_str, time_str = _parse_time(pub_time)
            
            result.append({
                "id": f"global_news_{_}",
                "title": title,
                "content": content,
                "date": date_str,
                "time": time_str,
                "source": "akshare·东财全球资讯",
                "url": "",
                "type": "news",
                "category": "全球",
                "sentiment": _score_sentiment(title + content),
                "stocks": [],
            })
        return result
    except Exception as e:
        logger.warning(f"akshare东财全球资讯获取失败: {e}")
        return []

# ── 财联社电报专用 API (官方 v1/roll/get_roll_list) ────────────────────────────
#
# 区别于上面 akshare 的混合快讯：这是财联社电报官方接口，字段最全(等级/关联个股/
# 关注主题/阅读分享数)，且支持「全部 / 重点(red)」分类与按时间翻页。
_CLS_URL = "https://www.cls.cn/v1/roll/get_roll_list"
_CLS_BASE = {"app": "CailianpressWeb", "os": "web", "sv": "8.4.6"}
_CLS_HEADERS = {**_HEADERS, "Referer": "https://www.cls.cn/telegraph"}


def _cls_sign(params: dict) -> str:
    """财联社接口签名：参数按键排序拼接 → sha1 → md5。"""
    raw = "&".join(f"{k}={params[k]}" for k in sorted(params))
    sha1 = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return hashlib.md5(sha1.encode("utf-8")).hexdigest()


def _fetch_cls_telegraph(category: str = "", count: int = 40,
                         last_time: str | int = "") -> list[dict]:
    """财联社电报。category='' 全部 / 'red' 重点；last_time 用于翻页(上一页末条 ctime)。"""
    params = {
        **_CLS_BASE,
        "category": category or "",
        "last_time": str(last_time or ""),
        "rn": str(min(max(count, 1), 50)),
        "refresh_type": "1",
    }
    params["sign"] = _cls_sign(params)
    try:
        r = requests.get(_CLS_URL, params=params, headers=_CLS_HEADERS, timeout=12)
        r.raise_for_status()
        roll = (r.json().get("data") or {}).get("roll_data") or []
    except Exception as e:
        logger.warning(f"财联社电报获取失败: {e}")
        return []

    result = []
    for it in roll:
        if it.get("is_ad") or it.get("is_fad"):
            continue  # 跳过广告
        content = _clean_content(it.get("content") or it.get("brief") or "")
        title = (it.get("title") or "").strip() or content[:40]
        date_str, time_str = _ts_to_datetime(it.get("ctime", 0))
        level = str(it.get("level") or "C")
        is_red = level in ("A", "B")  # A/B 为财联社标红重点
        stocks = []
        for s in (it.get("stock_list") or []):
            sid = str(s.get("StockID") or "")
            code = re.sub(r"^(sh|sz|bj)", "", sid)
            if code:
                stocks.append({"code": code, "name": s.get("name", "")})
        subjects = [s.get("subject_name", "") for s in (it.get("subjects") or [])
                    if s.get("subject_name")]
        result.append({
            "id": f"cls_{it.get('id', '')}",
            "title": title,
            "content": content,
            "date": date_str,
            "time": time_str,
            "source": "财联社电报",
            "url": it.get("shareurl", "") or "",
            "type": "flash",
            "category": "重点" if is_red else (subjects[0] if subjects else "电报"),
            "sentiment": _score_sentiment(title + content),
            "stocks": stocks,
            "is_red": is_red,
            "level": level,
            "subjects": subjects,
            "reading_num": it.get("reading_num", 0),
            "share_num": it.get("share_num", 0),
            "comment_num": it.get("comment_num", 0),
            "ctime": it.get("ctime", 0),
        })
    return result


# ── 财联社电报搜索 (官方 /api/sw, POST) ────────────────────────────────────────
_CLS_SEARCH_URL = "https://www.cls.cn/api/sw"
_CLS_SEARCH_HEADERS = {**_HEADERS, "Referer": "https://www.cls.cn/searchPage",
                       "Content-Type": "application/json"}


def _split_cls_title(text: str) -> tuple[str, str]:
    """从电报正文拆出标题：优先取【】内的，否则取首句/前40字。"""
    m = re.match(r"\s*【(.+?)】\s*(.*)", text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return text[:40].strip(), text.strip()


def _search_cls_telegraph(keyword: str, page: int = 0, rn: int = 30) -> list[dict]:
    """按关键词搜索财联社电报全量历史。返回与 _fetch_cls_telegraph 同结构的条目。"""
    if not keyword.strip():
        return []
    params = {**_CLS_BASE}
    params["sign"] = _cls_sign(params)
    body = {"type": "telegram", "keyword": keyword.strip(),
            "page": int(page), "rn": min(max(int(rn), 1), 50), "os": "web",
            "app": "CailianpressWeb", "sv": "8.4.6"}
    try:
        r = requests.post(_CLS_SEARCH_URL, params=params, json=body,
                          headers=_CLS_SEARCH_HEADERS, timeout=12)
        r.raise_for_status()
        data = ((r.json().get("data") or {}).get("telegram") or {}).get("data") or []
    except Exception as e:
        logger.warning(f"财联社电报搜索失败: {e}")
        return []

    result = []
    for it in data:
        # descr 内含 <em> 高亮标签，清洗为纯文本
        content = _clean_content(it.get("descr") or "")
        if not content:
            continue
        title = (it.get("title") or "").strip()
        if not title:
            title, content = _split_cls_title(content)
        date_str, time_str = _ts_to_datetime(it.get("time", 0))
        stocks = []
        for s in (it.get("stocks") or []):
            sid = str(s.get("StockID") or s.get("stock_id") or "")
            code = re.sub(r"^(sh|sz|bj)", "", sid)
            name = s.get("name") or s.get("secu_name") or ""
            if code or name:
                stocks.append({"code": code, "name": name})
        subjects = [s.get("subject_name", "") for s in (it.get("subjects") or [])
                    if isinstance(s, dict) and s.get("subject_name")]
        result.append({
            "id": f"cls_{it.get('id', '')}",
            "title": title,
            "content": content,
            "date": date_str,
            "time": f"{date_str} {time_str}".strip() if date_str else time_str,
            "source": "财联社电报",
            "url": "",
            "type": "flash",
            "category": subjects[0] if subjects else "电报",
            "sentiment": _score_sentiment(title + content),
            "stocks": stocks,
            "is_red": False,
            "level": "C",
            "subjects": subjects,
            "ctime": it.get("time", 0),
        })
    return result


# ── 财联社电报 AI 汇总分析 ──────────────────────────────────────────────────────

async def _cls_summary_ai(items: list[dict]) -> str | None:
    """让 LLM 对最新一批财联社电报做一段汇总分析。best-effort，失败返回 None。"""
    from quantforge.api.ai_client import chat

    heads = "\n".join(
        f"- [{it['sentiment']}] {it['title']}"
        for it in items[:50] if it.get("title")
    )
    if not heads:
        return None
    system = "你是资深A股策略分析师，擅长从盘面快讯快速提炼盘面主线与可操作信息。"
    user_msg = (
        f"下面是最新一批财联社电报标题(已标注 positive利好 / negative利空 / neutral中性)：\n\n"
        f"{heads}\n\n"
        "请做一段简明的盘面汇总分析(180字内)，包含：\n"
        "1) 当前消息面整体情绪与短线方向；\n"
        "2) 2-3个最受关注的热点主题/板块；\n"
        "3) 1-2条最值得留意的重磅消息。\n"
        "用自然段落表述，分条用「①②③」前缀，不要使用 ** # 等 markdown 符号。"
    )
    text = await chat(system, user_msg, max_tokens=400,
                      caller="cls_summary_ai", timeout=30)
    return (text or "").replace("*", "").replace("#", "").strip() or None


# ── 辅助函数: 时间解析 ─────────────────────────────────────────────────────────

def _parse_time(time_str: str) -> tuple[str, str]:
    """解析各种时间格式，返回(date, time)"""
    if not time_str:
        return "", ""
    time_str = time_str.strip()
    
    # 尝试多种格式
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ]
    
    for fmt in formats:
        try:
            dt = _dt.datetime.strptime(time_str, fmt)
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
        except ValueError:
            continue
    
    # 如果都失败了，尝试简单分割
    parts = time_str.split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    return parts[0] if parts else "", ""

# ── Flash news — 同花顺(财联社来源优先) + akshare数据源 ────────────────────────

def _ts_to_datetime(ts) -> tuple[str, str]:
    """Convert Unix timestamp (int or str) to (date, time) strings."""
    try:
        dt = _dt.datetime.fromtimestamp(int(ts))
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    except Exception:
        return "", ""


def _fetch_ths_flash(page_size: int = 50) -> list[dict]:
    """同花顺快讯 — 含个股关联和情绪色值，包含财联社来源。"""
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
                "source": "财联社",
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
    """合并4个数据源的快讯: 财联社+akshare3个数据源"""
    # 获取各个数据源
    ths_items = _fetch_ths_flash(page_size // 2)
    cls_items = _fetch_akshare_cls_telegraph(page_size // 4)
    global_items = _fetch_akshare_global_news(page_size // 4)
    
    # 合并并去重
    all_items = ths_items + cls_items + global_items
    seen = set()
    unique_items = []
    for item in all_items:
        key = item["title"][:50] if item["title"] else str(item["id"])
        if key not in seen:
            seen.add(key)
            unique_items.append(item)
    
    # 按时间排序
    unique_items.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
    return unique_items[:page_size]


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
    """akshare个股新闻 + THS个股新闻 + 东财公告合并。"""
    # 优先使用akshare
    ak_items = _fetch_akshare_stock_news(symbol, page_size // 2)
    ths = _fetch_ths_stock_news(symbol, page_size // 2)
    anns = _fetch_announcements(symbol, min(page_size, 15))
    ann_items = [_format_announcement(it) for it in anns]
    
    # Merge, deduplicate by title prefix
    seen = set()
    merged = []
    for item in ak_items + ths + ann_items:
        key = item["title"][:30]
        if key not in seen and item["title"]:
            seen.add(key)
            merged.append(item)
    merged.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
    return merged[:page_size]


# ── Sentiment score builder ────────────────────────────────────────────────────

def _build_sentiment(items: list[dict], *, with_breakdown: bool = False) -> dict:
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

    out = {
        "positive": pos, "negative": neg, "neutral": neu,
        "total": total, "score": score, "label": label, "level": level,
    }

    if with_breakdown:
        # 分类情绪 + 热点主题：让情绪面不止一个分数，能看出多空集中在哪些板块/主题。
        from collections import Counter
        cat_total: Counter = Counter()
        cat_net: Counter = Counter()
        for it in items:
            cat = it.get("category") or "其他"
            cat_total[cat] += 1
            if it["sentiment"] == "positive":
                cat_net[cat] += 1
            elif it["sentiment"] == "negative":
                cat_net[cat] -= 1
        out["by_category"] = [
            {"name": c, "count": n, "net": cat_net[c]}
            for c, n in cat_total.most_common(6)
        ]
        # 热点主题：出现条数最多的几个分类标签，给前端做 chips。
        out["hot_themes"] = [c for c, _ in cat_total.most_common(8)]

    return out


# ── 多源情绪样本池 + AI 研判 ────────────────────────────────────────────────────

def _fetch_sentiment_pool(limit: int = 80) -> list[dict]:
    """聚合多源消息面用于情绪研判：财联社快讯(带多空色值) + 全球资讯 + 公告。

    比单看公告全面得多——公告标题多为中性，快讯才真正承载多空情绪；财联社快讯还自带
    同花顺人工情绪色值(color)，比纯关键词更准。
    """
    pool = _fetch_flash(50)                                    # THS财联社 + cls + global
    pool += [_format_announcement(it) for it in _fetch_announcements("", 30)]
    seen, out = set(), []
    for it in pool:
        key = (it.get("title") or "")[:40] or str(it.get("id", ""))
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out[:limit]


async def _ai_sentiment_view(items: list[dict], sent: dict) -> str | None:
    """让 LLM 对当前多源消息面做一句话情绪研判。best-effort，失败返回 None。"""
    from quantforge.api.ai_client import chat

    heads = "\n".join(
        f"- [{it['sentiment']}] {it['title']}"
        for it in items[:30] if it.get("title")
    )
    if not heads:
        return None
    system = "你是资深A股策略分析师，擅长从盘面消息快速研判市场情绪与短线方向。"
    user_msg = (
        f"下面是最新一批A股消息面标题(已标注 positive利好 / negative利空 / neutral中性)，"
        f"关键词量化情绪分={sent['score']}({sent['label']})：\n\n{heads}\n\n"
        "请用一句话(45字内)研判当前消息面情绪与短线方向，并点出1个最受关注的主题板块。"
        "直接给结论，不要客套、不要分点、不要使用 ** 等 markdown 符号。"
    )
    text = await chat(system, user_msg, max_tokens=160,
                      caller="news_sentiment_ai", timeout=20)
    # 兜底去掉 markdown 强调符，横幅是纯文本渲染。
    return (text or "").replace("*", "").replace("#", "").strip() or None


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


@router.get("/cls")
async def get_cls_telegraph(
    count: int = Query(40, le=50),
    category: str = Query("", description="'' 全部 / 'red' 重点"),
    last_time: str = Query("", description="翻页游标：上一页末条 ctime"),
):
    """财联社电报专用接口。支持「全部/重点」分类 + 按时间翻页；2分钟缓存(首页)。"""
    cat = "red" if category in ("red", "重点") else ""
    # 翻页请求不走缓存(游标不同结果不同)
    ck = f"cls_{cat}_{count}"
    if not last_time:
        cached = _load_cache(ck, ttl_minutes=2)
        if cached:
            return cached

    items = await asyncio.to_thread(_fetch_cls_telegraph, cat, count, last_time)

    result = {
        "items": items,
        "total": len(items),
        "sentiment": _build_sentiment(items),
        "next_cursor": items[-1]["ctime"] if items else "",
        "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }

    if items and not last_time:
        _save_cache(ck, result)
    elif not items and not last_time:
        stale = _load_stale(ck)
        if stale:
            return stale

    return result


@router.get("/cls/search")
async def search_cls_telegraph(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    page: int = Query(0, ge=0, description="页码，从0开始"),
    rn: int = Query(30, le=50, description="每页条数"),
):
    """财联社电报关键词搜索(全量历史)。结果按关键词缓存 5 分钟。"""
    kw = keyword.strip()
    ck = f"cls_search_{kw}_{page}_{rn}"
    cached = _load_cache(ck, ttl_minutes=5)
    if cached:
        return cached

    items = await asyncio.to_thread(_search_cls_telegraph, kw, page, rn)
    result = {
        "items": items,
        "total": len(items),
        "keyword": kw,
        "page": page,
        "has_more": len(items) >= rn,
        "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    if items:
        _save_cache(ck, result)
    return result


@router.get("/cls/summary")
async def summarize_cls_telegraph(count: int = Query(50, le=60)):
    """财联社电报 AI 汇总分析：拉最新电报 → 量化情绪 + 热点主题/高频个股 + AI 综述。

    整体缓存 10 分钟，AI 每 10 分钟最多调用一次；AI 失败时降级为纯量化汇总。
    """
    ck = f"cls_summary_{count}"
    cached = _load_cache(ck, ttl_minutes=10)
    if cached:
        return cached

    items = await asyncio.to_thread(_fetch_cls_telegraph, "", count, "")
    if not items:
        stale = _load_stale(ck)
        if stale:
            return stale
        return {"summary": None, "themes": [], "hot_stocks": [], "count": 0,
                "sentiment": _build_sentiment([]),
                "updated_at": _dt.datetime.now().isoformat(timespec="seconds")}

    # 热点主题(关注主题出现频次) + 高频个股
    from collections import Counter
    theme_ct: Counter = Counter()
    stock_ct: Counter = Counter()
    for it in items:
        for t in (it.get("subjects") or []):
            if t:
                theme_ct[t] += 1
        for s in (it.get("stocks") or []):
            nm = s.get("name") or s.get("code")
            if nm:
                stock_ct[nm] += 1
    themes = [{"name": n, "count": c} for n, c in theme_ct.most_common(8)]
    hot_stocks = [{"name": n, "count": c} for n, c in stock_ct.most_common(8) if c > 1]

    ai_summary = None
    try:
        ai_summary = await _cls_summary_ai(items)
    except Exception as e:
        logger.debug(f"cls summary AI failed: {e}")

    result = {
        "summary": ai_summary,
        "themes": themes,
        "hot_stocks": hot_stocks,
        "sentiment": _build_sentiment(items),
        "count": len(items),
        "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    _save_cache(ck, result)
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
    """市场情绪研判：多源消息面(快讯+全球+公告) + 分类拆解 + AI 一句话研判。

    结果整体缓存 10 分钟，因此 AI 每 10 分钟最多调用一次；AI 失败时降级为纯量化情绪。
    """
    ck = "market_sentiment"
    cached = _load_cache(ck, ttl_minutes=10)
    if cached:
        return cached

    items = await asyncio.to_thread(_fetch_sentiment_pool, 80)
    sent = _build_sentiment(items, with_breakdown=True)

    ai_view = None
    if items:
        try:
            ai_view = await _ai_sentiment_view(items, sent)
        except Exception as e:
            logger.debug(f"sentiment AI view failed: {e}")

    result = {
        **sent,
        "ai_view": ai_view,
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
async def get_stock_news(
    symbol: str,
    count: int = Query(20, le=50),
    ann_only: bool = Query(False, description="仅返回该股公告（不含新闻/快讯）"),
):
    """News and announcements for a specific stock.

    ``ann_only=true`` 时只取东方财富个股公告，过滤掉个股新闻/快讯——个股详情页
    「消息面」只想看该股自己的公告。
    """
    ck = f"stock_{symbol}_{count}{'_ann' if ann_only else ''}"
    cached = _load_cache(ck, ttl_minutes=10)
    if cached:
        return cached

    if ann_only:
        raw = await asyncio.to_thread(_fetch_announcements, symbol, count)
        items = [_format_announcement(it) for it in raw]
        items.sort(key=lambda x: (x.get("date", ""), x.get("time", "")), reverse=True)
        items = items[:count]
    else:
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


# ── 自选股异动·资讯流（聚合多只个股新闻/公告）────────────────────────────────────

class WatchlistNewsRequest(BaseModel):
    codes: list[str] = []
    per_code: int = 5       # 每只取几条
    limit: int = 80         # 总条数上限


def _norm_symbol(code: str) -> str:
    """去掉交易所前缀(SH/SZ/BJ)取 6 位代码，供新闻接口使用。"""
    c = (code or "").strip().upper()
    for p in ("SH", "SZ", "BJ"):
        if c.startswith(p):
            c = c[2:]
            break
    return c


async def _wl_one_stock_news(code: str, per_code: int) -> list[dict]:
    """单只个股资讯(每只 15min 缓存，重复聚合很便宜)。"""
    sym = _norm_symbol(code)
    if not sym:
        return []
    ck = f"wlnews_{sym}_{per_code}"
    cached = _load_cache(ck, ttl_minutes=15)
    if cached is not None:
        items = cached.get("items", [])
    else:
        items = await asyncio.to_thread(_fetch_stock_news, sym, per_code)
        if items:
            _save_cache(ck, {"items": items})
        else:
            stale = _load_stale(ck)
            items = (stale or {}).get("items", []) if stale else []
    # 统一标注原始自选 code，前端据此映射股票名/跳详情
    out = []
    for it in items[:per_code]:
        out.append({**it, "wl_code": code, "symbol": sym})
    return out


@router.post("/watchlist")
async def get_watchlist_news(req: WatchlistNewsRequest):
    """聚合自选股的个股新闻 + 公告，按时间倒序成一条资讯流(异动一眼看)。

    每只个股 15min 缓存、并发 6，整体再做标题去重。push2/THS 间歇失败的只
    静默跳过，不影响其余。"""
    codes = [c.strip().upper() for c in (req.codes or []) if c.strip()][:50]
    if not codes:
        return {"items": [], "total": 0, "updated_at": _dt.datetime.now().isoformat(timespec="seconds")}

    per_code = max(1, min(req.per_code, 10))
    sem = asyncio.Semaphore(6)

    async def _guard(c: str):
        async with sem:
            try:
                return await _wl_one_stock_news(c, per_code)
            except Exception as e:
                logger.debug(f"watchlist news {c} failed: {e}")
                return []

    batches = await asyncio.gather(*[_guard(c) for c in codes])

    seen = set()
    merged = []
    for items in batches:
        for it in items:
            key = (it.get("wl_code", ""), (it.get("title") or "")[:30])
            if not it.get("title") or key in seen:
                continue
            seen.add(key)
            merged.append(it)
    merged.sort(key=lambda x: (x.get("date", ""), x.get("time", "")), reverse=True)
    merged = merged[:max(10, min(req.limit, 150))]

    return {
        "items": merged,
        "total": len(merged),
        "codes": len(codes),
        "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
