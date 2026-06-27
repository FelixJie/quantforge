"""首页看板聚合接口.

为首页新增的板块提供数据：
  - 涨幅排名         GET /home/gainers          —— 本地行情快照(stock_quote)
  - 1分钟涨速个股     GET /home/speed/stocks      —— 快照 + 滚动采样算 1 分钟涨速
  - 板块涨幅榜        GET /home/board-gainers     —— 概念(同花顺)/行业(新浪) 可切换
  - 板块1分钟涨速     GET /home/board-speed       —— 概念(同花顺)/行业(新浪) + 滚动采样
  - 每日两融数据      GET /home/margin            —— akshare 沪深市场两融汇总
  - 每日复盘(AI)      GET /home/review            —— 指数行情 + LLM

行情类一律走**本地已有数据源**(stock_quote 快照、同花顺概念指数、新浪行业)，不依赖
东财 push2(本地被代理劫持)，因此本地与线上 BCC 表现一致。涨速 = 当前价相对约 1 分钟前
一份采样的涨幅；采样落在 db_cache，冷启动头 1 分钟 / 收盘无波动时回退按涨幅排序，不空白。
自选股 / 增量信息(快讯) 复用既有 /watchlist /news 接口。
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import time as _time

from fastapi import APIRouter, Query
from loguru import logger

from quantforge.data.storage import db_cache as _db

router = APIRouter(prefix="/home", tags=["home"])


async def _cached(key: str, ttl: int, builder) -> dict:
    """先查缓存 → 拉取 → 失败回退旧值；统一外壳。"""
    hit = _db.get(key, ttl_seconds=ttl)
    if hit:
        return hit
    try:
        result = await asyncio.to_thread(builder)
        if result.get("items") or result.get("text"):
            _db.set(key, result, ttl_seconds=ttl, category="home")
            return result
    except Exception as exc:
        logger.debug(f"home {key} fetch failed: {exc}")
    stale = _db.get_stale(key)
    if stale:
        stale["stale"] = True
        return stale
    return {"items": [], "updated_at": None}


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _snapshot_rows(*, sort_by="change_pct", order="desc",
                   filter_type=None, limit=500, pages=1) -> list[dict]:
    """从本地 stock_quote 快照取行（可翻页拼接）。"""
    out: list[dict] = []
    for p in range(1, pages + 1):
        rows, _ = _db.quote_query(sort_by=sort_by, order=order,
                                  filter_type=filter_type, page=p, page_size=limit)
        if not rows:
            break
        out.extend(rows)
    return out


# 「1分钟涨速」滚动采样参数：
#   每 ~60s 把 cur 降为 prev 再写新 cur，故 prev 的年龄约 60–120s ≈ 1 分钟。
#   基准窗口取 [50, 600]s：50s 是 1 分钟采样刚成形的下限，>600s(10 分钟)视为陈旧
#   (午休/停盘后重连)直接弃用 → 回退按涨幅，避免拿一小时前的价当「1分钟前」。
_SPEED_ROTATE = 60
_SPEED_MIN_AGE = 50
_SPEED_MAX_AGE = 600


def _board_list(kind: str) -> list[dict]:
    """概念 / 行业板块列表（统一入口，供涨幅榜 & 涨速复用）。

    概念**只用同花顺概念指数**(ths_concept)：词条覆盖远比新浪概念全、且自带指数
    涨跌幅与领涨股。已落库则直接读库(秒回)，陈旧才现抓；不再回退新浪概念
    （概念页/预热器保鲜的 sector_boards 是唯一真源，避免首页与板块页概念词条不一致）。
    行业仍走新浪。返回元素统一含 node/name/change_pct/leader 字段。
    """
    from quantforge.api.routes import sector
    if kind == "concept":
        # 只读后台预热器保鲜的落库快照，不在用户请求里抓取(避免触发同花顺限频)；
        # 同花顺取不到时宁可空(落库快照兜底)，不掺新浪概念。
        boards = sector.cached_concept_boards()
        # 统一 node 键：同花顺板块用 code 作 node 供采样去重
        for b in boards:
            b.setdefault("node", b.get("code") or b.get("name"))
        return boards
    return sector._sina_industry_list() or []


def _rolling_speed(key: str, cur_vals: dict[str, float], kind: str) -> dict[str, float]:
    """滚动采样算「1分钟涨速」。维护两槽(prev/cur)，prev 约 1 分钟前。

    - kind="ratio": 速度 = (now-prev)/prev*100，用于个股价格。
    - kind="delta": 速度 = now-prev，用于板块涨跌幅(百分点变化)。
    返回 {code: speed}；无可用基准(冷启动头 1 分钟 / 午休停盘后基准过旧)时返回空，
    调用方回退按涨幅排序(前端标「暂按涨幅」)。

    停盘个股：其快照价不再变动，prev/cur 取到的是停盘前最后一笔，故速度≈0 被下方
    阈值剔除而不进涨速榜——等同「保留停盘前一分钟」基准、不污染榜单。
    """
    now = _time.time()
    st = _db.get_stale(key) or {}
    prev = st.get("prev")
    cur = st.get("cur")

    speeds: dict[str, float] = {}
    base = prev or cur            # 优先用更早的一份做 ~1 分钟基准
    if base and base.get("vals"):
        age = now - float(base.get("ts", 0))
        if _SPEED_MIN_AGE <= age <= _SPEED_MAX_AGE:
            bvals = base["vals"]
            for code, v in cur_vals.items():
                pv = bvals.get(code)
                if pv in (None, 0):
                    continue
                speeds[code] = (v - pv) / pv * 100.0 if kind == "ratio" else (v - pv)

    # 轮换：cur 缺失或已满 ~1 分钟 → cur 降为 prev，写入新 cur
    if not cur or (now - float(cur.get("ts", 0))) >= _SPEED_ROTATE:
        st["prev"] = cur or {"ts": now, "vals": cur_vals}
        st["cur"] = {"ts": now, "vals": cur_vals}
        _db.set(key, st, ttl_seconds=3600, category="home")

    # 丢弃近零速度：收盘/无波动/停盘时两次采样价格一致 → speed≈0，若原样返回会让
    # 调用方误判为「有实时涨速」并展示一片 +0.00%。剔除后空 dict 触发回退按涨幅。
    return {c: s for c, s in speeds.items() if abs(s) >= 0.005}


# ── 涨幅排名 ──────────────────────────────────────────────────────────────────
@router.get("/gainers")
async def get_gainers(top: int = Query(15, le=50)):
    def build():
        rows = _snapshot_rows(filter_type="gainers", limit=top)
        items = [{
            "code": r.get("code"), "name": r.get("name"),
            "price": r.get("price"), "change_pct": r.get("change_pct"),
            "speed": None,
        } for r in rows[:top]]
        return {"items": items, "updated_at": _db.quote_max_updated() or _now()}
    return await _cached(f"home_gainers_{top}", 30, build)


# ── 5分钟涨速·个股 ────────────────────────────────────────────────────────────
@router.get("/speed/stocks")
async def get_speed_stocks(top: int = Query(15, le=50)):
    def build():
        # 取流动性最好的 ~1000 只作为采样池（涨速领涨股基本都在活跃股内）。
        rows = _snapshot_rows(sort_by="turnover", order="desc", limit=500, pages=2)
        by_code = {r["code"]: r for r in rows if r.get("code")}
        cur = {c: r["price"] for c, r in by_code.items() if r.get("price")}
        speeds = _rolling_speed("home_speed_sample_stk", cur, "ratio")

        if speeds:
            ranked = sorted(speeds.items(), key=lambda kv: kv[1], reverse=True)[:top]
            items = [{
                "code": c, "name": by_code[c].get("name"),
                "price": by_code[c].get("price"),
                "change_pct": by_code[c].get("change_pct"),
                "speed": round(sp, 2),
            } for c, sp in ranked]
        else:
            # 冷启动 / 收盘无波动：回退按涨幅排序，至少不空白。
            rows.sort(key=lambda r: (r.get("change_pct") if r.get("change_pct") is not None else -1e9),
                      reverse=True)
            items = [{
                "code": r.get("code"), "name": r.get("name"),
                "price": r.get("price"), "change_pct": r.get("change_pct"),
                "speed": None,
            } for r in rows[:top]]
        return {"items": items, "updated_at": _db.quote_max_updated() or _now()}
    return await _cached(f"home_speed_stocks_{top}", 30, build)


# ── 1分钟涨速·板块（概念/行业 可切换）────────────────────────────────────────
@router.get("/board-speed")
async def get_board_speed(
    kind: str = Query("concept", enum=["concept", "industry"]),
    top: int = Query(12, le=30),
):
    """概念 / 行业板块 1 分钟涨速（按涨跌幅 1 分钟变化 = 百分点/分钟 降序）。

    概念用同花顺概念指数、行业用新浪，与涨幅榜同源；冷启动头 1 分钟回退按涨幅。
    """
    def build():
        boards = _board_list(kind)
        by_node = {b["node"]: b for b in boards if b.get("node")}
        cur = {n: b["change_pct"] for n, b in by_node.items()
               if b.get("change_pct") is not None}
        speeds = _rolling_speed(f"home_speed_sample_board_{kind}", cur, "delta")

        def _item(node, sp):
            b = by_node[node]
            return {
                "code": node, "name": b.get("name"),
                "change_pct": b.get("change_pct"),
                "speed": round(sp, 2) if sp is not None else None,
                "leader": b.get("leader") or None,
            }

        if speeds:
            ranked = sorted(speeds.items(), key=lambda kv: kv[1], reverse=True)[:top]
            items = [_item(n, sp) for n, sp in ranked]
        else:
            boards.sort(key=lambda b: (b.get("change_pct") if b.get("change_pct") is not None else -1e9),
                        reverse=True)
            items = [_item(b["node"], None) for b in boards[:top] if b.get("node")]
        return {"items": items, "updated_at": _now()}
    return await _cached(f"home_board_speed_{kind}_{top}", 30, build)


# ── 板块/概念涨幅榜（可切换）────────────────────────────────────────────────
@router.get("/board-gainers")
async def get_board_gainers(
    kind: str = Query("concept", enum=["concept", "industry"]),
    top: int = Query(12, le=30),
):
    """概念 / 行业板块涨幅榜（按涨跌幅降序）。

    概念用同花顺概念指数(词条全、自带涨幅与领涨)，行业走新浪；统一经 ``_board_list``。
    上游失败回退旧值，不空白。
    """
    def build():
        boards = [b for b in _board_list(kind) if b.get("change_pct") is not None]
        boards.sort(key=lambda b: b["change_pct"], reverse=True)
        items = [{
            "code": b.get("node"),
            "name": b.get("name"),
            "change_pct": b.get("change_pct"),
            "leader": b.get("leader") or None,
        } for b in boards[:top]]
        return {"items": items, "updated_at": _now()}
    return await _cached(f"home_board_gainers_{kind}_{top}", 60, build)


# ── 每日两融数据 ──────────────────────────────────────────────────────────────
@router.get("/margin")
async def get_margin():
    def build():
        import akshare as ak

        def _num(v) -> float:
            try:
                f = float(v)
                return 0.0 if f != f else f       # NaN → 0
            except (TypeError, ValueError):
                return 0.0

        out: list[dict] = []
        total_rz = total_rq = total_all = 0.0
        have = False

        # 近 N 个交易日两市合计余额，按日期聚合 → 前端画曲线。一次取满一年
        # (~250 交易日)，前端按 1月/3月/半年/1年 客户端切片，避免重复请求。
        SERIES_DAYS = 250
        by_date: dict[str, dict] = {}

        # 沪/深市场两融汇总：列 日期/融资余额/融券余额/融资融券余额，行按日期升序，
        # tail(1) 即最新交易日；整段尾部用于历史曲线。
        for market, fn in (("上交所", ak.macro_china_market_margin_sh),
                           ("深交所", ak.macro_china_market_margin_sz)):
            try:
                df = fn()
            except Exception as exc:
                logger.debug(f"margin {market} failed: {exc}")
                continue
            if df is None or df.empty:
                continue
            # 历史区段：逐日累加沪+深的余额到 by_date（只取尾部 N 日省内存）
            for rec in df.tail(SERIES_DAYS).to_dict("records"):
                day = str(rec.get("日期", "")).strip()
                if not day:
                    continue
                rzv = _num(rec.get("融资余额"))
                rqv = _num(rec.get("融券余额"))
                allvv = _num(rec.get("融资融券余额")) or (rzv + rqv)
                agg = by_date.setdefault(day, {"rz": 0.0, "rq": 0.0, "total": 0.0})
                agg["rz"] += rzv; agg["rq"] += rqv; agg["total"] += allvv

            # 最新交易日：当前卡片明细
            row = df.tail(1).iloc[0].to_dict()
            rz = _num(row.get("融资余额"))
            rq = _num(row.get("融券余额"))
            allv = _num(row.get("融资融券余额")) or (rz + rq)
            out.append({"market": market, "date": str(row.get("日期", "")),
                        "rz": rz, "rq": rq, "total": allv})
            total_rz += rz; total_rq += rq; total_all += allv; have = True

        if not have:
            return {"items": [], "updated_at": None}

        out.append({"market": "两市合计", "date": out[0].get("date", ""),
                    "rz": total_rz, "rq": total_rq, "total": total_all})

        # 两市合计曲线，按日期升序。沪深交易日历一致，逐日对齐即可。
        series = [
            {"date": d, "rz": v["rz"], "rq": v["rq"], "total": v["total"]}
            for d, v in sorted(by_date.items())
        ]
        return {"items": out, "series": series, "updated_at": _now()}

    # 两融为日度数据；缓存键按日切分，避免跨日命中旧值。盘中 30 分钟刷新一次，
    # 确保数据中心更新当日(T+1)余额后能尽快反映。
    key = f"home_margin_{_dt.date.today().isoformat()}"
    return await _cached(key, 30 * 60, build)


# ── 每日复盘（AI 生成，按日缓存）──────────────────────────────────────────────
@router.get("/review")
async def get_review():
    today = _dt.date.today().isoformat()
    key = f"home_review_{today}"
    hit = _db.get(key, ttl_seconds=12 * 3600)
    if hit:
        return hit

    from quantforge.api.routes.market import _fetch_index_quotes, _INDEX_LIST
    from quantforge.api import ai_client

    try:
        quotes = await asyncio.to_thread(_fetch_index_quotes)
        idx_lines = []
        for name, _code, _src, raw in _INDEX_LIST[:6]:
            q = quotes.get(raw) or {}
            pct = q.get("change_pct")
            if pct is not None:
                idx_lines.append(f"{name} {pct:+.2f}%")
        idx_text = "；".join(idx_lines) or "(指数数据暂缺)"

        system = ("你是一名A股资深复盘分析师。基于给定的主要指数当日涨跌，"
                  "用简洁专业的中文写一段每日复盘，120字以内，包含：今日市场情绪、"
                  "结构性特征(谁强谁弱)、对明日的简短提示。不要列表，不要免责声明。")
        user = f"今日主要指数表现：{idx_text}。请给出复盘。"
        text = await ai_client.chat(system, user, max_tokens=400, caller="home_review")

        result = {"text": (text or "").strip(), "indices": idx_lines,
                  "date": today, "updated_at": _now()}
        if result["text"]:
            _db.set(key, result, ttl_seconds=12 * 3600, category="home")
        return result
    except Exception as exc:
        logger.debug(f"home review failed: {exc}")
        stale = _db.get_stale(key)
        if stale:
            return stale
        return {"text": "", "indices": [], "date": today, "updated_at": None}


# ── 今日首次买入信号 ──────────────────────────────────────────────────────────
# 「首次买入」= 动能状态今天才由非买入翻转为 buy（signals 最后一根穿越落在最新交易日）。
# 与「当前处于 buy 持有中」区分：只挑**今天刚触发**的，避免把几天前买点的票混进来。
# 全市场扫描很重(对每只算 180 日动能)：只读 K 线缓存、无网络，asyncio 高并发跑 +
# 5 分钟缓存。空结果也写缓存(避免「今日确实无信号」时反复重扫)。
_FRESH_BUY_KEY = "home_fresh_buy"
_FRESH_BUY_TTL = 300
_fresh_buy_lock = asyncio.Lock()


async def _scan_fresh_buy() -> dict:
    from quantforge.api.routes.ai_picks import (
        _load_bars_cache_only, _safe_float as _sf, _mcap_to_yi,
        _MIN_TURNOVER_YI, _MOMO_CONCURRENCY,
    )
    from quantforge.analysis.momentum import compute_momentum, MomentumConfig

    cfg = MomentumConfig()

    # 1) 全市场池(快照分页) + 基础过滤(剔 ST/退/近涨停/僵尸股)
    pool: list[dict] = []
    page = 1
    while True:
        rows, total = _db.quote_query(page=page, page_size=500)
        if not rows:
            break
        for r in rows:
            code = (r.get("code") or "").strip()
            name = (r.get("name") or "")
            if not code or "ST" in name.upper() or "退" in name:
                continue
            ch = _sf(r.get("change_pct"))
            if ch is not None and ch >= 9.5:
                continue
            to = _sf(r.get("turnover"))
            if to is not None and to > 0 and to < _MIN_TURNOVER_YI * 1e8:
                continue
            pool.append(r)
        if len(pool) >= total or len(rows) < 500:
            break
        page += 1

    # 2) 只读缓存的全市场动能扫描(高并发、无网络)，筛出「今日首次买入」
    sem = asyncio.Semaphore(_MOMO_CONCURRENCY)

    async def _scan(r: dict) -> dict | None:
        code = (r.get("code") or "").strip()
        async with sem:
            bars = await asyncio.to_thread(_load_bars_cache_only, code)
        if not bars or len(bars) < 40:
            return None
        try:
            mom = compute_momentum(bars, cfg)
        except Exception:
            return None
        sigs = mom.get("signals") or []
        if not sigs:
            return None
        last = sigs[-1]
        last_bar_date = str(bars[-1].get("date") or "")
        # 今日首次买入：最后一个信号是 buy，且穿越日 == 该股最后一根 K 线日期
        if last.get("type") != "buy" or not last_bar_date:
            return None
        if str(last.get("date") or "") != last_bar_date:
            return None
        cur = mom.get("current") or {}
        return {
            "code": code,
            "name": r.get("name", ""),
            "price": _sf(r.get("price")),
            "change_pct": _sf(r.get("change_pct")),
            "signal_date": last_bar_date,
            "score": _sf(cur.get("score")),
            "buy_price": _sf(cur.get("buy_price")),
            "stop_price": _sf(cur.get("stop_price")),
            "target_price": _sf(cur.get("target_price")),
            "stop_pct": _sf(cur.get("stop_pct")),
            "target_pct": _sf(cur.get("target_pct")),
            "rr": _sf(cur.get("rr")),
            "market_cap": _mcap_to_yi(r.get("market_cap")),
        }

    scanned = await asyncio.gather(*[_scan(r) for r in pool])
    items = [x for x in scanned if x]
    items.sort(key=lambda x: -(x.get("score") or 0))   # 动能分高→低，强者优先
    logger.info(f"home/fresh-buy: 池 {len(pool)} 只 → 今日首次买入 {len(items)} 只")
    return {"items": items, "updated_at": _now()}


@router.get("/fresh-buy")
async def fresh_buy(top: int = Query(30, ge=1, le=100)):
    """今日首次触发买入信号的个股榜（全市场扫描，缓存 5 分钟）。"""
    hit = _db.get(_FRESH_BUY_KEY, ttl_seconds=_FRESH_BUY_TTL)
    if hit is None:
        # 锁内串行，避免并发请求同时触发多次全市场重扫
        async with _fresh_buy_lock:
            hit = _db.get(_FRESH_BUY_KEY, ttl_seconds=_FRESH_BUY_TTL)
            if hit is None:
                try:
                    hit = await _scan_fresh_buy()
                    _db.set(_FRESH_BUY_KEY, hit, ttl_seconds=_FRESH_BUY_TTL, category="home")
                except Exception as exc:
                    logger.warning(f"home/fresh-buy scan failed: {exc}")
                    hit = _db.get_stale(_FRESH_BUY_KEY) or {"items": [], "updated_at": None}
    items = (hit.get("items") or [])[:top]
    return {"items": items, "updated_at": hit.get("updated_at"),
            "count": len(hit.get("items") or [])}
