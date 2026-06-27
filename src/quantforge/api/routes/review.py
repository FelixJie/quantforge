"""每日复盘聚合接口（收盘视角）。

与「每日晨报」(:mod:`morning`) 对称：晨报是**开盘前**必看，复盘是**收盘后**回顾。
一屏聚合当日收盘后该看的东西，正文主体是**三段式**（一次 AI 产出）：

  一·盘面回顾 —— 公众号(纷传圈子) + 机构(知识星球) 今日复盘观点 + 收盘数据
  二·调研纪要 —— 「调研纪要」星球从今日收盘(15:00)到晚上 22:00 的全部纪要
  三·操作建议 —— 结合以上，对明日给出操作建议，**明确点名看好板块**

正文之外的结构化旁支（新增线索 / 龙虎榜 / 龙头股票 / 自选股梳理）见
:mod:`review_framework`。各板块独立兜底、并行抓取，单块失败/超时不拖垮整张复盘。
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from quantforge.api.routes.auth import get_optional_user
from quantforge.api.routes import morning

router = APIRouter(prefix="/review", tags=["review"])

logger = logging.getLogger("quantforge.api.review")


async def _section_margin() -> dict[str, Any]:
    """两市两融：复用 home/margin（最新余额 + 一年曲线）。"""
    from quantforge.api.routes.home import get_margin
    data = await get_margin()
    if not isinstance(data, dict):
        return {"ok": False}
    return {"ok": True, "items": data.get("items", []), "series": data.get("series", [])}


async def _section_hsgt() -> dict[str, Any]:
    """北向/南向资金：复用 market/hsgt（北向已停披露，主要看南向）。"""
    from quantforge.api.routes.market import get_hsgt
    data = await get_hsgt()
    channels = (data or {}).get("channels") or []
    south = [c for c in channels if c.get("direction") == "南向"
             and isinstance(c.get("net_buy"), (int, float))]
    south_net = sum(c["net_buy"] for c in south) if south else None
    return {"ok": True, "south_net": south_net, "channels": channels}


async def _section_limit() -> dict[str, Any]:
    """连板梯队 + 涨停情绪：复用 market/limit-pool。"""
    from quantforge.api.routes.market import get_limit_pool
    data = await get_limit_pool()
    if not isinstance(data, dict):
        return {"ok": False}
    return {
        "ok": True,
        "zt_count": data.get("zt_count"), "zb_count": data.get("zb_count"),
        "seal_rate": data.get("seal_rate"), "top_height": data.get("top_height"),
        "ladders": (data.get("ladders") or [])[:6],
    }


# ── 复盘正文三段（盘面回顾 / 调研纪要 / 操作建议·看好板块，一次 AI 汇总）──────────────
#
# 与晨报三段同构：把多源素材喂给一次 LLM，产出三段带标签正文。沿用「只读当日缓存 +
# 后台单飞预热」：冷缓存返回 pending，绝不在请求里现等 LLM。

_brief_warming = False


def _brief_ck() -> str:
    return f"review:brief_ai:{date.today().isoformat()}"


def _today_close() -> datetime:
    """今日收盘 15:00（调研纪要窗口起点：收盘到晚上 22:00）。"""
    t = date.today()
    return datetime(t.year, t.month, t.day, 15, 0, 0)


def _collect_research_after_close(limit: int = 40) -> list[dict]:
    """调研纪要素材：「调研纪要」星球从今日收盘(15:00)以来的帖子（标题 + 正文片段）。"""
    items: list[dict] = []
    try:
        from quantforge.data.storage import db_cache
        start = _today_close().isoformat()
        rows, _ = db_cache.blog_query(group_id=morning._GROUP_RESEARCH, page=1, page_size=80)
        for r in rows:
            if (r.get("created_at") or "") < start:
                continue  # 列表按时间降序，早于今日收盘的直接丢
            items.append({
                "author": r.get("author", ""),
                "title": r.get("ai_title") or r.get("title") or "",
                "text": (r.get("preview") or "")[:300],
            })
            if len(items) >= limit:
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("review research collect failed: %s", exc)
    return items


_BRIEF_LABELS = [("review", "盘面回顾"), ("research", "调研纪要"), ("advice", "操作建议")]


def _parse_brief(text: Optional[str]) -> Optional[dict]:
    """把带【盘面回顾】【调研纪要】【操作建议】标签的整段拆成三块。"""
    if not text:
        return None
    clean = text.replace("*", "").replace("#", "")
    labels = [lab for _, lab in _BRIEF_LABELS]
    pat = re.compile(r"[【\[]?(" + "|".join(labels) + r")[】\]]?[:：]?")
    matches = list(pat.finditer(clean))
    out = {k: "" for k, _ in _BRIEF_LABELS}
    if not matches:
        out["review"] = clean.strip()
        return out
    for i, m in enumerate(matches):
        seg_start = m.end()
        seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(clean)
        seg = clean[seg_start:seg_end].strip(" \n\r:：")
        key = next(k for k, l in _BRIEF_LABELS if l == m.group(1))
        if seg:
            out[key] = seg
    return out if any(out.values()) else None


def _market_brief_lines(market: dict, lhb: dict, limit: dict) -> list[str]:
    """把收盘数据压成几行喂给 AI 的盘面回顾素材。"""
    parts: list[str] = []
    dom = "、".join(
        f"{i.get('name')}{i.get('change_pct'):+.2f}%"
        for i in (market.get("domestic") or [])
        if isinstance(i.get("change_pct"), (int, float)))
    if dom:
        parts.append(f"今日收盘核心指数：{dom}")
    br = market.get("breadth") or {}
    if br.get("up_count") is not None:
        parts.append(f"涨跌家数：涨{br.get('up_count')}/跌{br.get('down_count')}；"
                     f"涨停{br.get('limit_up')}/跌停{br.get('limit_down')}")
    to = market.get("turnover") or {}
    if to.get("total_amount") is not None:
        parts.append(f"两市成交：{to['total_amount']}亿")
    lim = limit if isinstance(limit, dict) else (market.get("limit") or {})
    if lim.get("top_height"):
        parts.append(f"最高连板：{lim['top_height']}板，封板率{lim.get('seal_rate')}%")
        ladders = lim.get("ladders") or []
        tops = "；".join(
            f"{l.get('lianban')}板:" + " ".join(s.get("name", "") for s in (l.get("stocks") or [])[:4])
            for l in ladders[:3])
        if tops:
            parts.append(f"连板梯队：{tops}")
    lhb_bits = "、".join(
        f"{it.get('name')}(净{it.get('net'):+.1f}亿{'·机构' if it.get('is_inst') else ''})"
        for it in (lhb.get("items") or [])[:8]
        if isinstance(it.get("net"), (int, float)))
    if lhb_bits:
        parts.append(f"龙虎榜净买入居前：{lhb_bits}")
    return parts


async def _ai_review_brief(market: dict, lhb: dict, limit: dict,
                           web_posts: list[dict], research: list[dict]) -> Optional[dict]:
    """三段复盘正文：一次 AI 调用。best-effort，失败返回 None。"""
    from quantforge.api.ai_client import chat

    parts: list[str] = []
    parts.extend(_market_brief_lines(market, lhb, limit))
    if web_posts:
        blk = [f"·【{p.get('platform')}·{p.get('author') or '佚名'}】{p.get('title')}：{p.get('excerpt')}".strip()
               for p in web_posts[:14] if p.get("title") or p.get("excerpt")]
        if blk:
            parts.append("【财经网站/公众号/大V今日复盘观点】\n" + "\n".join(blk))
    if research:
        blk = [f"·{it.get('title') or ''}（{it.get('author') or ''}）{it.get('text') or ''}".strip()
               for it in research[:30]]
        parts.append("【今日收盘后机构调研纪要】\n" + "\n".join(blk))
    if not parts:
        return None
    material = "\n\n".join(parts)[:9000]

    system = (
        "你是A股首席策略分析师，擅长把收盘数据、各财经网站与大V复盘、机构调研纪要"
        "提炼成一份收盘后复盘。结论要具体、敢于点名板块与方向，不打太极。"
    )
    user = (
        "以下是今日收盘后可参考的多源信息：\n\n" + material +
        "\n\n请输出一份收盘后复盘，严格分为三段，每段用下面的中文标签单独成行开头；"
        "标签之后每一条要点另起一行、以「· 」开头，按要点归纳、干练精炼、一目了然：\n"
        "【盘面回顾】综合各财经网站与公众号的复盘观点 + 今日收盘数据，逐条回顾今日盘面"
        "(指数与情绪、资金主线、强弱分化、分歧点各成一条)，可点名板块，列 6-9 条。\n"
        "【调研纪要】逐条列出今日收盘到晚间机构关注的行业/个股主线与新增预期差，每条点名"
        "行业或个股，列 4-6 条；无纪要则一条说明暂无。\n"
        "【操作建议】结合盘面与调研纪要，逐条给出明日可执行的操作要点，"
        "**必须明确点名看好的板块/方向**，并把参与节奏、风险点各成一条，列 4-6 条。\n"
        "全文中文，每条要点一句话、直给结论、控制在 40 字内；只用「· 」作要点符号，"
        "不要数字编号、不要罗列原文出处、不要使用 * # 等 markdown 符号。"
    )
    text = await chat(system, user, max_tokens=1800, caller="review_brief", timeout=60,
                      provider=morning._LLM_PROVIDER)
    return _parse_brief(text)


def _warm_brief() -> None:
    """后台收齐多源素材 → 一次 AI 汇总复盘正文并落库（当日缓存）。单飞 + 失败静默。"""
    global _brief_warming
    if _brief_warming:
        return

    async def _run():
        global _brief_warming
        try:
            from quantforge.api.routes import review_framework as rf
            from quantforge.data.storage import db_cache as _db
            market = await morning._safe(morning._section_market(), "br_mk", {}, timeout=12)
            lhb = await morning._safe(rf._section_lhb(), "br_lhb", {}, timeout=16)
            limit = await morning._safe(_section_limit(), "br_limit", {}, timeout=10)
            web_posts = await asyncio.to_thread(rf._collect_review_posts, 16)
            research = await asyncio.to_thread(_collect_research_after_close)
            brief = await _ai_review_brief(
                market if isinstance(market, dict) else {},
                lhb if isinstance(lhb, dict) else {},
                limit if isinstance(limit, dict) else {},
                web_posts, research)
            if brief:  # AI 失败(账号挂/超时)就不写缓存，下次再试
                await asyncio.to_thread(
                    _db.set, _brief_ck(),
                    {"brief": brief, "research_count": len(research)},
                    morning._AI_TTL, "review")
        except Exception as exc:  # noqa: BLE001
            logger.debug("review brief warm failed: %s", exc)
        finally:
            _brief_warming = False

    try:
        asyncio.create_task(_run())
        _brief_warming = True
    except RuntimeError:
        pass


async def _section_brief() -> dict[str, Any]:
    """复盘三部分：只读当日缓存（AI 汇总盘面回顾/调研纪要/操作建议），没命中后台预热。"""
    cached = None
    try:
        from quantforge.data.storage import db_cache as _db
        cached = await asyncio.to_thread(_db.get, _brief_ck(), morning._AI_TTL)
    except Exception:  # noqa: BLE001
        cached = None
    if not isinstance(cached, dict):
        _warm_brief()
        return {"ok": True, "pending": True}
    brief = cached.get("brief") or {}
    return {
        "ok": True,
        "review": brief.get("review") or None,
        "research": brief.get("research") or None,
        "advice": brief.get("advice") or None,
        "research_count": cached.get("research_count", 0),
    }


@router.get("/history")
async def review_history():
    """有存档的复盘日期列表（降序）。"""
    return {"dates": morning.list_snapshots("review")}


@router.get("/summary")
async def review_summary(
    user: Optional[dict] = Depends(get_optional_user),
    day: Optional[str] = Query(None, alias="date"),
):
    """每日复盘：一屏聚合（收盘视角）。各板块独立兜底、并行抓取。

    带 ``?date=YYYY-MM-DD`` 且非今日时，直接返回该日存档（无存档则 empty）。
    """
    if day and day != date.today().isoformat():
        snap = morning.load_snapshot("review", day)
        if snap:
            return snap
        return {"date": day, "archived": True, "empty": True}

    from quantforge.api.routes import review_framework as rf

    (market, brief, clues, lhb, limit, hsgt, margin, watchlist, watchlist_risk) = await asyncio.gather(
        morning._safe(morning._section_market(), "market", {"ok": False}, timeout=12),
        morning._safe(_section_brief(), "brief", {"ok": False}, timeout=10),
        morning._safe(rf._section_clues(), "clues", {"ok": False}, timeout=10),
        morning._safe(rf._section_lhb(), "lhb", {"ok": False}, timeout=16),
        morning._safe(_section_limit(), "limit", {"ok": False}, timeout=10),
        morning._safe(_section_hsgt(), "hsgt", {"ok": False}, timeout=10),
        morning._safe(_section_margin(), "margin", {"ok": False}, timeout=12),
        morning._safe(rf._section_watchlist_review(user), "watchlist_review", {"ok": False}, timeout=12),
        morning._safe(rf._section_watchlist_risk(user), "watchlist_risk", {"ok": False}, timeout=16),
    )
    # 龙头依赖龙虎榜 + 连板，复用上面已取的结果，避免重复抓取
    dragons = await morning._safe(
        rf._section_dragons(lhb if isinstance(lhb, dict) else None,
                            limit if isinstance(limit, dict) else None),
        "dragons", {"ok": False}, timeout=10)

    payload = {
        "date": date.today().isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "market": market,            # 大盘收盘速览
        "brief": brief,              # 三段正文：盘面回顾 / 调研纪要 / 操作建议·看好板块
        "clues": clues,              # 新增线索（今日事件/订单/缺口 → 受益票，结构化）
        "lhb": lhb,                  # 龙虎榜（明细 + 机构净买排行 + 活跃营业部/游资）
        "dragons": dragons,          # 龙头股票
        "limit": limit,              # 连板梯队
        "hsgt": hsgt,                # 北向/南向
        "margin": margin,            # 两市两融
        "watchlist_review": watchlist,  # 自选股梳理（按用户，不入存档）
        "watchlist_risk": watchlist_risk,  # 自选股风险提示·技术面+消息面（按用户，不入存档）
        "verify": morning._section_verify(),  # 选股结算
    }
    morning.maybe_archive("review", payload)
    return payload


@router.post("/push")
async def review_push(user: Optional[dict] = Depends(get_optional_user)):
    """把复盘摘要推送到已配置的通知渠道。"""
    try:
        from quantforge.notification.manager import NotificationManager
        from quantforge.api.routes import review_framework as rf
        mk, br, wr = await asyncio.gather(
            morning._safe(morning._section_market(), "market", {"ok": False}, timeout=12),
            morning._safe(_section_brief(), "brief", {"ok": False}, timeout=10),
            morning._safe(rf._section_watchlist_risk(user), "watchlist_risk", {"ok": False}, timeout=16),
        )
        vf = morning._section_verify()

        lines: list[str] = [f"📕 每日复盘 {date.today().isoformat()}"]

        # 大盘收盘
        if mk.get("ok"):
            idx_bits = []
            for it in (mk.get("domestic") or [])[:4]:
                cp = it.get("change_pct")
                if cp is not None:
                    idx_bits.append(f"{it.get('name')} {cp:+.2f}%")
            if idx_bits:
                lines.append("📉 收盘：" + " ｜ ".join(idx_bits))
            br_b = mk.get("breadth") or {}
            to = mk.get("turnover") or {}
            extra = []
            if br_b.get("up_count") is not None:
                extra.append(f"涨{br_b['up_count']}/跌{br_b.get('down_count')}")
            if to.get("total_amount") is not None:
                extra.append(f"成交{to['total_amount']}亿")
            lim = mk.get("limit") or {}
            if lim.get("top_height"):
                extra.append(f"最高{lim['top_height']}板")
            if extra:
                lines.append("　" + "　".join(extra))

        # 三段正文
        if br.get("ok"):
            if br.get("review"):
                lines.append("🔍 盘面回顾：")
                lines.append(f"　{br['review']}")
            if br.get("advice"):
                lines.append("🎯 操作建议：")
                lines.append(f"　{br['advice']}")

        # 自选股风险提示（只推有风险信号的，最多 6 只）
        if wr.get("ok") and wr.get("items"):
            lines.append("⚠️ 自选股风险提示：")
            for r in wr["items"][:6]:
                bits = list(r.get("tech") or [])
                if r.get("news"):
                    bits.append("利空消息" + ("×%d" % len(r["news"]) if len(r["news"]) > 1 else ""))
                if bits:
                    lines.append(f"　[{r.get('level')}] {r.get('name')}：{'，'.join(bits)}")

        if vf.get("ok"):
            ov = vf.get("overall") or {}
            wr = ov.get("win_rate")
            if wr is not None:
                lines.append(f"📈 累计胜率：{wr}")

        title = f"每日复盘 {date.today().isoformat()}"
        body = "\n".join(lines)
        mgr = NotificationManager.from_settings()
        results = await mgr.notify(title, body)
        return {"ok": True, "pushed": [getattr(r, "__dict__", str(r)) for r in results]}
    except Exception as exc:
        logger.exception("review push failed")
        return {"ok": False, "error": str(exc)}


# ── 每日存档调度（无人访问也能留底）──────────────────────────────────────────
#
# 晨报早上 08:00 跑一遍，复盘晚上 22:00 跑一遍：先调一次 summary 触发各板块后台
# 预热（AI 正文/大V研判等异步落缓存），等一会儿再调一次——此时缓存已填好、内容
# 齐全，summary 内部 maybe_archive 即把当天整张报告落档。每块都各自兜底。

_MORNING_HM = (8, 0)    # 晨报固定早上 8:00 更新
_REVIEW_HM = (22, 0)    # 复盘固定晚上 22:00 更新


async def _capture(kind: str) -> None:
    """触发 + 等待预热 → 让 summary 自动落档。best-effort。"""
    fn = morning.morning_summary if kind == "morning" else review_summary
    try:
        await fn(user=None)          # 第一次：触发后台预热（返回 pending 不要紧）
        await asyncio.sleep(150)     # 给 LLM 正文/研判留出预热时间
        await fn(user=None)          # 第二次：缓存已填，summary 内部 maybe_archive 落档
    except Exception as exc:  # noqa: BLE001
        logger.debug("daily report capture(%s) failed: %s", kind, exc)


def _seconds_until(hour: int, minute: int) -> float:
    now = datetime.now()
    nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


async def daily_snapshot_scheduler() -> None:
    """盘前晨报、盘后复盘各自定时存档；启动时补一次当天缺失的存档。"""
    await asyncio.sleep(45)  # 让启动其它预热先跑
    today = date.today().isoformat()
    try:
        if not morning.load_snapshot("morning", today):
            await _capture("morning")
        if not morning.load_snapshot("review", today):
            await _capture("review")
    except Exception as exc:  # noqa: BLE001
        logger.debug("daily report startup backfill failed: %s", exc)

    while True:
        m_wait = _seconds_until(*_MORNING_HM)
        r_wait = _seconds_until(*_REVIEW_HM)
        if m_wait <= r_wait:
            await asyncio.sleep(max(60, m_wait))
            await _capture("morning")
        else:
            await asyncio.sleep(max(60, r_wait))
            await _capture("review")
