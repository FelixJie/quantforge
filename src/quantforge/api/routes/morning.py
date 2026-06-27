"""每日晨报聚合接口。

把分散在各处的「开盘前必看」信息聚合成一屏 / 一条推送，开篇先看大盘与消息面，
再落到个人持仓与策略：
  - 大盘速览（核心指数 + 隔夜外盘 + 涨跌家数 + 两市成交额 + 连板情绪）
  - 市场情绪（多源消息面 AI 研判 + 情绪分 + 热点主题 + 头条）
  - 自选异动（涨跌、触及止盈止损的初筛）
  - 今日 AI 选股 Top N
  - 昨日信号结算（整体胜率 + 分组 + 最近已结算）
  - 数据源健康（先给轻量版，后续加深为交叉校验）

全部复用现有函数，不重写业务逻辑。各板块独立兜底、并行抓取，单块失败/超时不
拖垮整张晨报。
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

import requests

from fastapi import APIRouter, Depends, Query

from quantforge.api.routes.auth import get_optional_user

router = APIRouter(prefix="/morning", tags=["morning"])

logger = logging.getLogger("quantforge.api.morning")

# 晨报/复盘各 AI 模块（总览/三段正文/复盘汇总/外盘读图/复盘九段框架）的缓存 TTL。
# 缓存键按「日期」分桶（如 morning:brief_ai:2026-06-19），各天互不覆盖，所以这里直接
# 保留约一年——8:00 生成后一整天甚至往后回看都命中，不会 4 小时一过期就退回"加载中"。
# review.py / review_framework.py 复用此常量，保持三处一致。
_AI_TTL = 366 * 86400

# 晨报/复盘的 AI 调用强制以 MiniMax 引领（即便全局 config 误选了欠费的 DeepSeek，
# 这些后台预热也直接打 MiniMax，不先撞一次 402 再回退）。其它预设仍作兜底。
# review.py / review_framework.py 复用此常量。
_LLM_PROVIDER = "minimax-m3"

# 大盘速览里指数的分组：国内核心 vs 隔夜外盘（晨报开盘前最该看外盘怎么走）。
_DOMESTIC_INDEX = {"000001", "399001", "399006", "000688", "899050", "000300", "000905", "000852"}
_OVERSEAS_INDEX = {"DJI", "IXIC", "INX", "HSI", "N225", "KOSPI"}


# ── 各板块构建器（每个都自我兜底，单块失败不拖垮整张晨报）──────────────

async def _safe(coro, label: str, fallback: Any, timeout: float | None = None) -> Any:
    """跑一个板块协程，吞掉任何异常/超时并落日志，返回兜底值。

    晨报是聚合页，任何单源（指数/情绪/AI）抖动或慢调用都不该让整页 500 或挂死。
    """
    try:
        if timeout is not None:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro
    except asyncio.TimeoutError:
        logger.warning("morning %s section timed out after %ss", label, timeout)
        return fallback
    except Exception as exc:  # noqa: BLE001 — 聚合页刻意吞所有异常
        logger.warning("morning %s section failed: %s", label, exc)
        return fallback


async def _section_market() -> dict[str, Any]:
    """大盘速览：核心指数 + 隔夜外盘 + 涨跌家数 + 两市成交额 + 连板情绪。

    全部复用 market 路由里已有的接口函数（带各自的本地快照/缓存与多源回退），
    四路并行抓取，任一路失败只丢自己那块。
    """
    from quantforge.api.routes.market import (
        get_limit_pool,
        get_market_breadth,
        get_market_indices,
        get_market_turnover,
    )

    indices_payload, breadth, turnover, limit = await asyncio.gather(
        _safe(get_market_indices(), "indices", {"indices": []}),
        _safe(get_market_breadth(), "breadth", None),
        _safe(get_market_turnover(), "turnover", None),
        _safe(get_limit_pool(), "limit", None),
    )

    raw = (indices_payload or {}).get("indices", []) if isinstance(indices_payload, dict) else []
    def _slim(it: dict) -> dict:
        return {
            "code": it.get("code"), "name": it.get("name"),
            "price": it.get("price"), "change_pct": it.get("change_pct"),
            "change": it.get("change"),
        }
    domestic = [_slim(i) for i in raw if i.get("code") in _DOMESTIC_INDEX]
    overseas = [_slim(i) for i in raw if i.get("code") in _OVERSEAS_INDEX]

    breadth_out = None
    if isinstance(breadth, dict):
        breadth_out = {
            "up_count": breadth.get("up_count"), "down_count": breadth.get("down_count"),
            "flat_count": breadth.get("flat_count"), "limit_up": breadth.get("limit_up"),
            "limit_down": breadth.get("limit_down"),
            "advance_decline_ratio": breadth.get("advance_decline_ratio"),
        }
    limit_out = None
    if isinstance(limit, dict) and limit.get("zt_count"):
        limit_out = {
            "zt_count": limit.get("zt_count"), "zb_count": limit.get("zb_count"),
            "seal_rate": limit.get("seal_rate"), "top_height": limit.get("top_height"),
        }
    return {
        "ok": True,
        "domestic": domestic,
        "overseas": overseas,
        "breadth": breadth_out,
        "turnover": turnover if isinstance(turnover, dict) else None,
        "limit": limit_out,
    }


_sentiment_warming = False  # 进程级单飞，避免冷缓存被反复刷时堆叠多个慢预热任务


def _warm_sentiment() -> None:
    """后台把市场情绪缓存填上，让下次晨报/刷新秒回。单飞 + 失败静默。

    本环境里这条链路（多源消息面拉取 + LLM 研判）很慢甚至会卡住，所以只在后台跑，
    成功了就进 news 的 10 分钟缓存，下次晨报直接命中。"""
    global _sentiment_warming
    if _sentiment_warming:
        return

    async def _run():
        global _sentiment_warming
        try:
            from quantforge.api.routes.news import get_market_sentiment
            await get_market_sentiment()
        except Exception as exc:  # noqa: BLE001
            logger.debug("morning sentiment warm failed: %s", exc)
        finally:
            _sentiment_warming = False

    try:
        asyncio.create_task(_run())
        _sentiment_warming = True
    except RuntimeError:
        pass


async def _section_sentiment() -> dict[str, Any]:
    """市场情绪：复用 /news/sentiment 的结果（AI 一句话研判 + 情绪分 + 热点 + 头条）。

    只读 news 已写好的 10 分钟缓存——命中就秒回完整结果；没命中绝不在请求里现算
    （那条链路要现拉多源消息面 + 调 LLM，本环境动辄上分钟），而是后台预热、本次先
    返回 pending。这样情绪面永远不会拖垮/拖慢整张晨报。
    """
    from quantforge.api.routes import news
    try:
        sent = news._load_cache("market_sentiment", ttl_minutes=10)
    except Exception:  # noqa: BLE001 — 读缓存失败按未命中处理
        sent = None
    if not isinstance(sent, dict):
        _warm_sentiment()
        return {"ok": True, "pending": True}
    return {
        "ok": True,
        "score": sent.get("score"),
        "label": sent.get("label"),
        "level": sent.get("level"),
        "ai_view": sent.get("ai_view"),
        "hot_themes": sent.get("hot_themes", [])[:6],
        "headlines": sent.get("recent_headlines", [])[:5],
    }


# ── 走势 & 外盘研判 ─────────────────────────────────────────────────────────
#
# 走势：从核心指数日 K 线算技术形态（均线位置/近期涨跌/连阳连阴/均线排列），纯计算、
#       走 K 线本地缓存，快且可靠，永远能出数。
# 研判：一次 AI 调用，结合隔夜外盘涨跌 + 指数形态给开盘前研判。AI 虽快但仍按情绪面
#       那套「只读缓存 + 后台预热」处理，绝不在请求里现等，保证晨报始终秒回。

# 走势覆盖的核心指数：(显示名, 带市场前缀的 K 线代码)。指数码必须带前缀，
# 否则 000001 会被当成平安银行(sz)而非上证指数(sh)。
_TREND_INDEX = [
    ("上证指数", "SH000001"),
    ("深证成指", "SZ399001"),
    ("创业板指", "SZ399006"),
    ("科创50", "SH000688"),
    ("北证50", "BJ899050"),
    ("沪深300", "SH000300"),
    ("中证1000", "SH000852"),
]

_analysis_warming = False


def _mean(xs: list[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def _compute_trend(name: str, bars: list[dict]) -> Optional[dict]:
    """从日 K 线算单个指数的技术走势画像。bars 升序，元素含 close。"""
    closes = [b.get("close") for b in bars if isinstance(b.get("close"), (int, float))]
    if len(closes) < 6:
        return None
    price = closes[-1]
    ma5 = _mean(closes[-5:])
    ma10 = _mean(closes[-10:]) if len(closes) >= 10 else None
    ma20 = _mean(closes[-20:]) if len(closes) >= 20 else None
    chg5 = (price / closes[-6] - 1) * 100 if len(closes) >= 6 else None
    chg20 = (price / closes[-21] - 1) * 100 if len(closes) >= 21 else None

    # 连阳(正)/连跌(负)：从最近一根往前数同向天数
    streak = 0
    for i in range(len(closes) - 1, 0, -1):
        d = closes[i] - closes[i - 1]
        if d > 0:
            if streak >= 0:
                streak += 1
            else:
                break
        elif d < 0:
            if streak <= 0:
                streak -= 1
            else:
                break
        else:
            break

    label = "震荡"
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            label = "多头排列"
        elif ma5 < ma10 < ma20:
            label = "空头排列"
        elif price > ma20:
            label = "偏多"
        else:
            label = "偏弱"

    return {
        "name": name,
        "price": round(price, 2),
        "ma5": round(ma5, 2) if ma5 else None,
        "ma20": round(ma20, 2) if ma20 else None,
        "chg5": round(chg5, 2) if chg5 is not None else None,
        "chg20": round(chg20, 2) if chg20 is not None else None,
        "streak": streak,
        "above_ma20": bool(ma20 is not None and price > ma20),
        "label": label,
    }


async def _index_trends() -> list[dict]:
    """并行算核心指数走势画像（K 线走本地增量缓存）。"""
    from quantforge.api.routes.market import _kline_cached
    out: list[dict] = []

    async def _one(name: str, code: str) -> None:
        try:
            bars, _ = await _kline_cached(code, "day", 30)
            t = _compute_trend(name, bars)
            if t:
                out.append(t)
        except Exception as exc:  # noqa: BLE001
            logger.debug("morning trend %s failed: %s", code, exc)

    await asyncio.gather(*[_one(n, c) for n, c in _TREND_INDEX])
    order = {n: i for i, (n, _) in enumerate(_TREND_INDEX)}
    out.sort(key=lambda x: order.get(x["name"], 99))
    return out


async def _ai_market_analysis(overseas: list[dict], trend: list[dict]) -> Optional[str]:
    """结合隔夜外盘 + 指数形态的开盘前 AI 研判。best-effort，失败返回 None。"""
    from quantforge.api.ai_client import chat

    ov = "、".join(
        f"{i.get('name')}{i.get('change_pct'):+.2f}%"
        for i in overseas if isinstance(i.get("change_pct"), (int, float))
    )
    parts = []
    for t in trend:
        bits = [t["name"], t["label"]]
        if t.get("chg5") is not None:
            bits.append(f"5日{t['chg5']:+.1f}%")
        bits.append("站上20日线" if t.get("above_ma20") else "跌破20日线")
        parts.append(" ".join(bits))
    tr = "；".join(parts)
    if not ov and not tr:
        return None

    system = "你是资深A股策略分析师，擅长结合隔夜外盘与指数技术形态研判当日方向。"
    user = (
        f"隔夜外盘：{ov or '暂无'}。\n"
        f"A股核心指数走势：{tr or '暂无'}。\n"
        "请用中文给开盘前研判，分两点：1)外盘对A股的影响与可能映射的板块；"
        "2)大盘技术走势与今日关注点(支撑/压力或方向)。每点1-2句、共120字内，"
        "直接给结论，不要分点编号、不要使用 * # 等 markdown 符号。"
    )
    text = await chat(system, user, max_tokens=400, caller="morning_analysis", timeout=25,
                      provider=_LLM_PROVIDER)
    return (text or "").replace("*", "").replace("#", "").strip() or None


def _analysis_ck() -> str:
    return f"morning:analysis_ai:{date.today().isoformat()}"


def _warm_analysis() -> None:
    """后台算外盘+走势 AI 研判并落库（当日缓存）。单飞 + 失败静默。"""
    global _analysis_warming
    if _analysis_warming:
        return

    async def _run():
        global _analysis_warming
        try:
            from quantforge.data.storage import db_cache as _db
            from quantforge.api.routes.market import get_market_indices
            idx = await get_market_indices()
            overseas = [
                i for i in (idx.get("indices") or [])
                if i.get("code") in _OVERSEAS_INDEX
            ]
            trend = await _index_trends()
            ai = await _ai_market_analysis(overseas, trend)
            if ai:
                await asyncio.to_thread(
                    _db.set, _analysis_ck(), {"ai_view": ai}, _AI_TTL, "morning"
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("morning analysis warm failed: %s", exc)
        finally:
            _analysis_warming = False

    try:
        asyncio.create_task(_run())
        _analysis_warming = True
    except RuntimeError:
        pass


async def _section_analysis() -> dict[str, Any]:
    """大盘走势画像（即时计算）+ 外盘/走势 AI 研判（只读当日缓存，没命中后台预热）。"""
    trend = await _safe(_index_trends(), "trend", [])
    ai_view = None
    try:
        from quantforge.data.storage import db_cache as _db
        cached = await asyncio.to_thread(_db.get, _analysis_ck(), _AI_TTL)
        if isinstance(cached, dict):
            ai_view = cached.get("ai_view")
    except Exception:  # noqa: BLE001
        ai_view = None
    if not ai_view:
        _warm_analysis()
    return {"ok": True, "trend": trend, "ai_view": ai_view, "pending": ai_view is None}


# ── 每日复盘总结（公众号 + 机构选股 的分析/汇总/总结类内容 → AI 汇总）────────────
#
# 把「公众号」(纷传)与「机构选股」(知识星球)当天发的**分析/汇总/总结类**帖子
# 收拢起来，用一次 AI 调用汇总成一段「每日复盘」。沿用情绪/研判那套「只读当日缓存 +
# 后台预热」——这条链路要读两处缓存/库 + 调 LLM，绝不在请求里现等，保证晨报始终秒回。

# 命中即视为「分析/汇总/总结类」的标题/正文关键词（荐股喊单、纯链接广告天然不含这些词）。
_REVIEW_KEYWORDS = (
    "复盘", "收评", "午评", "早评", "盘前", "盘后", "盘中", "总结", "汇总", "综述",
    "点评", "研判", "展望", "前瞻", "解读", "纪要", "回顾", "大势", "日报", "晚报",
    "周报", "策略", "观点", "小结", "梳理",
)

_REVIEW_MAX_ITEMS = 24          # 喂给 AI 的最多帖子数
_REVIEW_ITEM_CHARS = 500        # 单帖正文截断长度
_REVIEW_TOTAL_CHARS = 9000      # 汇总素材总长度上限


def _today_str() -> str:
    return date.today().isoformat()


def _is_today(ts: str) -> bool:
    """帖子时间是否为今天。纷传 '2026-06-15 17:47' / zsxq '2026-06-15T..' 都以日期开头。"""
    return bool(ts) and ts.strip()[:10] == _today_str()


def _hit_review_kw(*texts: str) -> bool:
    blob = " ".join(t for t in texts if t)
    return any(kw in blob for kw in _REVIEW_KEYWORDS)


def _collect_review_items() -> list[dict]:
    """收拢公众号 + 机构选股当天的分析/汇总/总结类帖子（含正文片段）。

    纯本地读缓存/库、零网络。返回 [{source, author, title, text}]，已按来源去噪截断。
    """
    items: list[dict] = []

    # 公众号（纷传）：快照缓存里就有完整正文。
    try:
        from quantforge.api.routes import fenchuan
        snap = fenchuan._load_cache()
        for p in (snap.get("posts") or []):
            if p.get("is_top"):  # 置顶老帖不算当天
                continue
            title, text = p.get("title", ""), p.get("text", "")
            if not _is_today(p.get("time", "")):
                continue
            if not _hit_review_kw(title, text):
                continue
            items.append({
                "source": "公众号",
                "author": p.get("author", ""),
                "title": title,
                "text": (text or "")[:_REVIEW_ITEM_CHARS],
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug("morning review: fenchuan collect failed: %s", exc)

    # 机构选股（知识星球）：列表只带预览，命中关键词的再取全文。
    try:
        from quantforge.data.storage import db_cache
        rows, _ = db_cache.blog_query(page=1, page_size=60)
        for r in rows:
            if not _is_today(r.get("created_at", "")):
                continue
            title = r.get("ai_title") or r.get("title") or ""
            preview = r.get("preview", "")
            if not _hit_review_kw(title, preview):
                continue
            text = preview
            full = db_cache.blog_get(r.get("post_id"))
            if isinstance(full, dict) and full.get("content_text"):
                text = full["content_text"]
            items.append({
                "source": "机构选股",
                "author": r.get("author", ""),
                "title": title,
                "text": (text or "")[:_REVIEW_ITEM_CHARS],
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug("morning review: blog collect failed: %s", exc)

    return items[:_REVIEW_MAX_ITEMS]


async def _ai_review_summary(items: list[dict]) -> Optional[str]:
    """把当天分析/总结类帖子汇总成一段复盘。best-effort，失败返回 None。"""
    from quantforge.api.ai_client import chat

    blocks, used = [], 0
    for it in items:
        head = f"【{it['source']}·{it.get('author') or '佚名'}】{it.get('title') or ''}".strip()
        body = (it.get("text") or "").strip()
        chunk = f"{head}\n{body}".strip()
        if used + len(chunk) > _REVIEW_TOTAL_CHARS:
            break
        blocks.append(chunk)
        used += len(chunk)
    if not blocks:
        return None

    system = (
        "你是资深A股投研编辑，擅长把多篇公众号与机构观点提炼成一份当日复盘。"
    )
    user = (
        "下面是今天来自『公众号』和『机构选股』的分析/复盘/总结类内容，可能有重复或噪声：\n\n"
        + "\n\n".join(blocks)
        + "\n\n请综合这些内容，写一段中文『每日复盘总结』，分三块："
        "1)今日盘面与市场情绪回顾；2)主要资金/机构关注的板块与主线(可点名)；"
        "3)分歧点与后市观点。每块2-3句、共300字内，直接给结论，"
        "不要罗列原文出处、不要分点编号、不要使用 * # 等 markdown 符号。"
    )
    text = await chat(system, user, max_tokens=700, caller="morning_review", timeout=40,
                      provider=_LLM_PROVIDER)
    return (text or "").replace("*", "").replace("#", "").strip() or None


def _review_ck() -> str:
    return f"morning:review_ai:{_today_str()}"


_review_warming = False


def _warm_review() -> None:
    """后台收拢素材 + AI 汇总当日复盘并落库（当日缓存）。单飞 + 失败静默。"""
    global _review_warming
    if _review_warming:
        return

    async def _run():
        global _review_warming
        try:
            from quantforge.data.storage import db_cache as _db
            items = await asyncio.to_thread(_collect_review_items)
            if not items:
                # 没有素材也写个空标记，避免每次刷新都重复扫库/触发预热。
                await asyncio.to_thread(
                    _db.set, _review_ck(),
                    {"summary": None, "sources": 0}, _AI_TTL, "morning")
                return
            summary = await _ai_review_summary(items)
            if summary:
                src = sorted({it["source"] for it in items})
                await asyncio.to_thread(
                    _db.set, _review_ck(),
                    {"summary": summary, "sources": len(items), "from": src},
                    _AI_TTL, "morning")
        except Exception as exc:  # noqa: BLE001
            logger.debug("morning review warm failed: %s", exc)
        finally:
            _review_warming = False

    try:
        asyncio.create_task(_run())
        _review_warming = True
    except RuntimeError:
        pass


async def _section_review() -> dict[str, Any]:
    """每日复盘总结：只读当日缓存（AI 汇总公众号+机构选股的分析类内容），没命中后台预热。"""
    cached = None
    try:
        from quantforge.data.storage import db_cache as _db
        cached = await asyncio.to_thread(_db.get, _review_ck(), _AI_TTL)
    except Exception:  # noqa: BLE001
        cached = None
    if not isinstance(cached, dict):
        _warm_review()
        return {"ok": True, "pending": True}
    return {
        "ok": True,
        "summary": cached.get("summary"),
        "sources": cached.get("sources", 0),
        "from": cached.get("from", []),
        "empty": not cached.get("summary"),
    }


# ── 今日总览（置顶 AI 综合总结，「总分」结构的「总」）────────────────────────────
#
# 把开盘前各维度信息（外盘 / 大盘形态研判 / 情绪 / 公众号机构复盘要点）浓缩成一段
# 「先结论后要点」的总览，放在晨报最前面。沿用「只读当日缓存 + 后台预热」：冷缓存
# 先返回 pending、后台单飞算好落库，绝不在请求里现等 LLM。

_overview_warming = False


def _overview_ck() -> str:
    return f"morning:overview_ai:{_today_str()}"


def _live_headlines(limit: int = 14) -> list[str]:
    """读站内实时财经快讯流(THS财联社/cls/global，news /flash 的 3 分钟缓存)的最新标题。

    这是本环境里唯一可靠的「实时外部调研」信号源：盘前喂给 AI 总览，让研判贴当下要闻。
    只读缓存(stale 亦可)，零网络、不阻塞；冷缓存则后台 kick 一次预热，本次先空着。
    """
    try:
        from quantforge.api.routes import news
        data = news._load_cache("flash_40", ttl_minutes=15) or news._load_stale("flash_40")
        if not isinstance(data, dict) or not data.get("items"):
            try:
                asyncio.create_task(news.get_flash_news(40))  # 后台预热
            except RuntimeError:
                pass
            return []
        out = []
        for it in data["items"][:limit]:
            t = (it.get("title") or "").strip()
            if t:
                out.append(t)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.debug("morning live headlines failed: %s", exc)
        return []


async def _ai_overview_text(market: dict, analysis_ai: Optional[str],
                            sentiment: Optional[dict],
                            review_summary: Optional[str],
                            picks: Optional[dict] = None,
                            verify: Optional[dict] = None,
                            live_news: Optional[list[str]] = None) -> Optional[str]:
    """开盘前综合总览：核心研判 + 外盘/方向/资金情绪/主线/风险 多段结构化长文。失败返回 None。"""
    from quantforge.api.ai_client import chat

    parts: list[str] = []
    ov = "、".join(
        f"{i.get('name')}{i.get('change_pct'):+.2f}%"
        for i in (market.get("overseas") or [])
        if isinstance(i.get("change_pct"), (int, float)))
    if ov:
        parts.append(f"隔夜外盘：{ov}")
    dom = "、".join(
        f"{i.get('name')}{i.get('change_pct'):+.2f}%"
        for i in (market.get("domestic") or [])
        if isinstance(i.get("change_pct"), (int, float)))
    if dom:
        parts.append(f"A股核心指数(上一交易日)：{dom}")
    br = market.get("breadth") or {}
    if br.get("up_count") is not None:
        parts.append(f"涨跌家数：涨{br.get('up_count')}/跌{br.get('down_count')}")
    to = market.get("turnover") or {}
    if to.get("total_amount") is not None:
        parts.append(f"两市成交：{to['total_amount']}亿")
    lim = market.get("limit") or {}
    if lim.get("top_height"):
        parts.append(f"上一交易日最高连板：{lim['top_height']}板，封板率{lim.get('seal_rate')}%")
    if isinstance(sentiment, dict) and sentiment.get("label"):
        parts.append(f"市场情绪：{sentiment.get('label')}（{sentiment.get('score')}）")
        themes = sentiment.get("hot_themes") or []
        if themes:
            parts.append("消息面热点：" + "、".join(str(t) for t in themes[:8]))
    if live_news:
        parts.append("今日实时财经快讯(节选)：\n" + "\n".join(f"· {h}" for h in live_news[:12]))
    if analysis_ai:
        parts.append(f"大盘走势研判：{analysis_ai}")
    if review_summary:
        parts.append(f"公众号/机构复盘要点：{review_summary}")
    if isinstance(picks, dict) and picks.get("picks"):
        names = "、".join(
            str(p.get("name") or p.get("symbol") or "") for p in picks["picks"][:8]
            if (p.get("name") or p.get("symbol")))
        if names:
            parts.append(f"今日AI选股(供参考)：{names}")
    if isinstance(verify, dict):
        ov_v = verify.get("overall") or {}
        if ov_v.get("win_rate") is not None:
            parts.append(f"历史选股累计胜率：{ov_v.get('win_rate')}（样本{ov_v.get('total')}）")
    if not parts:
        return None

    system = (
        "你是A股首席策略分析师，擅长把外盘、指数形态、消息面、实时快讯、机构观点等多维"
        "盘前信息综合成一份有信息量、可执行的开盘前研判。结论要具体、敢于点名板块与方向。"
    )
    user = (
        "以下是今日开盘前的多维信息(含实时财经快讯)：\n\n" + "\n".join(parts) +
        "\n\n请输出一份结构化的『今日总览』，要求：\n"
        "第一行先给一句话核心研判(不超过45字)，作为开头。\n"
        "随后另起段落，依次用下面五个标签开头各写1-2句(每个标签单独成段、标签后接内容)：\n"
        "外盘：隔夜外盘对A股的影响与可能映射的板块。\n"
        "方向：今日大盘方向、关键支撑/压力位或区间。\n"
        "资金情绪：成交量能、连板高度、市场情绪与风险偏好。\n"
        "主线：结合消息面热点与实时快讯，点出今日值得关注的1-3条主线/板块。\n"
        "风险：今日需要回避或警惕的风险点。\n"
        "全文中文、共350字左右，直接给结论与依据，不要罗列原始数据、不要分点编号、"
        "不要使用 * # 等 markdown 符号。"
    )
    text = await chat(system, user, max_tokens=900, caller="morning_overview", timeout=45,
                      provider=_LLM_PROVIDER)
    return (text or "").replace("*", "").replace("#", "").strip() or None


def _warm_overview() -> None:
    """后台收齐各维度（市场/研判/情绪/复盘总结）→ AI 综合总览并落库。单飞 + 失败静默。"""
    global _overview_warming
    if _overview_warming:
        return

    async def _run():
        global _overview_warming
        try:
            from quantforge.data.storage import db_cache as _db
            from quantforge.api.routes import news
            market = await _section_market()
            ana = await asyncio.to_thread(_db.get, _analysis_ck(), _AI_TTL)
            analysis_ai = ana.get("ai_view") if isinstance(ana, dict) else None
            try:
                senti = news._load_cache("market_sentiment", ttl_minutes=720)
            except Exception:  # noqa: BLE001
                senti = None
            rev = await asyncio.to_thread(_db.get, _review_ck(), _AI_TTL)
            review_summary = rev.get("summary") if isinstance(rev, dict) else None
            picks = await asyncio.to_thread(_section_picks)
            verify = await asyncio.to_thread(_section_verify)
            live_news = await asyncio.to_thread(_live_headlines)
            text = await _ai_overview_text(
                market, analysis_ai,
                senti if isinstance(senti, dict) else None, review_summary,
                picks=picks, verify=verify, live_news=live_news)
            if text:
                await asyncio.to_thread(
                    _db.set, _overview_ck(), {"text": text}, _AI_TTL, "morning")
        except Exception as exc:  # noqa: BLE001
            logger.debug("morning overview warm failed: %s", exc)
        finally:
            _overview_warming = False

    try:
        asyncio.create_task(_run())
        _overview_warming = True
    except RuntimeError:
        pass


async def _section_overview() -> dict[str, Any]:
    """今日总览：只读当日缓存（AI 综合各维度），没命中后台预热。"""
    cached = None
    try:
        from quantforge.data.storage import db_cache as _db
        cached = await asyncio.to_thread(_db.get, _overview_ck(), _AI_TTL)
    except Exception:  # noqa: BLE001
        cached = None
    if not isinstance(cached, dict):
        _warm_overview()
        return {"ok": True, "pending": True}
    return {"ok": True, "text": cached.get("text")}


async def _section_watchlist(user: Optional[dict]) -> dict[str, Any]:
    """自选概览 + 简单异动标记。复用 /watchlist/overview。"""
    if not user:
        return {"ok": True, "count": 0, "items": [], "movers": [], "note": "未登录"}
    try:
        from quantforge.api.routes.watchlist import get_watchlist_overview
        payload = await get_watchlist_overview(user)
        items = payload.get("items", []) if isinstance(payload, dict) else []
        movers: list[dict] = []
        for it in items:
            chg = it.get("change_pct")
            if isinstance(chg, (int, float)) and abs(chg) >= 3.0:
                movers.append(it)
        movers.sort(key=lambda x: abs(x.get("change_pct") or 0), reverse=True)
        return {
            "ok": True,
            "count": len(items),
            "items": items,
            "movers": movers[:10],
        }
    except Exception as exc:
        logger.exception("morning watchlist section failed")
        return {"ok": False, "error": str(exc)}


def _section_picks(strategy: str = "momentum", top_n: int = 10) -> dict[str, Any]:
    """今日 AI 选股最新一档，截断到 Top N。"""
    try:
        from quantforge.api.routes.ai_picks import _latest_today
        payload = _latest_today(strategy)
        if not payload:
            return {"ok": True, "picks": [], "generated_at": None, "empty": True}
        picks = payload.get("picks") or payload.get("recommendations") or []
        return {
            "ok": True,
            "generated_at": payload.get("generated_at"),
            "slot": payload.get("slot"),
            "strategy": strategy,
            "picks": picks[:top_n],
            "total": len(picks),
        }
    except Exception as exc:
        logger.exception("morning picks section failed")
        return {"ok": False, "error": str(exc)}


def _section_verify() -> dict[str, Any]:
    """信号结算统计。复用 PredictionTracker.get_stats()。"""
    try:
        from quantforge.prediction.tracker import PredictionTracker
        stats = PredictionTracker.get_stats()
        overall = {
            "win_rate": stats.get("accuracy_pct"),
            "total": stats.get("total"),
            "win": stats.get("win"),
            "loss": stats.get("loss"),
            "neutral": stats.get("neutral"),
            "avg_change_pct": stats.get("avg_change_pct"),
            "excess_avg_pct": stats.get("excess_avg_pct"),
            "beat_benchmark_pct": stats.get("beat_benchmark_pct"),
        }
        return {
            "ok": True,
            "overall": overall,
            "by_strategy": stats.get("by_pick_strategy", []),
        }
    except Exception as exc:
        logger.exception("morning verify section failed")
        return {"ok": False, "error": str(exc)}


def _section_data_health() -> dict[str, Any]:
    """数据源健康（轻量版）：读持久化快照表的新鲜度，零网络、秒回。

    后续可加深为多源交叉校验（同股价格互相打架告警）。
    """
    sources: list[dict] = []
    # 行情快照：stock_quote 表的覆盖量 + 最近刷新时间
    try:
        from quantforge.data.storage import db_cache
        cnt = db_cache.quote_count()
        updated = db_cache.quote_max_updated()
        ok = bool(cnt and cnt > 0)
        sources.append({"name": "行情快照", "ok": ok, "count": cnt, "updated_at": updated})
    except Exception as exc:
        sources.append({"name": "行情快照", "ok": False, "note": str(exc)[:60]})
    # 研报库：探一次研报摘要查询是否可用
    try:
        from quantforge.data.storage import db_cache
        if hasattr(db_cache, "reports_summary_many"):
            db_cache.reports_summary_many(["600519"])
            sources.append({"name": "研报库", "ok": True})
        else:
            sources.append({"name": "研报库", "ok": None, "note": "未接入"})
    except Exception as exc:
        sources.append({"name": "研报库", "ok": False, "note": str(exc)[:60]})
    return {"ok": True, "sources": sources}


# ── 隔夜美股（「180K」星球的「隔夜北美小结」，AI 读图分析）──────────────────────────
#
# 晨报开篇用「180K」知识星球每天清晨发的「隔夜北美小结」帖替代旧「大盘速览」。小结正文
# 本身是图，所以**让视觉 LLM 读图后产出一段隔夜美股分析**展示；原图缩成缩略图、点开放大。
# 读图(下载图片 + 视觉调用)很慢，沿用「只读缓存(按 post_id) + 后台单飞预热」，绝不在请求里现等。

_GROUP_180K = "28888222154481"          # 知识星球「180K」
_GROUP_RESEARCH = "28855458518111"      # 知识星球「调研纪要」
_OVERNIGHT_MARK = "隔夜北美小结"          # 该星球每日隔夜帖的固定正文标记
_OVERNIGHT_REFERER = "https://wx.zsxq.com/"  # zsxq 图片防盗链，下载需带 Referer
_OVERNIGHT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_OVERNIGHT_TTL = 7 * 86400              # 读图分析按 post_id 缓存一周（同一贴不重复读图）
_overnight_warming: set[str] = set()    # 正在读图预热的 post_id（单飞）


def _overnight_ck(post_id: str) -> str:
    return f"morning:overnight_ai:{post_id}"


def _fetch_image_b64(url: str) -> Optional[str]:
    """带 Referer 下载 zsxq 图片并 base64 编码（防盗链）。失败返回 None。"""
    try:
        r = requests.get(url, headers={"User-Agent": _OVERNIGHT_UA,
                                       "Referer": _OVERNIGHT_REFERER}, timeout=20)
        if r.status_code == 200 and r.content:
            return base64.b64encode(r.content).decode()
    except Exception as exc:  # noqa: BLE001
        logger.debug("overnight image fetch failed: %s", exc)
    return None


async def _ai_overnight_analysis(image_urls: list[str]) -> Optional[str]:
    """视觉 LLM 读「隔夜北美小结」图 → 一段隔夜美股分析。best-effort，失败返回 None。"""
    from quantforge.api.ai_client import chat
    b64s: list[str] = []
    for u in (image_urls or [])[:3]:
        b = await asyncio.to_thread(_fetch_image_b64, u)
        if b:
            b64s.append(b)
    if not b64s:
        return None
    system = "你是资深财经分析师，擅长读图并提炼隔夜美股(北美市场)要点。"
    user = (
        "这是『隔夜北美小结』的图片(可能多张)，内容是隔夜美股/北美市场的行情与要点。"
        "请读出图中关键信息，用中文按要点归纳、分条输出隔夜美股小结，每条要点另起一行、"
        "以「· 」开头，依次涵盖：三大股指与重要板块涨跌、资金面与市场情绪、商品/汇率/利率要点、"
        "对今日A股可能的映射与关注点，列 5-8 条。每条一句话、直给结论、控制在 40 字内；"
        "只用「· 」作要点符号，不要数字编号、不要使用 * # 等 markdown 符号。"
    )
    text = await chat(system, user, max_tokens=900, caller="morning_overnight",
                      images=b64s, timeout=90, provider=_LLM_PROVIDER)
    return (text or "").replace("*", "").replace("#", "").strip() or None


def _warm_overnight(post_id: str, image_urls: list[str]) -> None:
    """后台读图 + 视觉分析并落库（按 post_id 缓存）。单飞 + 失败静默。"""
    if not post_id or post_id in _overnight_warming or not image_urls:
        return

    async def _run():
        try:
            from quantforge.data.storage import db_cache as _db
            ana = await _ai_overnight_analysis(image_urls)
            if ana:
                await asyncio.to_thread(
                    _db.set, _overnight_ck(post_id), {"analysis": ana},
                    _OVERNIGHT_TTL, "morning")
        except Exception as exc:  # noqa: BLE001
            logger.debug("overnight warm failed: %s", exc)
        finally:
            _overnight_warming.discard(post_id)

    try:
        asyncio.create_task(_run())
        _overnight_warming.add(post_id)
    except RuntimeError:
        pass


async def _section_overnight_us() -> dict[str, Any]:
    """隔夜美股：最新「隔夜北美小结」的 AI 读图分析(只读缓存+后台预热) + 缩略图(走代理)。"""
    try:
        from quantforge.data.storage import db_cache
        rows, _ = db_cache.blog_query(
            search=_OVERNIGHT_MARK, group_id=_GROUP_180K, page=1, page_size=3)
        post = rows[0] if rows else None
        if not post:
            return {"ok": True, "empty": True}
        post_id = str(post.get("post_id") or "")
        raw_imgs = post.get("images") or []

        analysis = None
        try:
            from quantforge.data.storage import db_cache as _db
            cached = await asyncio.to_thread(_db.get, _overnight_ck(post_id), _OVERNIGHT_TTL)
            if isinstance(cached, dict):
                analysis = cached.get("analysis")
        except Exception:  # noqa: BLE001
            analysis = None
        if not analysis:
            _warm_overnight(post_id, raw_imgs)

        # 缩略图走 /api/xingqiu/image 代理（zsxq 图片有防盗链，浏览器直连取不到）
        try:
            from quantforge.api.routes.blog import _proxify_url
            imgs = [_proxify_url(u) for u in raw_imgs]
        except Exception:  # noqa: BLE001
            imgs = list(raw_imgs)

        return {
            "ok": True,
            "title": post.get("ai_title") or post.get("title") or _OVERNIGHT_MARK,
            "analysis": analysis,
            "analysis_pending": analysis is None,
            "images": imgs,
            "post_id": post_id,
            "created_at": post.get("created_at"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("morning overnight_us section failed: %s", exc)
        return {"ok": False}


# ── 晨报正文三部分（消息面 / 调研纪要 / 操作建议，一次 AI 汇总）───────────────────────
#
# 把三类素材喂给一次 LLM，产出三段带标签的晨报正文：
#   一·消息面   = 财联社/cls 实时快讯 + 公众号(纷传)当天早报类帖子（重点参考财联社）
#   二·调研纪要 = 「调研纪要」星球从上一交易日收盘到今早 8 点的帖子
#   三·操作建议 = 结合隔夜美股 + 上两段给出今日操作思路
# 沿用情绪/总览那套「只读当日缓存 + 后台单飞预热」：冷缓存返回 pending，绝不在请求里现等 LLM。

_brief_warming = False


def _brief_ck() -> str:
    return f"morning:brief_ai:{_today_str()}"


def _prev_trading_close() -> datetime:
    """上一交易日 15:00（粗略：跳过周末，不含法定节假日）。"""
    d = date.today() - timedelta(days=1)
    while d.weekday() >= 5:  # 5=周六 6=周日
        d -= timedelta(days=1)
    return datetime(d.year, d.month, d.day, 15, 0, 0)


def _collect_morning_news(limit_mp: int = 12) -> dict[str, list]:
    """消息面素材：财联社/cls 实时快讯标题 + 公众号(纷传)当天帖子（标题+正文片段）。"""
    cls = _live_headlines(20)
    mp: list[dict] = []
    try:
        from quantforge.api.routes import fenchuan
        snap = fenchuan._load_cache()
        for p in (snap.get("posts") or []):
            if p.get("is_top"):
                continue
            if not _is_today(p.get("time", "")):
                continue
            mp.append({
                "author": p.get("author", ""),
                "title": p.get("title", ""),
                "text": (p.get("text") or "")[:300],
            })
            if len(mp) >= limit_mp:
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("morning news: fenchuan collect failed: %s", exc)
    return {"cls": cls, "mp": mp}


def _collect_research_overnight(limit: int = 30) -> list[dict]:
    """调研纪要素材：「调研纪要」星球从上一交易日收盘以来的帖子（标题 + 正文片段）。"""
    items: list[dict] = []
    try:
        from quantforge.data.storage import db_cache
        start = _prev_trading_close().isoformat()
        rows, _ = db_cache.blog_query(group_id=_GROUP_RESEARCH, page=1, page_size=80)
        for r in rows:
            if (r.get("created_at") or "") < start:
                continue  # 列表按时间降序，早于上一交易日收盘的直接丢
            items.append({
                "author": r.get("author", ""),
                "title": r.get("ai_title") or r.get("title") or "",
                "text": (r.get("preview") or "")[:300],
                "post_id": r.get("post_id"),
            })
            if len(items) >= limit:
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("morning research collect failed: %s", exc)
    return items


_BRIEF_LABELS = [("news", "消息面"), ("research", "调研纪要"), ("advice", "操作建议")]


def _parse_brief(text: Optional[str]) -> Optional[dict]:
    """把带【消息面】【调研纪要】【操作建议】标签的整段拆成三块。"""
    if not text:
        return None
    clean = text.replace("*", "").replace("#", "")
    labels = [lab for _, lab in _BRIEF_LABELS]
    pat = re.compile(r"[【\[]?(" + "|".join(labels) + r")[】\]]?[:：]?")
    matches = list(pat.finditer(clean))
    out = {k: "" for k, _ in _BRIEF_LABELS}
    if not matches:
        out["news"] = clean.strip()
        return out
    for i, m in enumerate(matches):
        seg_start = m.end()
        seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(clean)
        seg = clean[seg_start:seg_end].strip(" \n\r:：")
        key = next(k for k, l in _BRIEF_LABELS if l == m.group(1))
        if seg:
            out[key] = seg
    return out if any(out.values()) else None


async def _ai_morning_brief(overnight_title: Optional[str], news: dict,
                            research: list[dict]) -> Optional[dict]:
    """三段晨报正文：一次 AI 调用。best-effort，失败返回 None。"""
    from quantforge.api.ai_client import chat

    parts: list[str] = []
    if overnight_title:
        parts.append(f"【隔夜美股】{overnight_title}")
    cls = (news or {}).get("cls") or []
    if cls:
        parts.append("【财联社/快讯】\n" + "\n".join(f"· {h}" for h in cls[:18]))
    mp = (news or {}).get("mp") or []
    if mp:
        blk = [f"·{m.get('author') or ''}：{m.get('title') or ''} {m.get('text') or ''}".strip()
               for m in mp[:12]]
        parts.append("【公众号早报】\n" + "\n".join(blk))
    if research:
        blk = [f"·{it.get('title') or ''}（{it.get('author') or ''}）{it.get('text') or ''}".strip()
               for it in research[:30]]
        parts.append("【机构调研纪要】\n" + "\n".join(blk))
    if not parts:
        return None
    material = "\n\n".join(parts)[:9000]

    system = (
        "你是A股首席策略分析师，擅长把隔夜外盘、财经快讯、公众号早报与机构调研纪要"
        "提炼成一份开盘前晨报。结论要具体、敢于点名板块与方向。"
    )
    user = (
        "以下是今日开盘前可参考的多源信息：\n\n" + material +
        "\n\n请输出一份开盘前晨报，严格分为三段，每段用下面的中文标签单独成行开头；"
        "标签之后每一条要点另起一行、以「· 」开头，按要点归纳、干练精炼、一目了然：\n"
        "【消息面】逐条列出今日最重要的消息/政策/数据与市场热点(重点参考财联社)，"
        "每条点明事件并指向受益板块/方向，列 5-8 条。\n"
        "【调研纪要】逐条列出机构关注的行业/个股主线与新增预期差，每条点名行业或个股，列 4-6 条。\n"
        "【操作建议】结合隔夜美股、消息面与调研纪要，逐条给出今日可执行的操作要点"
        "(方向、关注板块、参与节奏、风险点各成一条)，列 4-6 条。\n"
        "全文中文，每条要点一句话、直给结论、控制在 40 字内；只用「· 」作要点符号，"
        "不要数字编号、不要罗列原文出处、不要使用 * # 等 markdown 符号。"
    )
    text = await chat(system, user, max_tokens=1600, caller="morning_brief", timeout=60,
                      provider=_LLM_PROVIDER)
    return _parse_brief(text)


def _warm_brief() -> None:
    """后台收齐三类素材 → 一次 AI 汇总晨报正文并落库（当日缓存）。单飞 + 失败静默。"""
    global _brief_warming
    if _brief_warming:
        return

    async def _run():
        global _brief_warming
        try:
            from quantforge.data.storage import db_cache as _db
            ov = await _section_overnight_us()
            news = await asyncio.to_thread(_collect_morning_news)
            research = await asyncio.to_thread(_collect_research_overnight)
            ov_text = None
            if isinstance(ov, dict):
                ov_text = ov.get("analysis") or ov.get("title")
            brief = await _ai_morning_brief(ov_text, news, research)
            if brief:  # AI 失败(账号挂/超时)就不写缓存，下次再试，避免整天卡空
                await asyncio.to_thread(
                    _db.set, _brief_ck(),
                    {"brief": brief, "research_count": len(research)},
                    _AI_TTL, "morning")
        except Exception as exc:  # noqa: BLE001
            logger.debug("morning brief warm failed: %s", exc)
        finally:
            _brief_warming = False

    try:
        asyncio.create_task(_run())
        _brief_warming = True
    except RuntimeError:
        pass


async def _section_brief() -> dict[str, Any]:
    """晨报三部分：只读当日缓存（AI 汇总消息面/调研纪要/操作建议），没命中后台预热。"""
    cached = None
    try:
        from quantforge.data.storage import db_cache as _db
        cached = await asyncio.to_thread(_db.get, _brief_ck(), _AI_TTL)
    except Exception:  # noqa: BLE001
        cached = None
    if not isinstance(cached, dict):
        _warm_brief()
        return {"ok": True, "pending": True}
    brief = cached.get("brief") or {}
    return {
        "ok": True,
        "news": brief.get("news") or None,
        "research": brief.get("research") or None,
        "advice": brief.get("advice") or None,
        "research_count": cached.get("research_count", 0),
    }


# ── 历史快照存档（每日晨报/复盘留底，可回看）─────────────────────────────────
#
# 把当天「内容齐全」的整张报告 JSON 落进通用缓存表（category=daily_report_<kind>，
# key=report:<kind>:YYYY-MM-DD，超长 TTL ≈ 一年多）。回看历史日期时直接取存档，
# 不再重算。**自选板块是按用户私有的**，存档时剥离，避免不同用户互相覆盖。
# morning / review 共用这套，kind 区分。

_SNAP_TTL = 400 * 86400  # 存档约一年多
# 用户私有 / 实时探活，不入存档（watchlist_review = 复盘的自选股梳理，按用户私有）
_SNAP_DROP = ("watchlist", "holdings", "watchlist_review", "watchlist_risk", "data_health")


def _snap_key(kind: str, day: str) -> str:
    return f"report:{kind}:{day}"


def _snap_category(kind: str) -> str:
    return f"daily_report_{kind}"


def report_is_complete(payload: dict, kind: str = "review") -> bool:
    """这份报告是否「内容齐全」值得存档。

    晨报：三部分正文（操作建议/消息面）已生成即可；
    复盘：三部分正文（操作建议/盘面回顾）已生成即可。
    """
    if not isinstance(payload, dict):
        return False
    b = payload.get("brief")
    if kind == "morning":
        return bool(isinstance(b, dict) and b.get("ok")
                    and ((b.get("advice") or "").strip() or (b.get("news") or "").strip()))
    return bool(isinstance(b, dict) and b.get("ok")
                and ((b.get("advice") or "").strip() or (b.get("review") or "").strip()))


def save_snapshot(kind: str, payload: dict) -> None:
    """把一份完整报告快照落库存档（当天可被多次覆盖，最后一次为准）。best-effort。"""
    try:
        from quantforge.data.storage import db_cache as _db
        day = (payload.get("date") if isinstance(payload, dict) else None) or _today_str()
        snap = {k: v for k, v in payload.items() if k not in _SNAP_DROP}
        snap["archived"] = True
        _db.set(_snap_key(kind, day), snap, _SNAP_TTL, _snap_category(kind))
    except Exception as exc:  # noqa: BLE001
        logger.debug("save %s snapshot failed: %s", kind, exc)


def load_snapshot(kind: str, day: str) -> Optional[dict]:
    """取某天的报告存档（忽略 TTL，存了就给）。"""
    try:
        from quantforge.data.storage import db_cache as _db
        snap = _db.get_stale(_snap_key(kind, day))
        return snap if isinstance(snap, dict) else None
    except Exception:  # noqa: BLE001
        return None


def list_snapshots(kind: str) -> list[str]:
    """有存档的日期列表（降序）。"""
    try:
        from quantforge.data.storage import db_cache as _db
        rows = _db.list_by_category(_snap_category(kind))
        days = []
        for r in rows:
            d = str(r.get("key", "")).rsplit(":", 1)[-1]
            if len(d) == 10 and d[4] == "-":
                days.append(d)
        return sorted(set(days), reverse=True)
    except Exception:  # noqa: BLE001
        return []


def maybe_archive(kind: str, payload: dict) -> None:
    """报告内容齐全时异步落档（不阻塞响应）。"""
    if not report_is_complete(payload, kind):
        return
    try:
        asyncio.create_task(asyncio.to_thread(save_snapshot, kind, payload))
    except RuntimeError:
        pass


# ── 聚合接口 ──────────────────────────────────────────────────────────

@router.get("/history")
async def morning_history():
    """有存档的晨报日期列表（降序）。"""
    return {"dates": list_snapshots("morning")}


@router.get("/summary")
async def morning_summary(
    user: Optional[dict] = Depends(get_optional_user),
    strategy: str = "momentum",
    top_n: int = 10,
    day: Optional[str] = Query(None, alias="date"),
):
    """每日晨报：隔夜美股 + 三部分正文(消息面/调研纪要/操作建议) + 今日AI选股(动能买点)。

    带 ``?date=YYYY-MM-DD`` 且非今日时，直接返回该日存档（无存档则 empty）。
    """
    if day and day != _today_str():
        snap = load_snapshot("morning", day)
        if snap:
            return snap
        return {"date": day, "archived": True, "empty": True}

    # 隔夜美股(读图分析)与三部分正文都走「只读缓存+后台预热」，绝不在请求里现等 LLM。
    overnight, brief = await asyncio.gather(
        _safe(_section_overnight_us(), "overnight_us", {"ok": False}, timeout=10),
        _safe(_section_brief(), "brief", {"ok": False}, timeout=10),
    )
    payload = {
        "date": _today_str(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "overnight_us": overnight,
        "brief": brief,
        "picks": _section_picks(strategy, top_n),
    }
    maybe_archive("morning", payload)
    return payload


@router.post("/push")
async def morning_push(user: Optional[dict] = Depends(get_optional_user)):
    """把晨报摘要推送到已配置的通知渠道（微信 / Telegram 等）。"""
    try:
        from quantforge.notification.manager import NotificationManager
        ovn, br = await asyncio.gather(
            _safe(_section_overnight_us(), "overnight_us", {"ok": False}, timeout=10),
            _safe(_section_brief(), "brief", {"ok": False}, timeout=10),
        )
        pk = _section_picks()

        lines: list[str] = [f"📅 每日晨报 {date.today().isoformat()}"]

        # 隔夜美股
        if ovn.get("ok") and ovn.get("title"):
            lines.append(f"🌎 隔夜美股：{ovn['title']}")

        # 三部分正文
        if br.get("ok"):
            if br.get("news"):
                lines.append("一·消息面：")
                lines.append(f"　{br['news']}")
            if br.get("research"):
                lines.append("二·调研纪要：")
                lines.append(f"　{br['research']}")
            if br.get("advice"):
                lines.append("三·操作建议：")
                lines.append(f"　{br['advice']}")

        picks = pk.get("picks", []) if pk.get("ok") else []
        if picks:
            lines.append("🤖 今日AI选股（动能买点）：")
            for p in picks[:5]:
                nm = p.get("name") or p.get("symbol") or "?"
                rsn = p.get("reason") or p.get("one_liner") or ""
                lines.append(f"  · {nm} {str(rsn)[:30]}")

        title = f"每日晨报 {date.today().isoformat()}"
        body = "\n".join(lines)
        mgr = NotificationManager.from_settings()
        results = await mgr.notify(title, body)
        return {"ok": True, "pushed": [getattr(r, "__dict__", str(r)) for r in results]}
    except Exception as exc:
        logger.exception("morning push failed")
        return {"ok": False, "error": str(exc)}
