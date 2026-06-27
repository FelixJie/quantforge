"""涨价逻辑板块 — 从新闻 / 研报 / 机构荐股 / 公众号文本里挖「产品提价」信号，
AI 综合归纳出**第二天可能因涨价逻辑发酵的来源主题与对应龙头股**。

与「大宗商品期货价格驱动」无关（那是旧实现，已废弃）：本模块**不看期货行情**，而是
从下列文本源里抓取企业「实际提价 / 调价 / 涨价函 / 供需紧张 / 减产挺价」等线索：

数据来源（**主源 = 机构荐股 + 韭研公社**，其余降权作补充）：
- 机构荐股 / 调研纪要 blog_posts —— 知识星球库内（**主源**）
- 韭研公社 jiuyangongshe 社区文章流 —— 外部实时、免登录签名（**主源**）
- 财经快讯（news._fetch_flash，财联社 + 全球资讯）—— 外部实时（补充·降权）
- 行业研报 industry_reports —— 库内（补充·降权）
- 个股研报 stock_reports —— 库内（自带 stockCode，补充·降权）
- 公众号 fenchuan 快照 —— app_config 缓存内（补充·降权）

流程：多源采集含「涨价关键词」的线索 → 去重/按时效与源权重排序 → 喂给 AI →
归纳「涨价来源主题 → 涨价原因/传导逻辑 → 受益龙头股」→ 补实时行情 → 当日缓存。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter(prefix="/price-surge", tags=["price-surge"])

logger = logging.getLogger("quantforge.api.price_surge")

_CACHE_DIR = Path("data/cache/price_surge")
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── 提价关键词 ────────────────────────────────────────────────────────────────
# 只聚焦「企业产品 / 服务的实际提价行为」，刻意**不含** “上涨/涨停/涨幅” 这类会被
# 个股股价噪声污染的词。命中其一即纳入候选线索，最终是否成立由 AI 研判。
_PRICE_KEYWORDS: tuple[str, ...] = (
    "涨价", "提价", "调价", "涨价函", "提价函", "提价潮", "涨价潮", "涨价预期",
    "价格上调", "价格上行", "价格回升", "价格反弹", "价格创新高", "价格新高",
    "报价上涨", "报价上调", "报价上行", "售价上调", "上调售价", "上调价格",
    "挺价", "提涨", "量价齐升", "涨价落地", "提价落地", "再涨价", "新一轮涨价",
    "供不应求", "供需紧张", "供需缺口", "缺货", "紧缺", "一货难求", "货紧",
    "减产", "限产", "停产检修", "产能出清", "挺价惜售", "惜售", "封盘",
)

# 大宗商品期货色彩过强、应弱化的词（仅用于排序降权，不硬过滤——维生素/制冷剂/化肥
# 等“类商品”提价仍是有效逻辑）。
_FUTURES_NOISE: tuple[str, ...] = ("期货", "主力合约", "夜盘", "持仓量", "基差")

# ── 事件类型 ─────────────────────────────────────────────────────────────────
# 涨价主题应「以事件为驱动」：要么有企业发布的涨价/调价公告（涨价函），要么是产品价格
# 当日确实上涨。下列按事件强度从强到弱归类，命中靠前者优先（一条线索取最强事件）。
_EVENT_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # 公告型：企业主动发函/宣布调价 —— 最硬的「事件」
    ("涨价函", (
        "涨价函", "提价函", "调价函", "调价通知", "涨价通知", "提价通知",
        "上调价格", "价格上调", "上调售价", "售价上调", "上调出厂价", "出厂价上调",
        "宣布涨价", "宣布提价", "发布涨价", "全线涨价", "全面提价", "上调报价",
    )),
    # 价格型：产品/现货价格当日确实上涨
    ("价格上涨", (
        "价格上涨", "报价上涨", "报价上行", "价格上行", "价格创新高", "价格新高",
        "价格回升", "价格反弹", "再涨价", "新一轮涨价", "涨价落地", "提价落地",
        "量价齐升", "提涨",
    )),
    # 供需型：减产/缺货/挺价等推动后续涨价的供需事件
    ("供需驱动", (
        "减产", "限产", "停产检修", "产能出清", "供需紧张", "供不应求", "供需缺口",
        "缺货", "紧缺", "一货难求", "货紧", "挺价", "惜售", "挺价惜售", "封盘",
    )),
)


def _event_type(text: str) -> str:
    """判定一条线索的驱动事件类型；都不命中归「提价预期」（预期/传闻阶段）。"""
    t = text or ""
    for label, kws in _EVENT_TYPES:
        if any(kw in t for kw in kws):
            return label
    return "提价预期"

# 采集回看天数（研报/博客/公众号按发布日；快讯为当日实时）
_LOOKBACK_DAYS = 12
# 每源最多采集条数（防 prompt 爆）
_PER_SOURCE_CAP = 60
# 交给 AI 的线索总上限
_MAX_SIGNALS = 110


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _safe_float(v) -> float | None:
    try:
        return float(v)
    except Exception:
        return None


def _json_path(name: str) -> Path:
    return _CACHE_DIR / f"{name}.json"


def _load_cache(name: str, ttl: int) -> dict | None:
    p = _json_path(name)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data.get("_cached_at", "2000-01-01T00:00:00"))
        if (datetime.now() - ts).total_seconds() > ttl:
            return None
        return data
    except Exception:
        return None


def _load_stale(name: str) -> dict | None:
    p = _json_path(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(name: str, data: dict) -> None:
    try:
        data["_cached_at"] = datetime.now().isoformat()
        _json_path(name).write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception as e:
        logger.debug("price_surge cache save failed: %s", e)


def _begin_date(days: int = _LOOKBACK_DAYS, as_of: date | None = None) -> str:
    base = as_of or date.today()
    return (base - timedelta(days=days)).isoformat()


def _in_window(d: str, begin: str, end: str) -> bool:
    """日期字符串(YYYY-MM-DD 前缀)落在 [begin, end] 闭区间内（空日期放行）。"""
    dd = (d or "")[:10]
    if not dd:
        return True
    return begin <= dd <= end


def _hit_keywords(text: str) -> list[str]:
    """返回 text 命中的提价关键词（去重，保序）。"""
    t = text or ""
    out: list[str] = []
    for kw in _PRICE_KEYWORDS:
        if kw in t and kw not in out:
            out.append(kw)
    return out


def _futures_weight(text: str) -> float:
    """大宗商品期货色彩越重权重越低（0.6~1.0）。"""
    t = text or ""
    n = sum(1 for kw in _FUTURES_NOISE if kw in t)
    return max(0.6, 1.0 - n * 0.2)


# ── 多源线索采集 ──────────────────────────────────────────────────────────────

def _harvest_news(as_of: date | None = None) -> list[dict]:
    """财经快讯（财联社 + 全球资讯），筛含提价关键词的条目。

    快讯只有「当下」实时流，无法回溯历史 —— 回填历史某日(as_of<今天)时直接跳过。
    """
    if as_of and as_of < date.today():
        return []
    out: list[dict] = []
    try:
        from quantforge.api.routes import news as _news
        items = _news._fetch_flash(60)
    except Exception as e:
        logger.debug("price_surge harvest news failed: %s", e)
        items = []
    today = date.today().isoformat()
    for it in items:
        title = (it.get("title") or "").strip()
        content = (it.get("content") or "").strip()
        blob = f"{title} {content}"
        kws = _hit_keywords(blob)
        if not kws:
            continue
        stocks = [s.get("name") or s.get("code") for s in (it.get("stocks") or []) if s.get("name") or s.get("code")]
        out.append({
            "source": "财经快讯",
            "source_kind": "news",
            "title": title or content[:40],
            "snippet": content[:120],
            "date": it.get("date") or today,
            "keywords": kws,
            "stocks": stocks,
            "url": it.get("url") or "",
        })
    return out[:_PER_SOURCE_CAP]


def _harvest_industry_reports(as_of: date | None = None) -> list[dict]:
    """行业研报：标题/行业名含提价关键词。"""
    from quantforge.data.storage import db_cache as _db
    begin = _begin_date(as_of=as_of)
    end = (as_of or date.today()).isoformat()
    out: list[dict] = []
    try:
        rows = _db.industry_reports_search(list(_PRICE_KEYWORDS), begin_date=begin, limit=200)
    except Exception as e:
        logger.debug("price_surge harvest industry reports failed: %s", e)
        rows = []
    for r in rows:
        if not _in_window(r.get("publish_date") or "", begin, end):
            continue
        title = (r.get("title") or "").strip()
        ind = (r.get("industry_name") or "").strip()
        org = (r.get("org") or "").strip()
        kws = _hit_keywords(f"{title} {ind}")
        if not kws:
            continue
        out.append({
            "source": "行业研报",
            "source_kind": "industry_report",
            "title": title,
            "snippet": f"{ind}" + (f"·{org}" if org else ""),
            "date": (r.get("publish_date") or "")[:10],
            "keywords": kws,
            "stocks": [],
            "url": "",
        })
    return out[:_PER_SOURCE_CAP]


def _harvest_stock_reports(as_of: date | None = None) -> list[dict]:
    """个股研报：标题含提价关键词；自带 stockCode 可直接定位个股。"""
    import sqlite3
    from quantforge.data.storage import db_cache as _db
    from quantforge.data.storage import stock_meta_cache
    end = (as_of or date.today()).isoformat()
    out: list[dict] = []
    try:
        conn: sqlite3.Connection = _db._conn()
        like_clause = " OR ".join(["title LIKE ?"] * len(_PRICE_KEYWORDS))
        params: list = [f"%{kw}%" for kw in _PRICE_KEYWORDS]
        params.append(_begin_date(as_of=as_of))
        params.append(end)
        rows = conn.execute(
            f"SELECT code, title, org, publish_date FROM stock_reports "
            f"WHERE ({like_clause}) AND publish_date >= ? AND publish_date <= ? "
            f"ORDER BY publish_date DESC LIMIT 200",
            params,
        ).fetchall()
    except Exception as e:
        logger.debug("price_surge harvest stock reports failed: %s", e)
        rows = []
    names = {}
    try:
        names = stock_meta_cache.get_all_names()
    except Exception:
        pass
    for r in rows:
        title = (r["title"] or "").strip()
        kws = _hit_keywords(title)
        if not kws:
            continue
        code = (r["code"] or "").strip()
        nm = names.get(code) or names.get(code.zfill(6)) or ""
        out.append({
            "source": "个股研报",
            "source_kind": "stock_report",
            "title": title,
            "snippet": (r["org"] or "").strip(),
            "date": (r["publish_date"] or "")[:10],
            "keywords": kws,
            "stocks": [f"{nm}({code})"] if nm else ([code] if code else []),
            "url": "",
        })
    return out[:_PER_SOURCE_CAP]


def _harvest_blog(as_of: date | None = None) -> list[dict]:
    """机构荐股 / 调研纪要（知识星球）：标题/正文含提价关键词。"""
    from quantforge.data.storage import db_cache as _db
    begin = _begin_date(as_of=as_of)
    end = (as_of or date.today()).isoformat()
    out: list[dict] = []
    try:
        rows = _db.blog_posts_search(list(_PRICE_KEYWORDS), begin_date=begin, limit=200)
    except Exception as e:
        logger.debug("price_surge harvest blog failed: %s", e)
        rows = []
    for r in rows:
        if not _in_window(r.get("created_at") or "", begin, end):
            continue
        title = (r.get("ai_title") or r.get("title") or "").strip()
        body = (r.get("content_text") or "").strip()
        kws = _hit_keywords(f"{title} {body}")
        if not kws:
            continue
        out.append({
            "source": "机构荐股",
            "source_kind": "blog",
            "title": title or body[:40],
            "snippet": body[:120],
            "date": (r.get("created_at") or "")[:10],
            "keywords": kws,
            "stocks": [],
            "url": "",
        })
    return out[:_PER_SOURCE_CAP]


def _harvest_jiuyan(as_of: date | None = None) -> list[dict]:
    """韭研公社社区文章流：标题/副标题/正文含提价关键词（免登录签名抓取）。

    回填历史某日时：社区流仍按最新发布抓取，但翻页回看天数放大到能覆盖到
    (as_of - LOOKBACK)，再按 [begin, as_of] 切片，剔除晚于 as_of 的文章。
    """
    begin = _begin_date(as_of=as_of)
    end = (as_of or date.today()).isoformat()
    # 让韭研翻够页覆盖到 begin（从今天往回算）
    lookback = max(_LOOKBACK_DAYS, (date.today() - (as_of - timedelta(days=_LOOKBACK_DAYS))).days) if as_of else _LOOKBACK_DAYS
    out: list[dict] = []
    try:
        from quantforge.data.feed import jiuyan
        rows = jiuyan.harvest_keyword_signals(
            list(_PRICE_KEYWORDS), lookback_days=lookback,
            pages=12 if (as_of and as_of < date.today()) else 8,
        )
    except Exception as e:
        logger.debug("price_surge harvest jiuyan failed: %s", e)
        rows = []
    for r in rows:
        if not _in_window(r.get("date") or "", begin, end):
            continue
        out.append({
            "source": "韭研公社",
            "source_kind": "jiuyan",
            "title": r.get("title") or "",
            "snippet": r.get("snippet") or "",
            "date": r.get("date") or "",
            "keywords": r.get("keywords") or [],
            "stocks": r.get("stocks") or [],
            "url": f"https://www.jiuyangongshe.com/a/{r.get('article_id')}" if r.get("article_id") else "",
        })
    return out[:_PER_SOURCE_CAP]


def _harvest_fenchuan(as_of: date | None = None) -> list[dict]:
    """公众号（纷传快照）：标题/正文含提价关键词。"""
    out: list[dict] = []
    try:
        from quantforge.api.routes import fenchuan as _fc
        snap = _fc._load_cache()
        posts = snap.get("posts") or []
    except Exception as e:
        logger.debug("price_surge harvest fenchuan failed: %s", e)
        posts = []
    begin = _begin_date(as_of=as_of)
    end = (as_of or date.today()).isoformat()
    for p in posts:
        title = (p.get("title") or "").strip()
        text = (p.get("text") or "").strip()
        kws = _hit_keywords(f"{title} {text}")
        if not kws:
            continue
        ptime = (p.get("time") or "")[:10]
        if ptime and not (begin <= ptime <= end):
            continue
        out.append({
            "source": "公众号",
            "source_kind": "fenchuan",
            "title": title or text[:40],
            "snippet": text[:120],
            "date": ptime,
            "keywords": kws,
            "stocks": [],
            "url": p.get("url") or "",
        })
    return out[:_PER_SOURCE_CAP]


def _harvest_signals(as_of: date | None = None) -> dict:
    """汇总全部源的提价线索，去重 + 按时效/源权重排序。返回 {signals, by_source, ...}。

    ``as_of`` 给定且早于今天时为「历史回填」：库内研报/机构荐股/韭研按
    [as_of-12d, as_of] 切片回溯，快讯不可回溯被跳过（结果标 partial）。
    """
    raw: list[dict] = []
    raw += _harvest_blog(as_of)       # 主源：机构荐股 / 调研纪要
    raw += _harvest_jiuyan(as_of)     # 主源：韭研公社
    raw += _harvest_news(as_of)
    raw += _harvest_industry_reports(as_of)
    raw += _harvest_stock_reports(as_of)
    raw += _harvest_fenchuan(as_of)

    # 去重：按标题前 24 字；顺带打上「驱动事件类型」标签（事件驱动展示用）
    seen: set[str] = set()
    uniq: list[dict] = []
    for s in raw:
        key = (s.get("title") or "")[:24]
        if not key or key in seen:
            continue
        seen.add(key)
        s["event_type"] = _event_type(f"{s.get('title','')} {s.get('snippet','')}")
        uniq.append(s)

    today = as_of or date.today()
    is_partial = bool(as_of and as_of < date.today())

    def _rank(s: dict) -> float:
        # 时效：越近权重越高
        try:
            d = datetime.strptime(s.get("date") or today.isoformat(), "%Y-%m-%d").date()
            age = (today - d).days
        except Exception:
            age = 3
        recency = max(0.3, 1.0 - age * 0.07)
        # 源权重：**主源 机构荐股 / 韭研公社 最高**，研报/公众号/快讯降权作补充。
        src_w = {
            "blog": 1.0, "jiuyan": 1.0,
            "industry_report": 0.7, "stock_report": 0.7,
            "fenchuan": 0.6, "news": 0.55,
        }.get(s.get("source_kind"), 0.6)
        kw_w = min(1.3, 1.0 + 0.1 * len(s.get("keywords") or []))
        return recency * src_w * kw_w * _futures_weight(s.get("title", "") + s.get("snippet", ""))

    uniq.sort(key=_rank, reverse=True)
    signals = uniq[:_MAX_SIGNALS]

    by_source: dict[str, int] = {}
    for s in signals:
        by_source[s["source"]] = by_source.get(s["source"], 0) + 1

    return {
        "signals": signals,
        "by_source": by_source,
        "total": len(signals),
        "as_of": today.isoformat(),
        "partial": is_partial,
        "updated_at": datetime.now().isoformat(),
    }


# ── 个股行情补全 ──────────────────────────────────────────────────────────────

def _name_to_code() -> dict[str, str]:
    try:
        from quantforge.data.storage import stock_meta_cache
        return {v: k for k, v in stock_meta_cache.get_all_names().items() if v}
    except Exception:
        return {}


def _enrich_stocks(names: list[str], rev: dict[str, str] | None = None) -> list[dict]:
    """股票简称 → 代码 + 实时行情（市值/现价/涨跌幅）。"""
    import sqlite3
    rev = rev if rev is not None else _name_to_code()
    out: list[dict] = []
    conn = None
    try:
        from quantforge.data.storage import db_cache as _db
        conn = _db._conn()
    except Exception:
        conn = None
    seen: set[str] = set()
    for raw in names:
        nm = (raw or "").strip()
        # 容忍 "简称(代码)" 形态
        m = re.match(r"^(.*?)[（(](\d{6})[)）]$", nm)
        code = ""
        if m:
            nm, code = m.group(1).strip(), m.group(2)
        if not code:
            code = rev.get(nm, "")
        key = code or nm
        if not key or key in seen:
            continue
        seen.add(key)
        info: dict = {"name": nm, "code": code}
        if code and conn is not None:
            try:
                row = conn.execute(
                    "SELECT price, change_pct, market_cap FROM stock_quote WHERE code=? LIMIT 1",
                    (code,),
                ).fetchone()
                if row:
                    info["price"] = row["price"]
                    info["change_pct"] = row["change_pct"]
                    info["market_cap"] = row["market_cap"]
            except Exception:
                pass
        out.append(info)
    return out


# ── AI 分析 ───────────────────────────────────────────────────────────────────

_analysis_warming = False


def _analysis_ck() -> str:
    return f"price_surge:analysis:{date.today().isoformat()}"


def _build_material(signals: list[dict]) -> str:
    """把线索按源分组，拼成喂给 AI 的材料。"""
    groups: dict[str, list[dict]] = {}
    for s in signals:
        groups.setdefault(s["source"], []).append(s)
    parts: list[str] = []
    for src, items in groups.items():
        lines = []
        for s in items[:40]:
            tag = "/".join(s.get("keywords") or [])
            et = s.get("event_type") or ""
            stk = ("｜相关：" + "、".join(s["stocks"])) if s.get("stocks") else ""
            d = s.get("date") or ""
            lines.append(f"· [{d}][{et}·{tag}] {s['title']}{stk}")
        parts.append(f"【{src}】\n" + "\n".join(lines))
    return "\n\n".join(parts)[:12000]


async def _run_ai_analysis(harvest: dict) -> dict:
    """综合提价线索 → AI 归纳明日涨价来源主题 + 龙头股。"""
    from quantforge.api.ai_client import chat
    from quantforge.api.research_helpers import _loads_lenient

    signals = harvest.get("signals") or []
    if not signals:
        return {
            "themes": [],
            "summary": "近期暂未从机构荐股/韭研公社等源中捕捉到明显的产品提价线索。",
            "signal_count": 0,
            "as_of": harvest.get("as_of"),
            "partial": harvest.get("partial", False),
            "generated_at": datetime.now().isoformat(),
        }

    material = _build_material(signals)

    system = (
        "你是A股「涨价逻辑」主题分析师。你的任务是：从下列线索中（**以机构荐股、韭研公社"
        "两类为主，新闻/研报/公众号为辅**），识别真正在发生或即将发生的**企业产品/服务提价**，"
        "归纳出第二天可能因『涨价逻辑』被资金关注的来源主题，并给出受益龙头股。"
        "**涨价主题必须以『事件』为驱动**——要么有企业发布的涨价/调价公告（涨价函），"
        "要么产品价格当日确实上涨；只有模糊预期、没有具体涨价事件的不要立为主题。"
        "每条线索前的 [日期][事件类型·关键词] 标注了它的驱动事件类型"
        "（涨价函/价格上涨/供需驱动/提价预期），请优先采纳有『涨价函』『价格上涨』硬事件的线索。"
        "**不要**把单纯的大宗商品期货价格涨跌当作主题——聚焦能传导到上市公司业绩/股价的提价事件。"
    )
    user = (
        "以下是近期多源采集到的『提价相关』线索：\n\n" + material +
        "\n\n请综合判断，输出一个 JSON 对象，格式如下：\n"
        '{"summary":"一句话整体判断（哪些涨价主题最值得关注，2-3句）",'
        '"themes":[{'
        '"theme":"涨价主题/品种（如 制冷剂、维生素、面板、海运、化妆品提价 等）",'
        '"category":"所属行业（如 化工/医药/消费/航运 等）",'
        '"trigger":{"date":"驱动事件日期 YYYY-MM-DD（取最关键那条线索的日期）",'
        '"type":"涨价函|价格上涨|供需驱动","event":"一句话描述驱动事件'
        '（谁发了涨价函/什么产品价格涨了多少/谁减产挺价，尽量含主体与幅度）"},'
        '"logic":"涨价原因与传导逻辑（供需/成本/政策/产能出清/旺季，含量化信息更好）",'
        '"evidence":["支撑该判断的线索标题1","线索标题2"],'
        '"stocks":["受益龙头股简称1","简称2","简称3"],'
        '"catalyst":"次日/短期催化（提价落地、旺季、检修停产等）",'
        '"confidence":"高|中|低"}]}\n'
        "要求：\n"
        "1. themes 按确定性与弹性排序，最多 8 个；线索零散、无明确涨价事件的不要硬凑；\n"
        "2. 每个 theme 必须给出 trigger（一个具体的涨价驱动事件，带日期与类型）"
        "且必须有 evidence（直接引用上文线索标题），无事件无证据的不要列；\n"
        "3. stocks 只填 A 股**股票简称**（不填代码），优先该涨价链条里业绩弹性最大的龙头，最多 5 只；\n"
        "4. confidence：高=多源印证且提价已落地；中=研报/单源提及、趋势确立；低=预期/传闻阶段；\n"
        "5. 只输出 JSON 对象本身，不要任何额外文字或代码块标记。"
    )

    text = await chat(system, user, max_tokens=3000, caller="price_surge_analysis", timeout=240)
    data = _loads_lenient(text)
    if not isinstance(data, dict):
        data = {}

    themes = data.get("themes") or []
    rev = _name_to_code()
    for th in themes:
        if not isinstance(th, dict):
            continue
        names = [str(x) for x in (th.get("stocks") or []) if x]
        th["stocks"] = _enrich_stocks(names, rev)
        ev = th.get("evidence")
        if isinstance(ev, str):
            th["evidence"] = [ev]
        elif not isinstance(ev, list):
            th["evidence"] = []
        # trigger 类型硬化：统一成 {date,type,event} 字典，缺字段补空
        tg = th.get("trigger")
        if isinstance(tg, str):
            tg = {"event": tg, "type": "", "date": ""}
        elif not isinstance(tg, dict):
            tg = {"event": "", "type": "", "date": ""}
        th["trigger"] = {
            "date": str(tg.get("date") or "")[:10],
            "type": str(tg.get("type") or ""),
            "event": str(tg.get("event") or ""),
        }

    data["themes"] = [t for t in themes if isinstance(t, dict)]
    data["signal_count"] = len(signals)
    data["by_source"] = harvest.get("by_source", {})
    data["as_of"] = harvest.get("as_of")
    data["partial"] = harvest.get("partial", False)
    data["generated_at"] = datetime.now().isoformat()
    return data


async def _ensure_analysis(harvest: dict) -> dict:
    """当日缓存 AI 分析；命中直接返回，缺失则后台生成并返回 pending（带 stale 兜底）。"""
    global _analysis_warming
    from quantforge.data.storage import db_cache

    ck = _analysis_ck()
    cached = db_cache.get(ck, ttl_seconds=366 * 86400)
    if cached:
        return cached

    stale = db_cache.get_stale(ck)
    if not _analysis_warming:
        _analysis_warming = True

        async def _warm():
            global _analysis_warming
            try:
                result = await _run_ai_analysis(harvest)
                db_cache.set(ck, result, ttl_seconds=366 * 86400, category="price_surge")
            except Exception as e:
                logger.warning("price_surge AI analysis failed: %s", e)
            finally:
                _analysis_warming = False

        asyncio.create_task(_warm())

    if stale:
        stale = {**stale, "_pending": True}
        return stale
    return {"_pending": True, "themes": [], "summary": "AI 分析生成中，请稍候刷新…"}


# ── HTTP 端点 ─────────────────────────────────────────────────────────────────

@router.get("/signals")
async def get_signals(force: bool = Query(False)):
    """多源提价线索（主源 机构荐股 + 韭研公社，辅以新闻/研报/公众号），15 分钟缓存。"""
    cache_name = f"signals_{date.today().isoformat()}"
    if not force:
        cached = _load_cache(cache_name, ttl=15 * 60)
        if cached:
            return cached
    result = await asyncio.to_thread(_harvest_signals)
    if result.get("signals"):
        _save_cache(cache_name, result)
    else:
        stale = _load_stale(cache_name)
        if stale:
            return stale
    return result


@router.get("/analysis")
async def get_analysis(force: bool = Query(False)):
    """AI 综合分析：明日涨价来源主题 + 龙头股（当日缓存，冷缓存返回 pending）。"""
    from quantforge.data.storage import db_cache

    if force:
        db_cache.delete(_analysis_ck())

    cache_name = f"signals_{date.today().isoformat()}"
    harvest = _load_stale(cache_name)
    if not harvest or not harvest.get("signals"):
        harvest = await asyncio.to_thread(_harvest_signals)
        if harvest.get("signals"):
            _save_cache(cache_name, harvest)
    return await _ensure_analysis(harvest)


# ── 历史存档 / 时间脉络 ────────────────────────────────────────────────────────
# 每日 AI 分析以 `price_surge:analysis:{日期}` 为键存入 db_cache（category=price_surge，
# 保留 366 天），天然按天累积。下列端点据此提供「查看历史某日」与「同一涨价主题跨天
# 串成脉络（看确定性演进）」两种回看视角。

_ANALYSIS_PREFIX = "price_surge:analysis:"

# 主题归一：把「制冷剂涨价 / 制冷剂提价 / 制冷剂」收敛到同一脉络。
_THEME_STRIP = (
    "涨价潮", "提价潮", "涨价预期", "涨价落地", "提价落地", "新一轮涨价", "再涨价",
    "涨价", "提价", "调价", "价格上涨", "价格上行", "价格回升", "价格反弹",
    "量价齐升", "供需紧张", "供不应求", "缺货", "紧缺", "减产", "限产",
)


def _normalize_theme(name: str) -> str:
    s = (name or "").strip()
    raw = s
    for suf in _THEME_STRIP:
        s = s.replace(suf, "")
    s = s.strip(" 　·、，,（）()【】[]")
    return s or raw


# 品种归类词典：AI 每天给同一涨价品种起的名字会变（「CCL/PCB覆铜板涨价」vs
# 「PCB/CCL/AI载板材料涨价」），仅靠去后缀无法合并。这里按品种特异性从强到弱列出
# 判定 token（小写匹配），命中第一个即归该组，键=对外展示的规范名。
_CANON_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("覆铜板/CCL",        ("ccl", "覆铜板")),
    ("MLCC",              ("mlcc",)),
    ("ABF/BT载板",        ("abf", "bt载板", "ic载板", "载板")),
    ("PCB",               ("pcb",)),
    ("光模块/光互联",     ("光模块", "光互联", "光器件", "cpo", "光芯片")),
    ("晶圆代工/先进制程", ("晶圆", "代工", "先进制程", "wafer", "foundry")),
    ("存储芯片",          ("存储", "dram", "nand", "颗粒", "内存", "闪存", "hbm")),
    ("多晶硅/硅料",       ("多晶硅", "硅料")),
    ("六氟磷酸锂/电解液", ("六氟磷酸锂", "电解液", "lifsi", "添加剂", "vc")),
    ("磷化铟",            ("磷化铟",)),
    ("氮化铝陶瓷",        ("氮化铝", "陶瓷基板", "陶瓷")),
    ("钨",                ("钨",)),
    ("稀土",              ("稀土",)),
    ("面板",              ("面板", "液晶", "lcd", "oled")),
    ("制冷剂",            ("制冷剂", "r32", "r134", "氟化工")),
    ("维生素",            ("维生素", "va", "ve")),
    ("钛白粉",            ("钛白粉",)),
    ("纯碱",              ("纯碱",)),
    ("化纤/涤纶氨纶",     ("涤纶", "氨纶", "粘胶", "化纤")),
    ("海运/航运",         ("海运", "航运", "运价", "集运", "scfi")),
    ("水泥",              ("水泥",)),
    ("化妆品",            ("化妆品",)),
)


def _theme_group(name: str) -> tuple[str, str]:
    """返回 (脉络分组键, 展示名)。命中品种词典→规范名；否则回退去后缀归一。"""
    t = (name or "").lower()
    for label, toks in _CANON_TOKENS:
        if any(tok in t for tok in toks):
            return label, label
    norm = _normalize_theme(name)
    return norm, (name or "").strip()


def _list_archive() -> list[dict]:
    """枚举已存档的每日分析键，按日期倒序返回 [{date, fetched_at}]。"""
    from quantforge.data.storage import db_cache
    out: list[dict] = []
    for it in db_cache.list_by_category("price_surge"):
        key = it.get("key") or ""
        if not key.startswith(_ANALYSIS_PREFIX):
            continue
        d = key[len(_ANALYSIS_PREFIX):]
        if len(d) == 10 and d[4] == "-":  # 仅 YYYY-MM-DD
            out.append({"date": d, "fetched_at": it.get("fetched_at")})
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


@router.get("/dates")
async def list_dates(limit: int = Query(90)):
    """历史存档日期列表（每条带当日主题数 / 概要 / 主题名），供「历史存档」回看。"""
    from quantforge.data.storage import db_cache
    out: list[dict] = []
    for a in _list_archive()[:limit]:
        data = db_cache.get_stale(f"{_ANALYSIS_PREFIX}{a['date']}") or {}
        themes = [t for t in (data.get("themes") or []) if isinstance(t, dict)]
        out.append({
            "date": a["date"],
            "theme_count": len(themes),
            "summary": data.get("summary", ""),
            "themes": [t.get("theme") for t in themes if t.get("theme")][:10],
            "generated_at": data.get("generated_at"),
        })
    return {"dates": out, "total": len(out)}


@router.get("/history")
async def get_history(d: str = Query(..., description="YYYY-MM-DD")):
    """查看历史某一天存档的完整 AI 分析。"""
    from quantforge.data.storage import db_cache
    data = db_cache.get_stale(f"{_ANALYSIS_PREFIX}{d}")
    if not data:
        return {"date": d, "themes": [], "summary": "该日期暂无存档", "_empty": True}
    return {**data, "date": d}


@router.get("/timeline")
async def get_timeline(days: int = Query(45, ge=1, le=366)):
    """时间脉络：把近 N 天存档里同一涨价主题跨天串起来，呈现确定性 / 龙头股的演进。"""
    from quantforge.data.storage import db_cache
    threads: dict[str, dict] = {}
    for a in _list_archive()[:days]:
        date_str = a["date"]
        data = db_cache.get_stale(f"{_ANALYSIS_PREFIX}{date_str}") or {}
        for th in (data.get("themes") or []):
            if not isinstance(th, dict):
                continue
            name = (th.get("theme") or "").strip()
            if not name:
                continue
            key, display = _theme_group(name)
            t = threads.setdefault(key, {
                "theme": display, "category": th.get("category") or "",
                "points": [], "aliases": set(),
            })
            # 收集该品种各日的原始命名（差异化的叫法），便于前端展示「曾用名」
            if name and name != t["theme"]:
                t["aliases"].add(name)
            # 保留最近一次出现时的行业（循环按日期倒序进入，首个即最新）
            if not t.get("category") and th.get("category"):
                t["category"] = th.get("category")
            stocks = [
                s.get("name") for s in (th.get("stocks") or [])
                if isinstance(s, dict) and s.get("name")
            ]
            t["points"].append({
                "date": date_str,
                "confidence": th.get("confidence") or "",
                "catalyst": th.get("catalyst") or "",
                "logic": th.get("logic") or "",
                "stocks": stocks[:6],
            })

    out: list[dict] = []
    for t in threads.values():
        pts = sorted(t["points"], key=lambda p: p["date"])
        last = pts[-1]
        out.append({
            "theme": t["theme"],
            "category": t["category"],
            "aliases": sorted(t.get("aliases") or []),
            "first_seen": pts[0]["date"],
            "last_seen": last["date"],
            "days_count": len(pts),
            "latest_confidence": last["confidence"],
            "latest_catalyst": last["catalyst"],
            "latest_logic": last["logic"],
            "latest_stocks": last["stocks"],
            "points": pts,
        })
    # 排序：持续天数多者优先（脉络更确凿），再按最近出现日。
    out.sort(key=lambda x: (x["days_count"], x["last_seen"]), reverse=True)
    return {"threads": out, "total": len(out), "span_days": days}


# ── 单主题·一年涨价时间线 ──────────────────────────────────────────────────────
# 需求：每个涨价主题应有「至少一年内」的涨价时间线。库内研报(行业/个股)+机构荐股
# 留存约一年历史，按「主题词 + 提价关键词」回溯检索，抽出带日期的涨价事件串成时间线。
# （财经快讯/韭研只有近端实时流，无法回溯一年，故时间线以库内三源为骨架。）

def _theme_query_terms(theme: str) -> list[str]:
    """主题名 → 检索词：归一后的主干词 + 原始名，去重去空，过滤过短词。"""
    out: list[str] = []
    for t in (_normalize_theme(theme), (theme or "").strip()):
        t = (t or "").strip()
        if len(t) >= 2 and t not in out:
            out.append(t)
    return out


def _build_theme_timeline(theme: str, days: int = 365) -> dict:
    """回溯近 ``days`` 天库内三源里命中「主题词 + 提价关键词」的事件，构造时间线。"""
    import sqlite3
    from quantforge.data.storage import db_cache as _db
    from quantforge.data.storage import stock_meta_cache

    terms = _theme_query_terms(theme)
    if not terms:
        return {"theme": theme, "events": [], "total": 0}
    begin = (date.today() - timedelta(days=days)).isoformat()
    events: list[dict] = []

    # 1) 机构荐股 / 调研纪要（标题+正文）
    try:
        for t in terms:
            for r in _db.blog_posts_search([t], begin_date=begin, limit=300):
                title = (r.get("ai_title") or r.get("title") or "").strip()
                body = (r.get("content_text") or "").strip()
                blob = f"{title} {body}"
                if not _hit_keywords(blob):
                    continue
                events.append({
                    "date": (r.get("created_at") or "")[:10],
                    "source": "机构荐股", "source_kind": "blog",
                    "title": title or body[:40],
                    "event_type": _event_type(blob),
                    "url": "",
                })
    except Exception as e:
        logger.debug("theme timeline blog failed: %s", e)

    # 2) 行业研报（标题/行业名）
    try:
        for t in terms:
            for r in _db.industry_reports_search([t], begin_date=begin, limit=300):
                title = (r.get("title") or "").strip()
                ind = (r.get("industry_name") or "").strip()
                blob = f"{title} {ind}"
                if not _hit_keywords(blob):
                    continue
                events.append({
                    "date": (r.get("publish_date") or "")[:10],
                    "source": "行业研报", "source_kind": "industry_report",
                    "title": title, "event_type": _event_type(blob), "url": "",
                })
    except Exception as e:
        logger.debug("theme timeline industry failed: %s", e)

    # 3) 个股研报（标题，自带代码）
    try:
        names = {}
        try:
            names = stock_meta_cache.get_all_names()
        except Exception:
            pass
        conn: sqlite3.Connection = _db._conn()
        like_kw = " OR ".join(["title LIKE ?"] * len(_PRICE_KEYWORDS))
        for t in terms:
            params: list = [f"%{t}%"]
            params += [f"%{kw}%" for kw in _PRICE_KEYWORDS]
            params.append(begin)
            rows = conn.execute(
                f"SELECT code, title, org, publish_date FROM stock_reports "
                f"WHERE title LIKE ? AND ({like_kw}) AND publish_date >= ? "
                f"ORDER BY publish_date DESC LIMIT 200",
                params,
            ).fetchall()
            for r in rows:
                title = (r["title"] or "").strip()
                code = (r["code"] or "").strip()
                nm = names.get(code) or names.get(code.zfill(6)) or ""
                events.append({
                    "date": (r["publish_date"] or "")[:10],
                    "source": "个股研报", "source_kind": "stock_report",
                    "title": title, "event_type": _event_type(title),
                    "stock": f"{nm}({code})" if nm else code, "url": "",
                })
    except Exception as e:
        logger.debug("theme timeline stock_report failed: %s", e)

    # 去重（同日同标题前 20 字）+ 升序
    seen: set[str] = set()
    uniq: list[dict] = []
    for e in sorted(events, key=lambda x: x.get("date") or ""):
        d = e.get("date") or ""
        key = d + "|" + (e.get("title") or "")[:20]
        if not d or key in seen:
            continue
        seen.add(key)
        uniq.append(e)

    by_type: dict[str, int] = {}
    by_month: dict[str, int] = {}
    for e in uniq:
        by_type[e["event_type"]] = by_type.get(e["event_type"], 0) + 1
        ym = (e.get("date") or "")[:7]
        if ym:
            by_month[ym] = by_month.get(ym, 0) + 1

    return {
        "theme": theme,
        "terms": terms,
        "events": uniq,
        "total": len(uniq),
        "first_date": uniq[0]["date"] if uniq else "",
        "last_date": uniq[-1]["date"] if uniq else "",
        "by_type": by_type,
        "by_month": by_month,
        "span_days": days,
        "generated_at": datetime.now().isoformat(),
    }


@router.get("/theme-timeline")
async def theme_timeline(
    theme: str = Query(..., description="涨价主题/品种名，如 制冷剂"),
    days: int = Query(365, ge=30, le=730),
    force: bool = Query(False),
):
    """单个涨价主题的一年涨价事件时间线（库内研报+机构荐股回溯，缓存 6 小时）。"""
    safe = re.sub(r"[^\w一-龥]", "_", theme)[:40] or "x"
    cache_name = f"theme_{safe}_{days}"
    if not force:
        cached = _load_cache(cache_name, ttl=6 * 3600)
        if cached:
            return cached
    result = await asyncio.to_thread(_build_theme_timeline, theme, days)
    if result.get("events"):
        _save_cache(cache_name, result)
    return result


@router.get("/refresh")
async def refresh_analysis():
    """强制重新采集线索 + 重新生成 AI 分析（后台异步，立即返回 accepted）。"""
    from quantforge.data.storage import db_cache
    db_cache.delete(_analysis_ck())
    for f in _CACHE_DIR.glob("signals_*.json"):
        try:
            f.unlink()
        except Exception:
            pass

    harvest = await asyncio.to_thread(_harvest_signals)
    _save_cache(f"signals_{date.today().isoformat()}", harvest)
    asyncio.create_task(_ensure_analysis(harvest))
    return {"status": "accepted", "message": "正在重新采集涨价线索并生成分析，请稍候刷新页面"}


@router.post("/backfill")
async def backfill(date_str: str = Query(..., alias="date", description="回填基准日 YYYY-MM-DD")):
    """回填历史某日的涨价分析并存档（同步等待生成）。

    库内研报/机构荐股/韭研按 [date-12d, date] 切片回溯；快讯不可回溯被跳过，
    故 date<今天的存档会带 partial=true 标注。覆盖式写入 price_surge:analysis:{date}。
    """
    from quantforge.data.storage import db_cache
    try:
        as_of = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return {"status": "error", "message": "日期格式应为 YYYY-MM-DD"}
    if as_of > date.today():
        return {"status": "error", "message": "不能回填未来日期"}

    harvest = await asyncio.to_thread(_harvest_signals, as_of)
    result = await _run_ai_analysis(harvest)
    db_cache.set(
        f"{_ANALYSIS_PREFIX}{date_str}", result,
        ttl_seconds=366 * 86400, category="price_surge",
    )
    return {
        "status": "ok",
        "date": date_str,
        "signal_count": harvest.get("total", 0),
        "theme_count": len(result.get("themes") or []),
        "partial": result.get("partial", False),
        "by_source": harvest.get("by_source", {}),
    }


# ── 每日自动归档 ───────────────────────────────────────────────────────────────
# 需求：每个交易日「晚 10 点」归纳当日涨价线索，供客户次日开盘前回看。AI 分析以
# price_surge:analysis:{date} 落档，但仅在有人访问时才生成；这里加一个盘后定时任务，
# 无人访问也把分析存进去，保证「历史存档 / 时间脉络」每天有底。默认开，QF_NO_PRICE_SURGE_DAILY=1 关。
#
# 触发规则（用户要求）：每日 22:00 触发，但仅在「今天是交易日，或明天是交易日（=开盘前 1 日）」
# 时才真正归档——即跳过纯休市夜（周六、长假中段），并保证每个开盘日的前一晚都有最新分析。

_DAILY_HM = (22, 0)

# A 股交易日历缓存：(刷新日, 交易日 date 集合)。用 akshare 真实日历（含法定节假日/调休），
# 取不到时回退到「工作日=交易日」的粗略判断。
_TRADE_CAL: tuple[date, frozenset[date]] | None = None


def _trade_days() -> frozenset[date]:
    """返回 A 股交易日集合（akshare 真实日历，每日刷新一次；失败回退空集合）。"""
    global _TRADE_CAL
    today = date.today()
    if _TRADE_CAL is not None and _TRADE_CAL[0] == today:
        return _TRADE_CAL[1]
    days: frozenset[date] = frozenset()
    try:
        import akshare as ak

        df = ak.tool_trade_date_hist_sina()
        col = df["trade_date"]
        parsed: set[date] = set()
        for v in col:
            if isinstance(v, date) and not isinstance(v, datetime):
                parsed.add(v)
            else:
                try:
                    parsed.add(datetime.fromisoformat(str(v)[:10]).date())
                except Exception:
                    pass
        days = frozenset(parsed)
    except Exception as e:
        logger.debug("price_surge 取交易日历失败，回退工作日判断：%s", e)
    _TRADE_CAL = (today, days)
    return days


def _is_trade_day(d: date) -> bool:
    """d 是否 A 股交易日。日历可用则查表；日历缺该日期(如跨年)或取不到则按工作日粗判。"""
    cal = _trade_days()
    if cal:
        if d in cal:
            return True
        # 日历有数据但不含 d：仅当 d 在日历覆盖范围内才信其为「非交易日」，
        # 超出范围（如次年）退回工作日判断，避免误杀。
        if min(cal) <= d <= max(cal):
            return False
    return d.weekday() < 5


def _should_archive_now() -> bool:
    """22:00 触发时是否归档：今天是交易日，或明天是交易日（开盘前 1 日）。"""
    today = date.today()
    return _is_trade_day(today) or _is_trade_day(today + timedelta(days=1))


def _seconds_until(hour: int, minute: int) -> float:
    now = datetime.now()
    nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


async def _archive_today() -> None:
    """采集当日线索 → AI 分析 → 覆盖写入 price_surge:analysis:{today}。best-effort。"""
    from quantforge.data.storage import db_cache
    try:
        harvest = await asyncio.to_thread(_harvest_signals)
        if harvest.get("signals"):
            _save_cache(f"signals_{date.today().isoformat()}", harvest)
        result = await _run_ai_analysis(harvest)
        db_cache.set(_analysis_ck(), result, ttl_seconds=366 * 86400, category="price_surge")
        logger.info("price_surge 当日存档完成：%s 个主题", len(result.get("themes") or []))
    except Exception as e:
        logger.warning("price_surge 当日存档失败：%s", e)


async def daily_archive_scheduler() -> None:
    """每日 22:00 归档当天涨价分析（仅交易日 / 开盘前 1 日）；启动时补一次当天缺失的存档。"""
    from quantforge.data.storage import db_cache

    await asyncio.sleep(90)  # 让启动其它预热先跑
    try:
        # 启动补档同样只在交易日 / 开盘前一日做，休市夜不留空档也不浪费 token。
        if _should_archive_now() and not db_cache.get_stale(_analysis_ck()):
            await _archive_today()
    except Exception as e:
        logger.debug("price_surge 启动补档失败：%s", e)

    while True:
        await asyncio.sleep(max(60, _seconds_until(*_DAILY_HM)))
        if _should_archive_now():
            await _archive_today()
        else:
            logger.info("price_surge 今晚非交易日且明日休市，跳过归档")
        await asyncio.sleep(90)  # 跨过整分，避免同一时刻重复触发
