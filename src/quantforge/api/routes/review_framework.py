"""每日复盘的结构化板块（收盘视角）。

复盘正文主体（盘面回顾 / 调研纪要 / 操作建议）在 :mod:`review` 里以「三段式」一次
AI 产出；本模块只提供**结构化、纯计算/抓取**的旁支板块，零 LLM、即时可见：

  - 龙虎榜     —— 东财每日明细 + **机构净买排行** + **今日活跃营业部(知名游资标注)**。
  - 龙头股票   —— 连板梯队最高板个股 + 龙虎榜净买入龙头。
  - 自选股梳理 —— 自选股当日表现 + 已登记成本的盈亏（按用户，结构化直出）。

另提供 `_collect_review_posts`（纷传圈子 + 知识星球今日复盘帖），供 review 的三段正文
「盘面回顾」取「财经网站/公众号复盘观点」素材用。

各板块独立兜底，单源失败不拖垮整张复盘。
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from datetime import date
from typing import Any, Optional

import requests

from quantforge.api.routes import morning, review

logger = logging.getLogger("quantforge.api.review_framework")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
}


# ── 龙虎榜（东财每日明细 + 机构净买排行 + 活跃营业部 / 游资标注）─────────────────────
_EM_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# 知名游资营业部关键词 → 游资别名（按营业部名子串匹配，标注「席位」用）。
# 子串越靠前越优先匹配；尽量用足够区分度的子串避免误标。
_KNOWN_HOTMONEY = {
    # —— 顶级游资 / 知名席位 ——
    "宁波桑田路": "宁波桑田路(章盟主)",
    "宁波江东北路": "宁波江东北路",
    "上海江苏路": "上海江苏路(作手新一)",
    "中国银河绍兴": "银河绍兴(赵老哥)",
    "杭州上塘路": "杭州上塘路(赵老哥系)",
    "上海溧阳路": "中信上海溧阳路",
    "宁波解放南路": "宁波解放南路(敢死队)",
    "光大证券宁波": "光大宁波(敢死队)",
    "益田路荣超": "华泰深圳益田路",
    "招商证券深圳益田路": "招商深圳益田路",
    "深圳泰然九路": "国信深圳泰然九路",
    "上海东方路": "中信建投上海东方路",
    "上海武定路": "华泰上海武定路",
    "北京安立路": "中信建投北京安立路",
    "南京太平南路": "国君南京太平南路",
    "成都北一环路": "成都北一环路",
    "深圳红岭中路": "深圳红岭中路",
    "杭州九环路": "杭州九环路",
    "梅州梅水路": "方正梅州梅水路",
    "华鑫证券上海分公司": "华鑫上海(量化/炒新)",
    "东亚前海": "东亚前海(量化)",
    "国金证券上海互联网": "国金量化",
    # —— 东财拉萨系（散户/量化大本营，区分各路）——
    "拉萨团结路第二": "东财拉萨(赵老哥系)",
    "拉萨东环路第二": "东财拉萨二(方新侠系)",
    "拉萨团结路第一": "东财拉萨一",
    "拉萨东环路第一": "东财拉萨",
    "拉萨金珠西路": "东财拉萨",
    "拉萨北京西路": "东财拉萨",
    "东方财富拉萨": "东财拉萨(量化/游资)",
    # —— 人名直标 ——
    "陈小群": "陈小群",
    "孙哥": "孙哥",
    "量化": "量化席位",
}


def _tag_hotmoney(dept_name: str) -> Optional[str]:
    for kw, alias in _KNOWN_HOTMONEY.items():
        if kw in dept_name:
            return alias
    return None


def _em_query(report: str, sort_col: str, page_size: int, trade_date: Optional[str] = None,
              date_field: str = "TRADE_DATE") -> list[dict]:
    params = {
        "reportName": report, "columns": "ALL", "source": "WEB", "client": "WEB",
        "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_col, "sortTypes": "-1",
    }
    if trade_date:
        params["filter"] = f"({date_field}='{trade_date}')"
    r = requests.get(_EM_URL, params=params, headers=_HEADERS, timeout=12)
    r.raise_for_status()
    return ((r.json() or {}).get("result") or {}).get("data") or []


def _yi(v) -> Optional[float]:
    return round(v / 1e8, 2) if isinstance(v, (int, float)) else None


def _fetch_lhb(limit: int = 60) -> dict:
    """东财龙虎榜每日明细：取最近有数据的交易日，按净买入额降序。"""
    rows: list[dict] = []
    used_date = ""
    try:
        for back in range(0, 7):
            d = (date.today() - _dt.timedelta(days=back)).isoformat()
            rows = _em_query("RPT_DAILYBILLBOARD_DETAILS", "BILLBOARD_NET_AMT", 120, d)
            if rows:
                used_date = d
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("lhb fetch failed: %s", exc)
        return {"ok": False, "date": "", "items": [], "inst_count": 0}

    items: list[dict] = []
    inst_count = 0
    for it in rows:
        explain = str(it.get("EXPLAIN") or "")
        is_inst = "机构" in explain
        if is_inst:
            inst_count += 1
        items.append({
            "name": it.get("SECURITY_NAME_ABBR"),
            "code": it.get("SECURITY_CODE"),
            "close": it.get("CLOSE_PRICE"),
            "change_pct": round(it["CHANGE_RATE"], 2) if isinstance(it.get("CHANGE_RATE"), (int, float)) else None,
            "net": _yi(it.get("BILLBOARD_NET_AMT")),
            "buy": _yi(it.get("BILLBOARD_BUY_AMT")),
            "sell": _yi(it.get("BILLBOARD_SELL_AMT")),
            "turnover_rate": round(it["TURNOVERRATE"], 2) if isinstance(it.get("TURNOVERRATE"), (int, float)) else None,
            "reason": str(it.get("EXPLANATION") or ""),
            "explain": explain,
            "is_inst": is_inst,
        })
    # 机构净买排行：上榜原因含「机构」且净额为正，按净额降序。
    inst_rank = sorted(
        [it for it in items if it.get("is_inst") and isinstance(it.get("net"), (int, float)) and it["net"] > 0],
        key=lambda x: x["net"], reverse=True)[:8]
    return {"ok": True, "date": used_date, "items": items[:limit],
            "inst_count": inst_count, "total": len(rows), "inst_rank": inst_rank}


def _fetch_active_depts(limit: int = 20) -> dict:
    """东财每日活跃营业部：最近有数据的交易日，按净额降序，标注知名游资席位。

    返回 `depts`（按净额降序的活跃营业部）与 `hotmoney`（仅命中知名游资别名的席位，
    供「知名游资今日动向」单列高亮）。为多捞游资席位，扫描比 limit 更深一截再筛。
    """
    rows: list[dict] = []
    used_date = ""
    try:
        for back in range(0, 7):
            d = (date.today() - _dt.timedelta(days=back)).isoformat() + " 00:00:00"
            rows = _em_query("RPT_OPERATEDEPT_ACTIVE", "TOTAL_NETAMT", 120, d, date_field="ONLIST_DATE")
            if rows:
                used_date = d[:10]
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("active depts fetch failed: %s", exc)
        return {"ok": False, "date": "", "depts": [], "hotmoney": []}

    all_depts: list[dict] = []
    for it in rows:
        name = str(it.get("OPERATEDEPT_NAME") or "")
        if not name:
            continue
        stocks = str(it.get("SECURITY_NAME_ABBR") or "").split()
        all_depts.append({
            "name": name.replace("证券股份有限公司", "").replace("股份有限公司", ""),
            "full_name": name,
            "net": _yi(it.get("TOTAL_NETAMT")),
            "buy_appear": it.get("BUYER_APPEAR_NUM"),
            "sell_appear": it.get("SELLER_APPEAR_NUM"),
            "stocks": stocks[:6],
            "hotmoney": _tag_hotmoney(name),
        })
    # 知名游资单列（净额绝对值降序，买卖两端都算「动向」），从全量里筛而非只看前列。
    hotmoney = sorted(
        [d for d in all_depts if d["hotmoney"]],
        key=lambda x: abs(x["net"]) if isinstance(x["net"], (int, float)) else 0,
        reverse=True)[:15]
    return {"ok": True, "date": used_date, "depts": all_depts[:limit], "hotmoney": hotmoney}


async def _section_lhb() -> dict[str, Any]:
    lhb, depts = await asyncio.gather(
        asyncio.to_thread(_fetch_lhb, 60),
        morning._safe(asyncio.to_thread(_fetch_active_depts, 20), "active_depts", {"ok": False}, timeout=14),
    )
    if isinstance(lhb, dict) and isinstance(depts, dict) and depts.get("ok"):
        lhb["active_depts"] = depts.get("depts") or []
        lhb["hotmoney"] = depts.get("hotmoney") or []
        lhb["depts_date"] = depts.get("date")
    return lhb


# ── 龙头股票（连板梯队最高板 + 龙虎榜净买入龙头）──────────────────────────────────
async def _section_dragons(lhb: Optional[dict] = None,
                           limit: Optional[dict] = None) -> dict[str, Any]:
    if limit is None:
        limit = await morning._safe(review._section_limit(), "rf_limit2", {}, timeout=10)
    if lhb is None:
        lhb = await _section_lhb()

    leaders: list[dict] = []
    seen: set[str] = set()

    ladders = (limit.get("ladders") or []) if isinstance(limit, dict) else []
    for ld in ladders[:2]:
        lb = ld.get("lianban")
        for s in (ld.get("stocks") or [])[:4]:
            code = str(s.get("code") or "")
            if code and code not in seen:
                seen.add(code)
                leaders.append({
                    "name": s.get("name"), "code": code,
                    "tag": f"{lb}板", "reason": "连板梯队高度龙头",
                })

    for it in (lhb.get("items") or []) if isinstance(lhb, dict) else []:
        code = str(it.get("code") or "")
        if not code or code in seen:
            continue
        if isinstance(it.get("net"), (int, float)) and it["net"] > 0:
            seen.add(code)
            tag = "机构买入" if it.get("is_inst") else "游资净买"
            leaders.append({
                "name": it.get("name"), "code": code, "tag": tag,
                "reason": f"龙虎榜净买入 {it['net']:+.1f}亿",
            })
        if len(leaders) >= 12:
            break

    return {"ok": True, "leaders": leaders[:12]}


# ── 自选股梳理（自选当日表现 + 已登记成本的盈亏）──────────────────────────────────
async def _section_watchlist_review(user: Optional[dict]) -> dict[str, Any]:
    if not user:
        return {"ok": True, "items": [], "totals": None, "note": "未登录"}
    try:
        from quantforge.api.routes.watchlist import get_watchlist_overview
        payload = await get_watchlist_overview(user)
        raw = payload.get("items", []) if isinstance(payload, dict) else []
    except Exception as exc:  # noqa: BLE001
        logger.debug("watchlist review section failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    out: list[dict] = []
    tot_cost = tot_mv = tot_pnl = 0.0
    has_pos = False
    for it in raw:
        price = it.get("price")
        cost = it.get("cost_price")
        shares = it.get("shares")
        row = {
            "name": it.get("name") or it.get("code"), "code": it.get("code"),
            "price": price, "change_pct": it.get("change_pct"),
            "cost_price": None, "pnl_pct": None, "market_value": None, "pnl": None,
        }
        if (isinstance(cost, (int, float)) and cost > 0
                and isinstance(shares, (int, float)) and shares > 0
                and isinstance(price, (int, float)) and price > 0):
            has_pos = True
            mv = price * shares
            pnl = mv - cost * shares
            tot_cost += cost * shares
            tot_mv += mv
            tot_pnl += pnl
            row.update({"cost_price": round(cost, 3),
                        "pnl_pct": round((price / cost - 1) * 100, 2),
                        "market_value": round(mv, 2), "pnl": round(pnl, 2)})
        out.append(row)

    # 排序：先按当日涨跌幅降序（自选当日表现一目了然），无行情的沉底。
    out.sort(key=lambda x: (x.get("change_pct") is None, -(x.get("change_pct") or 0)))
    totals = None
    if has_pos and tot_cost > 0:
        totals = {
            "cost": round(tot_cost, 2), "market_value": round(tot_mv, 2),
            "pnl": round(tot_pnl, 2),
            "pnl_pct": round((tot_mv / tot_cost - 1) * 100, 2),
        }
    return {"ok": True, "items": out, "totals": totals, "count": len(out)}


# ── 自选股风险提示（技术面 + 消息面，纯规则结构化）────────────────────────────────────
#
# 复盘收盘后，对自选股逐只做一次「风险体检」：
#   · 技术面 —— 读本地日线(自选已预热)，规则识别跌破均线/空头排列/高位累涨/急跌/
#               放量杀跌/RSI 超买等技术风险；零网络、即时可见。
#   · 消息面 —— 复用个股资讯流(news._wl_one_stock_news，15min 缓存)，命中利空关键词或
#               负面情绪的近期新闻/公告即作消息面风险，整体限时兜底，超时则只出技术面。
# 只输出**确有风险信号**的个股(无信号不刷屏)，按风险条数(高→低)排序。按用户、不入存档。

# 消息面利空关键词：标题/正文命中才视为风险信号（公告/快讯）。
# 风险面板重精度——只认明确利空词，不用「负面情绪」泛判，避免泛市场快讯混入。
_RISK_NEWS_KW = [
    "减持", "拟减持", "质押", "平仓", "问询", "关注函", "监管函", "立案", "处罚",
    "诉讼", "仲裁", "业绩预减", "业绩预亏", "预亏", "由盈转亏", "下修", "解禁", "限售",
    "商誉减值", "计提", "退市", "*ST", "风险警示", "下调评级", "评级下调",
    "终止", "违规", "被查", "冻结", "失信", "造假", "举牌",
    "跌停", "闪崩", "暴跌", "重挫", "破发", "爆雷", "踩雷",
]


def _rsi_last(closes: list[float], period: int = 14) -> Optional[float]:
    """最近一根 RSI（简化版，够用于「超买」判定）。"""
    if len(closes) <= period:
        return None
    gains = losses = 0.0
    for i in range(-period, 0):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return round(100 - 100 / (1 + rs), 1)


def _norm6(code: str) -> str:
    """去掉交易所前缀(SH/SZ/BJ)取 6 位代码——个股日线表按 6 位代码入库。"""
    c = (code or "").strip().upper()
    for p in ("SH", "SZ", "BJ"):
        if c.startswith(p):
            return c[2:]
    return c


def _tech_risk(code: str) -> list[str]:
    """从本地日线提炼技术面风险标签（无风险返回空列表）。"""
    try:
        from quantforge.data.storage import db_cache
        bars = db_cache.kline_load(_norm6(code), "day", 90) or []
    except Exception:  # noqa: BLE001
        bars = []
    closes = [float(b["close"]) for b in bars if b.get("close") is not None]
    highs = [float(b["high"]) for b in bars if b.get("high") is not None]
    lows = [float(b["low"]) for b in bars if b.get("low") is not None]
    vols = [float(b["volume"]) for b in bars if b.get("volume") is not None]
    if len(closes) < 20:
        return []

    def _ma(n: int) -> Optional[float]:
        return sum(closes[-n:]) / n if len(closes) >= n else None

    def _ret(n: int) -> Optional[float]:
        return (closes[-1] / closes[-1 - n] - 1) * 100 if len(closes) > n else None

    flags: list[str] = []
    last = closes[-1]
    prev = closes[-2] if len(closes) >= 2 else last
    ma5, ma20, ma60 = _ma(5), _ma(20), _ma(60)

    # 跌破关键均线（昨日还在上方→今日刚破位，最值得提示）
    if ma20 and last < ma20:
        flags.append("跌破20日线" + ("(今日新破)" if prev >= ma20 else ""))
    if ma60 and last < ma60:
        flags.append("跌破60日生命线" + ("(今日新破)" if prev >= ma60 else ""))
    # 均线空头排列
    if ma5 and ma20 and ma60 and ma5 < ma20 < ma60:
        flags.append("均线空头排列")
    # 短期急跌
    r5 = _ret(5)
    if r5 is not None and r5 <= -8:
        flags.append(f"5日急跌{r5:.0f}%")
    # 高位累涨过大（20日分位高 + 区间涨幅大 → 回调风险）
    w, v = highs[-20:], lows[-20:]
    if w and v and max(w) > min(v):
        pos20 = (last - min(v)) / (max(w) - min(v)) * 100
        r20 = _ret(20)
        if pos20 >= 88 and r20 is not None and r20 >= 25:
            flags.append(f"高位累涨{r20:.0f}%，注意回调")
    # 放量杀跌（今日跌幅明显 + 量能放大 → 资金出逃）
    if len(closes) >= 6 and len(vols) >= 6:
        today_chg = (last / prev - 1) * 100 if prev else 0.0
        avg5 = sum(vols[-6:-1]) / 5
        if today_chg <= -3 and avg5 and vols[-1] >= 1.8 * avg5:
            flags.append("放量杀跌")
    # RSI 超买
    rsi = _rsi_last(closes)
    if rsi is not None and rsi >= 80:
        flags.append(f"RSI超买({rsi:.0f})")

    return flags


def _news_risk(news_items: list[dict]) -> list[dict]:
    """从个股近期资讯里挑出利空信号（命中关键词或负面情绪），返回 [{title,date}]。"""
    cut = (_dt.date.today() - _dt.timedelta(days=7)).isoformat()
    hits: list[dict] = []
    seen: set[str] = set()
    for it in news_items or []:
        title = (it.get("title") or "").strip()
        if not title or (it.get("date") or "") < cut:
            continue
        text = title + (it.get("content") or "")
        if not any(kw in text for kw in _RISK_NEWS_KW):
            continue
        key = title[:24]
        if key in seen:
            continue
        seen.add(key)
        hits.append({"title": title[:48], "date": it.get("date") or ""})
        if len(hits) >= 3:
            break
    return hits


async def _section_watchlist_risk(user: Optional[dict]) -> dict[str, Any]:
    """自选股风险提示：技术面(本地日线规则) + 消息面(近期利空资讯)，只列有风险信号的。"""
    if not user:
        return {"ok": True, "items": [], "note": "未登录"}
    try:
        from quantforge.api.routes.watchlist import get_watchlist_overview
        payload = await get_watchlist_overview(user)
        raw = payload.get("items", []) if isinstance(payload, dict) else []
    except Exception as exc:  # noqa: BLE001
        logger.debug("watchlist risk overview failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    codes = [(it.get("code"), it.get("name") or it.get("code"),
              it.get("price"), it.get("change_pct"), it.get("cost_price"))
             for it in raw if it.get("code")][:30]
    if not codes:
        return {"ok": True, "items": [], "count": 0, "checked": 0}

    # 技术面：本地日线，纯计算并发（线程池）。
    tech_flags = await asyncio.gather(
        *[asyncio.to_thread(_tech_risk, c[0]) for c in codes])

    # 消息面：复用个股资讯流(各 15min 缓存、并发 6)，整体限时兜底；超时则只出技术面。
    news_map: dict[str, list[dict]] = {}
    try:
        from quantforge.api.routes import news as news_mod
        sem = asyncio.Semaphore(6)

        async def _one(code: str):
            async with sem:
                try:
                    return code, await news_mod._wl_one_stock_news(code, 8)
                except Exception:  # noqa: BLE001
                    return code, []

        results = await asyncio.wait_for(
            asyncio.gather(*[_one(c[0]) for c in codes]), timeout=12)
        for code, items in results:
            risk = _news_risk(items)
            if risk:
                news_map[code] = risk
    except Exception as exc:  # noqa: BLE001
        logger.debug("watchlist risk news degraded (tech-only): %s", exc)

    out: list[dict] = []
    for (code, name, price, chg, cost), flags in zip(codes, tech_flags):
        news_hits = news_map.get(code) or []
        tech = list(flags)
        # 跌破登记成本价也作技术面风险补充
        if (isinstance(cost, (int, float)) and cost > 0
                and isinstance(price, (int, float)) and price > 0 and price < cost):
            tech.append(f"已跌破成本{(price / cost - 1) * 100:.0f}%")
        if not tech and not news_hits:
            continue
        score = len(tech) + len(news_hits) + (1 if news_hits else 0)
        level = "高" if score >= 3 else ("中" if score >= 2 else "低")
        out.append({
            "code": code, "name": name, "price": price, "change_pct": chg,
            "level": level, "tech": tech, "news": news_hits,
        })

    # 风险高→低排序（信号多的在前），一眼看最该警惕的。
    rank = {"高": 0, "中": 1, "低": 2}
    out.sort(key=lambda x: (rank.get(x["level"], 3),
                            -(len(x["tech"]) + len(x["news"]))))
    return {"ok": True, "items": out, "count": len(out), "checked": len(codes)}


# ── 复盘正文「盘面回顾」素材：今日财经复盘帖（纷传圈子 + 知识星球）────────────────────
#
# 复盘三段正文的第一段需要「多财经网站/公众号的复盘观点」。雪球/微博/韭研等平台无
# 稳定免登录通路，已不再接入；这里只汇总**确实能抓到**的两类今日复盘帖喂给 AI。
_ZSXQ_URL = "https://wx.zsxq.com/dweb2/index/topic_detail/{}"


def _collect_review_posts(limit: int = 16) -> list[dict]:
    """汇总今日复盘类帖：公众号(纷传圈子) + 机构(知识星球)。纯本地读缓存/库、零网络。"""
    posts: list[dict] = []

    # 1) 公众号（纷传圈子）今日复盘类帖
    try:
        from quantforge.api.routes import fenchuan
        snap = fenchuan._load_cache()
        for p in (snap.get("posts") or []):
            if p.get("is_top") or not morning._is_today(p.get("time", "")):
                continue
            text = (p.get("text") or "").strip()
            if not morning._hit_review_kw(p.get("title", ""), text):
                continue
            posts.append({
                "platform": "公众号圈子", "author": p.get("author") or "",
                "title": (p.get("title") or "")[:60] or text[:30],
                "excerpt": text[:140], "url": p.get("url") or "", "time": p.get("time") or "",
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug("review posts fenchuan collect failed: %s", exc)

    # 2) 机构（知识星球）今日复盘类帖
    try:
        from quantforge.data.storage import db_cache
        rows, _ = db_cache.blog_query(page=1, page_size=60)
        for r in rows:
            if not morning._is_today(r.get("created_at", "")):
                continue
            title = r.get("ai_title") or r.get("title") or ""
            preview = r.get("preview", "")
            if not morning._hit_review_kw(title, preview):
                continue
            pid = r.get("post_id")
            posts.append({
                "platform": "知识星球", "author": r.get("author") or "",
                "title": (title or preview[:30])[:60], "excerpt": (preview or "")[:140],
                "url": _ZSXQ_URL.format(pid) if pid else "", "time": r.get("created_at") or "",
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug("review posts blog collect failed: %s", exc)

    return posts[:limit]


# ── 新增线索（今日新增事件 / 订单中标 / 涨价缺口 / 新产品 → 受益票，结构化抽取）────────────
#
# 区别于「调研纪要」那段散文：这里把今日新增的研报标题/纪要/快讯喂给一次 AI，**抽取成结构
# 化条目**——每条 = 事件 + 利好逻辑 + 受益票(名+码) + 出处，按用户最关心的维度分桶（订单/缺口
# /新品/政策）。AI 只输出股票**简称**，代码由本地股名缓存反查（规避代码幻觉）。沿用「只读
# 当日缓存 + 后台单飞预热」：冷缓存返回 pending，绝不在请求里现等 LLM。

_clues_warming = False
_CLUE_TYPES = ["订单中标", "涨价缺口", "新产品", "政策事件", "其他"]


def _clues_ck() -> str:
    return f"review:clues_ai:{date.today().isoformat()}"


def _latest_report_date(items: list[dict]) -> str:
    """取一批(降序)研报里最新的 publish_date：今天有就用今天，否则回退到最近一天。

    研报按天批量入库，东财常滞后一天（晚上看复盘时今天那批可能还没灌）。用「今天 or
    库里最新一天」而非死磕今天，订单/缺口类催化才不会因当天没灌就整段空着。
    """
    today = date.today().isoformat()
    dates = {(r.get("publish_date") or "") for r in items}
    if today in dates:
        return today
    return max((d for d in dates if d), default=today)


def _collect_today_reports(limit: int = 80) -> tuple[list[dict], list[dict]]:
    """个股研报(自带 code，配股名) + 行业研报标题，取「今天 or 库里最新一天」作线索素材。"""
    from quantforge.data.storage import db_cache, stock_meta_cache
    stock_items: list[dict] = []
    ind_items: list[dict] = []
    try:
        items = db_cache.reports_list(page=1, page_size=150, days=4).get("items", [])
        target = _latest_report_date(items)
        for r in items:
            if (r.get("publish_date") or "") != target:
                continue
            code = r.get("code") or ""
            stock_items.append({
                "code": code,
                "name": stock_meta_cache.get_name(code) or "",
                "title": r.get("title") or "",
                "org": r.get("org") or "",
            })
            if len(stock_items) >= limit:
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("clues stock-reports collect failed: %s", exc)
    try:
        items = db_cache.industry_reports_list(page=1, page_size=120).get("items", [])
        target = _latest_report_date(items)
        for r in items:
            if (r.get("publish_date") or "") != target:
                continue
            ind_items.append({
                "industry": r.get("industry_name") or "",
                "title": r.get("title") or "",
                "org": r.get("org") or "",
            })
            if len(ind_items) >= 40:
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("clues industry-reports collect failed: %s", exc)
    return stock_items, ind_items


def _collect_flash_titles(limit: int = 40) -> list[str]:
    """今日财经快讯标题（含简短正文），事件/订单/涨价类硬催化的来源之一。"""
    out: list[str] = []
    try:
        from quantforge.api.routes import news
        for it in news._fetch_flash(limit):
            t = (it.get("title") or "").strip()
            c = (it.get("content") or "").strip()
            txt = (t + " " + c).strip()[:120] if c else t
            if txt:
                out.append(txt)
    except Exception as exc:  # noqa: BLE001
        logger.debug("clues flash collect failed: %s", exc)
    return out


def _resolve_codes(names: list[str]) -> list[dict]:
    """股票简称 → {name, code}，code 由本地股名缓存反查（缺失留空，不编造）。"""
    try:
        from quantforge.data.storage import stock_meta_cache
        rev = {v: k for k, v in stock_meta_cache.get_all_names().items() if v}
    except Exception:  # noqa: BLE001
        rev = {}
    out: list[dict] = []
    seen: set[str] = set()
    for nm in names:
        nm = (nm or "").strip()
        if not nm or nm in seen:
            continue
        seen.add(nm)
        out.append({"name": nm, "code": rev.get(nm, "")})
    return out


async def _ai_extract_clues(stock_reports: list[dict], ind_reports: list[dict],
                            research: list[dict], news: list[str]) -> list[dict]:
    """把今日新增素材抽取成结构化线索条目。best-effort，失败抛出由调用方静默。"""
    from quantforge.api.ai_client import chat
    from quantforge.api.research_helpers import _loads_lenient

    parts: list[str] = []
    if stock_reports:
        blk = [f"·{r['name']}({r['code']})｜{r['title']}（{r.get('org') or ''}）"
               for r in stock_reports if r.get("title")]
        if blk:
            parts.append("【今日个股研报标题】\n" + "\n".join(blk[:60]))
    if ind_reports:
        blk = [f"·[{r.get('industry') or ''}] {r['title']}（{r.get('org') or ''}）"
               for r in ind_reports if r.get("title")]
        if blk:
            parts.append("【今日行业研报标题】\n" + "\n".join(blk[:30]))
    if research:
        blk = [f"·{it.get('title') or ''} {it.get('text') or ''}".strip()
               for it in research[:20] if (it.get('title') or it.get('text'))]
        if blk:
            parts.append("【今日收盘后机构调研纪要】\n" + "\n".join(blk))
    if news:
        parts.append("【今日财经快讯】\n" + "\n".join(f"·{n}" for n in news[:40]))
    if not parts:
        return []
    material = "\n\n".join(parts)[:11000]

    system = (
        "你是A股事件驱动分析师，专挑'新增'的硬催化：新签订单/中标、产品涨价/供需缺口、"
        "新品量产/技术突破/客户导入、政策招标补贴。你只认有明确受益上市公司的实质性事件，"
        "对宽泛观点、复盘感想、历史回顾一律忽略。"
    )
    user = (
        "以下是今日新增的研报标题、机构调研纪要与财经快讯：\n\n" + material +
        "\n\n请从中抽取**今日新增**的事件型线索，输出一个 JSON 数组，每个元素形如：\n"
        '{"type":"订单中标","event":"一句话事件（含主体）","logic":"为何利好（尽量带具体数字：'
        '订单金额/涨价幅度/缺口比例）","stocks":["受益股简称1","受益股简称2"],"source":"研报|纪要|快讯"}\n'
        "要求：\n"
        "1. type 只能取以下之一，按口径归类（拿不准时优先归入更具体的非'其他'桶）：\n"
        "   · 订单中标 = 新签订单/中标/框架协议/大单；\n"
        "   · 涨价缺口 = 产品涨价/提价/缺货/供需缺口/产能紧缺/出口限制/限产带来的价格弹性；\n"
        "   · 新产品 = 新品送样/量产/技术突破/客户导入/新车型新机型；\n"
        "   · 政策事件 = 政策出台/招标/补贴/规划/预警等外部催化；\n"
        "   · 其他 = 实在无法归入上述四类的实质催化；\n"
        "2. stocks 只填A股**股票简称**（如\"贵州茅台\"），**绝不要编股票代码**；没有明确受益个股的线索直接丢弃；\n"
        "3. event/logic 要具体，logic 优先给出金额/涨价幅度/供需缺口等量化信息；\n"
        "4. 只保留今日新增的实质催化，最多 12 条，重要的排前面；\n"
        "5. 只输出 JSON 数组本身，不要任何额外文字、不要 markdown 代码块标记。"
    )
    text = await chat(system, user, max_tokens=1800, caller="review_clues", timeout=180,
                      provider=morning._LLM_PROVIDER)
    data = _loads_lenient(text)
    raw_list = data if isinstance(data, list) else (
        data.get("clues") if isinstance(data, dict) else [])
    clues: list[dict] = []
    for c in raw_list or []:
        if not isinstance(c, dict):
            continue
        names = c.get("stocks") or []
        if isinstance(names, str):
            names = [names]
        stocks = _resolve_codes([str(n) for n in names])
        typ = c.get("type") or "其他"
        if typ not in _CLUE_TYPES:
            typ = "其他"
        event = (c.get("event") or "").strip()
        if not event or not stocks:
            continue
        clues.append({
            "type": typ,
            "event": event,
            "logic": (c.get("logic") or "").strip(),
            "stocks": stocks,
            "source": (c.get("source") or "").strip(),
        })
    return clues[:12]


def _warm_clues() -> None:
    """后台收齐今日新增素材 → 一次 AI 抽取结构化线索并落库（当日缓存）。单飞 + 失败静默。"""
    global _clues_warming
    if _clues_warming:
        return

    async def _run():
        global _clues_warming
        try:
            from quantforge.data.storage import db_cache as _db
            # 各采集器独立兜底+超时：快讯源(news._fetch_flash)偶发卡死，决不能堵死整个 warm。
            reports = await morning._safe(
                asyncio.to_thread(_collect_today_reports), "clues_reports", ([], []), timeout=12)
            stock_reports, ind_reports = reports if isinstance(reports, tuple) else ([], [])
            research = await morning._safe(
                asyncio.to_thread(review._collect_research_after_close), "clues_research", [], timeout=10)
            flash = await morning._safe(
                asyncio.to_thread(_collect_flash_titles), "clues_flash", [], timeout=15)
            clues = await _ai_extract_clues(stock_reports, ind_reports, research, flash)
            # 抽取成功（含空结果）即落库，避免反复重跑；AI 失败会抛异常→不写，下次再试
            await asyncio.to_thread(_db.set, _clues_ck(), {"clues": clues}, morning._AI_TTL, "review")
        except Exception as exc:  # noqa: BLE001
            logger.debug("clues warm failed: %s", exc)
        finally:
            _clues_warming = False

    try:
        asyncio.create_task(_run())
        _clues_warming = True
    except RuntimeError:
        pass


async def _section_clues() -> dict[str, Any]:
    """新增线索：只读当日缓存（AI 抽取的结构化事件→受益票），没命中后台预热。"""
    cached = None
    try:
        from quantforge.data.storage import db_cache as _db
        cached = await asyncio.to_thread(_db.get, _clues_ck(), morning._AI_TTL)
    except Exception:  # noqa: BLE001
        cached = None
    if not isinstance(cached, dict):
        _warm_clues()
        return {"ok": True, "pending": True, "clues": [], "count": 0}
    clues = cached.get("clues") or []
    return {"ok": True, "pending": False, "clues": clues, "count": len(clues)}
