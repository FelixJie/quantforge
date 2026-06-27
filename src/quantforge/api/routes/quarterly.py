"""季报分析（一级板块）——季报预增 / 净利润断层策略（二级板块）。

独立于「AI 每日精选」的板块。当前实现「净利润断层」子策略，纯规则、不走 AI：
  净利润断层 = ①净利润惊喜(业绩超预期，用净利同比>20%近似) + ②断层(业绩公告后首个
  交易日向上跳空高开≥3%且收阳线)。股票池：消费 / 医药 / 电子 / 通信 四大行业。

数据：东财 datacenter 业绩报表 + 业绩预告（公告日 / 净利同比 / 行业），见
``quantforge.analysis.jegap``；断层判定走本地日 K 缓存（市场 K 线预热器已灌库）。
产出结构与 ai_picks 的 picks 一致，前端复用同一套卡片渲染。

Endpoints:
  GET  /api/quarterly/jegap          → 今日净利润断层榜（缓存优先，缺则现场生成）
  POST /api/quarterly/jegap/refresh  → 后台强制重算
  GET  /api/quarterly/jegap/status   → 运行状态 + 缓存覆盖度
"""

from __future__ import annotations

import asyncio
import json
import datetime as _dt
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks
from loguru import logger

router = APIRouter(prefix="/quarterly", tags=["quarterly"])

_CACHE_DIR = Path("data/cache/quarterly")
_RUNNING: dict[str, bool] = {}
_JEGAP_CONCURRENCY = 16


# ── 缓存 helpers（按交易日一份）─────────────────────────────────────────────────

def _trade_date(now: _dt.datetime | None = None) -> _dt.date:
    now = now or _dt.datetime.now()
    day = now.date()
    while day.weekday() >= 5:
        day += _dt.timedelta(days=1)
    return day


def _cache_path(strategy: str, day: str | None = None) -> Path:
    day = day or _trade_date().isoformat()
    return _CACHE_DIR / f"{strategy}_{day}.json"


def _load_cache(strategy: str) -> dict | None:
    f = _cache_path(strategy)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(strategy: str, data: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(strategy).write_text(
            json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"quarterly cache save failed: {e}")


# ── 每日线索日志：记录每天「新增推荐」了哪些股票 ──────────────────────────────────
_CLUE_LOG_PATH = _CACHE_DIR / "clue_log.json"
_CLUE_LOG_KEEP_DAYS = 90


def _load_clue_log() -> dict:
    if not _CLUE_LOG_PATH.exists():
        return {"jegap": [], "preincrease": []}
    try:
        data = json.loads(_CLUE_LOG_PATH.read_text(encoding="utf-8"))
        data.setdefault("jegap", [])
        data.setdefault("preincrease", [])
        return data
    except Exception:
        return {"jegap": [], "preincrease": []}


def _save_clue_log(log: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _CLUE_LOG_PATH.write_text(
            json.dumps(log, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"quarterly clue log save failed: {e}")


def _update_clue_log(strategy: str, picks: list[dict], date: str,
                     brief_fn) -> list[dict]:
    """把今日推荐与历史对比，记录**当日新增**的标的；返回当日新增列表。

    «新增» = 该 code 此前从未在本策略推荐过。按日存一条，同日重算则覆盖。
    """
    log = _load_clue_log()
    entries = [e for e in log.get(strategy, []) if e.get("date") != date]
    seen: set[str] = set()
    for e in entries:
        for it in e.get("new", []):
            if it.get("code"):
                seen.add(it["code"])
    new_items: list[dict] = []
    for p in picks:
        code = (p.get("code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        new_items.append({"code": code, "name": p.get("name") or "",
                          "brief": brief_fn(p)})
    entries.append({"date": date, "count": len(new_items), "new": new_items})
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)
    cutoff = (_dt.date.today() - _dt.timedelta(days=_CLUE_LOG_KEEP_DAYS)).isoformat()
    entries = [e for e in entries if e.get("date", "") >= cutoff]
    log[strategy] = entries
    _save_clue_log(log)
    return new_items


# ── 净利润断层：采集 → 断层判定 → 构建 picks ────────────────────────────────────

async def _collect_jegap() -> tuple[list[dict], dict]:
    """采集四大行业预增标的，逐只判定业绩公告后首日是否形成断层 + 漏斗计数。

    返回 ``(候选, funnel)``。候选含 ``_gap``(断层元数据) / ``_ann``(触发公告) /
    ``_days_since_gap``，已按断层日由近及远排序。
    """
    from quantforge.analysis import jegap
    from quantforge.api.routes.ai_picks import _load_bars_cache_only

    # 本季度（用户口径）：6/26 → Q2(06-30)。只看当季正在披露/预告的标的，未披露则为空。
    period = jegap.current_report_period()
    reports, forecasts, qoq_map = await asyncio.gather(
        asyncio.to_thread(jegap.fetch_reports, period),
        asyncio.to_thread(jegap.fetch_forecasts, period),
        asyncio.to_thread(jegap.compute_qoq_map, period),
    )
    # 行业仅财报口径有；预告无行业，按代码回填财报的行业归类
    code_sector = {r["code"]: (r["sector"], r["industry"]) for r in reports}

    merged: dict[str, dict] = {}

    def _add(item: dict, sector: str, industry):
        code = item["code"]
        m = merged.get(code)
        if not m:
            m = merged[code] = {
                "code": code, "name": item["name"], "sector": sector,
                "industry": industry, "growth": item["growth"],
                "period_label": item["period_label"], "anns": [],
            }
        m["growth"] = max(m["growth"], item["growth"])
        if item.get("name"):
            m["name"] = item["name"]
        m["anns"].append({
            "notice_date": item["notice_date"], "source": item["source"],
            "growth": item["growth"], "predict_type": item.get("predict_type"),
        })

    for r in reports:
        _add(r, r["sector"], r["industry"])
    forecast_only = 0
    for f in forecasts:
        sec = code_sector.get(f["code"])
        if sec:
            _add(f, sec[0], sec[1])
        else:
            forecast_only += 1         # 纯预告(暂无财报、无行业)——取消行业限制后仍纳入
            _add(f, "", "")

    # 单季净利环比（仅财报已披露的标的有，纯预告无精确数字）
    for code, m in merged.items():
        q = qoq_map.get(code)
        if q:
            m["qoq"] = q.get("qoq")
            m["qoq_note"] = q.get("note")

    funnel = {
        "market_total": len(reports) + len(forecasts),  # 抓取到的预增公告条数
        "after_filter": len(merged),                    # 全市场去重预增标的
        "scored": 0,                                    # 有日 K 缓存可判定断层
        "buy_points": 0,                                # 形成断层(高开≥3%+收阳)
        "selected": 0,                                  # 断层日落在近窗口(可参与)
        "cap": 0,
        "period": period,
        "period_label": jegap._period_label(period),
        "forecast_only": forecast_only,
    }
    if not merged:
        return [], funnel

    today = _dt.date.today()
    sem = asyncio.Semaphore(_JEGAP_CONCURRENCY)
    scored = 0

    async def _scan(m: dict):
        nonlocal scored
        async with sem:
            bars = await asyncio.to_thread(_load_bars_cache_only, m["code"])
        if not bars or len(bars) < 2:
            return None
        scored += 1
        # 对每个公告日检测断层，保留断层日最新的合格者（预告/财报哪个先触发都纳入）
        best = None
        for a in m["anns"]:
            g = jegap.detect_gap(bars, a["notice_date"])
            if not g:
                continue
            if best is None or g["gap_date"] > best["_gap"]["gap_date"]:
                best = {"_gap": g, "_ann": a}
        if not best:
            return None
        c = {**m}
        c["_gap"] = best["_gap"]
        c["_ann"] = best["_ann"]
        return c

    scanned = await asyncio.gather(*[_scan(m) for m in merged.values()])
    cands = [c for c in scanned if c]
    funnel["scored"] = scored
    funnel["buy_points"] = len(cands)

    kept: list[dict] = []
    for c in cands:
        try:
            days = (today - _dt.date.fromisoformat(c["_gap"]["gap_date"])).days
        except Exception:
            days = 999
        c["_days_since_gap"] = days
        if 0 <= days <= jegap.RECENT_DAYS:
            kept.append(c)
    funnel["selected"] = len(kept)

    # 断层日越新越靠前，再按净利同比、高开幅度
    kept.sort(key=lambda c: (c["_days_since_gap"], -(c["growth"] or 0),
                             -(c["_gap"]["gap_open_pct"] or 0)))
    return kept, funnel


# 断层后价格已涨离缺口收盘价超此幅度 → 入场机会已过，列为「已兑现·观察」
_JEGAP_RUNUP_MAX = 12.0
# 止损相对现价的最大幅度——缺口下沿离现价过远时改用技术止损，避免出现 -50% 的荒谬止损
_JEGAP_STOP_CAP = 10.0


def _build_jegap_picks(cands: list[dict]) -> list[dict]:
    """把断层候选转成 picks（规则化，不走 AI）。需先 enrich 回填现价。

    入场状态三档：
      · 可参与(actionable)：现价仍贴近缺口（涨幅未兑现）、缺口未回补 → 优先推荐。
      · 已兑现(ran_up)：断层后已大涨远离缺口、追高风险大 → 标「观察」、排后。
      · 已回补(filled)：现价跌回缺口下沿之下、断层失效 → 标「观察」、排最后。
    """
    rows: list[dict] = []
    for c in cands:
        g = c["_gap"]
        ann = c["_ann"]
        days = c.get("_days_since_gap", 0)
        growth = c.get("growth")
        qoq = c.get("qoq")
        qoq_note = c.get("qoq_note")
        sector = c.get("sector") or ""
        source = ann.get("source") or "财报"
        ptype = ann.get("predict_type")
        prev_close = g.get("prev_close")       # 缺口下沿/回补位
        gap_close = g.get("gap_close")         # 断层日收盘
        gap_open_pct = g.get("gap_open_pct")
        gap_date = g.get("gap_date")
        when = "今日" if days == 0 else f"{days}日前"

        price = c.get("price") or gap_close
        buy = round(price, 2) if price else None

        # 断层后涨幅（相对断层日收盘）
        rise_since = ((price / gap_close - 1.0) * 100.0) if (price and gap_close) else 0.0
        filled = bool(price and prev_close and price < prev_close)     # 缺口回补、失效
        ran_up = bool(not filled and rise_since > _JEGAP_RUNUP_MAX)    # 已大幅兑现
        actionable = not filled and not ran_up

        # 止损 = 缺口下沿(前收)；离现价过远则改技术止损（现价-10%），避免荒谬止损幅度
        stop = prev_close
        if buy and stop and stop < buy and (1 - stop / buy) * 100 <= _JEGAP_STOP_CAP:
            stop_pct = round((1 - stop / buy) * 100, 1)
        else:
            stop = round(buy * (1 - _JEGAP_STOP_CAP / 100), 2) if buy else None
            stop_pct = _JEGAP_STOP_CAP
        target_pct = 15.0
        target = round(buy * (1 + target_pct / 100), 2) if buy else None

        conf = 60
        conf += int(min((growth or 0) / 5.0, 20))          # 净利同比越高越加分
        conf += int(min((gap_open_pct or 0) * 2.0, 12))    # 高开越猛越加分
        conf += max(0, 8 - days // 3)                      # 断层越新越加分
        if ran_up:
            conf -= 18
        if filled:
            conf -= 28
        conf = int(min(95, max(35, conf)))

        if filled:
            state, entry_label = "sell", "缺口回补"
        elif ran_up:
            state, entry_label = "hold", "已兑现·观察"
        else:
            state, entry_label = "buy", "可参与"

        # 环比措辞（单季净利环比，仅财报已披露者有）
        if qoq is not None:
            qoq_txt = f"净利环比{qoq:+.0f}%"
        elif qoq_note:
            qoq_txt = qoq_note
        else:
            qoq_txt = None

        signals = [
            f"净利同比{growth:+.0f}%" if growth is not None else "业绩预增",
            f"高开{gap_open_pct:+.1f}%", "收阳线", f"{when}断层", source,
        ]
        if qoq_txt:
            signals.append(qoq_txt)
        if sector:
            signals.append(sector)

        type_clause = f"{source}{ptype}" if (source == "预告" and ptype) else source
        if qoq is not None:
            qoq_clause = f"单季净利润环比{qoq:+.1f}%，"
        elif qoq_note:
            qoq_clause = f"单季净利润{qoq_note}，"
        else:
            qoq_clause = ""
        reason = (
            f"{c.get('period_label', '')}净利润同比{growth:+.1f}%（{type_clause}），{qoq_clause}"
            f"{ann.get('notice_date')}业绩公告后，{gap_date}首个交易日跳空高开{gap_open_pct:+.1f}%、"
            f"收阳线（断层日全天{g.get('gap_day_chg'):+.1f}%），市场以向上跳空认可业绩超预期，形成净利润断层。"
            f"属{sector}板块。"
        )
        if filled:
            reason += "注意：现价已跌回缺口下沿之下（缺口回补），断层失效，仅供观察、勿抄底。"
        elif ran_up:
            reason += f"注意：断层后现价已较断层收盘上涨{rise_since:+.0f}%，入场机会基本兑现，追高风险大，仅作观察。"

        rows.append({
            "code": c["code"], "name": c["name"], "sector": sector,
            "reason": reason, "signals": signals,
            "buy_price": buy, "stop_price": stop, "target_price": target,
            "target_pct": target_pct, "stop_pct": stop_pct,
            "checklist": [
                f"回踩不破缺口下沿(前收 {prev_close})且快速收复，再顺势跟进，勿追高断层当日大阳",
                "成交量较断层日不持续放大、无放量长阴；分时承接有力",
                "业绩高增可持续（非资产处置/补贴等一次性损益），所属板块景气向上",
                f"止损：跌破缺口下沿 {prev_close} 即视为缺口回补、断层失效，离场",
            ],
            "confidence": conf, "risk_level": "中", "holding_period": "2-8周",
            "no_buy_point": not actionable,
            "entry_state": state, "entry_label": entry_label,
            "price": price, "change_pct": c.get("change_pct"),
            "pe": c.get("pe"), "pb": c.get("pb"),
            # 复用 ai_picks 卡片的 momentum 槽位承载断层信息
            "momentum": {
                "score": conf, "state": state,
                "growth": growth, "qoq": qoq, "qoq_note": qoq_note,
                "gap_date": gap_date, "days_since": days,
                "gap_open_pct": gap_open_pct, "gap_day_chg": g.get("gap_day_chg"),
                "rise_since": round(rise_since, 1), "source": source,
                "prev_close": prev_close, "gap_close": gap_close,
                "gap_filled": filled, "ran_up": ran_up, "entry_label": entry_label,
                "buy_price": buy, "stop_price": stop, "target_price": target,
                "stop_pct": stop_pct, "target_pct": target_pct,
            },
            "_sortkey": (0 if actionable else (1 if ran_up else 2), days, -(growth or 0)),
        })

    # 可参与(新鲜) → 已兑现 → 已回补；同档内断层日越近、净利增速越高越靠前
    rows.sort(key=lambda r: r["_sortkey"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r.pop("_sortkey", None)
    return rows


def _jegap_summary(picks: list[dict], funnel: dict) -> tuple[str, str]:
    label = funnel.get("period_label", "季报")
    if picks:
        n_act = sum(1 for p in picks if not p.get("no_buy_point"))
        summary = (
            f"净利润断层·{label}：全市场范围内，净利润同比>20%（业绩超预期近似）"
            f"且业绩公告后首个交易日高开≥3%并收阳线的标的共 {len(picks)} 只，"
            f"其中现价仍贴近缺口、可参与 {n_act} 只（其余已大幅兑现或缺口回补，仅供观察）。"
            "断层=市场以向上跳空对业绩报告的认可，跳空越坚决、净利增速越高越受关注。"
        )
        op = ("断层战法：优先参与近期新形成、缺口未回补的断层标的；回踩缺口下沿不破再跟进，"
              "跌破缺口下沿（缺口回补）即断层失效止损。重业绩可持续性、轻短线追涨。")
    else:
        summary = (
            f"净利润断层·{label}：全市场暂无「净利同比>20% + 公告后首日高开≥3%收阳」"
            "的标的；可能因当季披露窗已过较久或断层标的现价已回补缺口，建议耐心等待下一轮业绩季。"
        )
        op = "当前无新形成的净利润断层标的，等待业绩季新的跳空确认。"
    return summary, op


async def _generate_jegap() -> dict:
    """净利润断层产出：东财业绩榜单 → 缓存断层判定 → 实时回填现价 → 规则化 picks（不走 AI）。"""
    from quantforge.api.routes.ai_picks import _enrich_candidates

    if _RUNNING.get("jegap"):
        cached = _load_cache("jegap")
        if cached:
            return cached
    _RUNNING["jegap"] = True
    try:
        cands, funnel = await _collect_jegap()
        cands = await _enrich_candidates(cands)   # 回填现价/涨跌，用于缺口回补判定
        picks = _build_jegap_picks(cands)
        funnel["recommended"] = len(picks)
        funnel["actionable"] = sum(1 for p in picks if not p.get("no_buy_point"))
        has_buy_point = funnel["actionable"] > 0
        summary, op = _jegap_summary(picks, funnel)

        now = _dt.datetime.now()
        payload = {
            "generated_at": now.isoformat(),
            "date": _trade_date(now).isoformat(),
            "strategy": "jegap",
            "strategy_label": "净利润断层",
            "no_buy_point": not has_buy_point,
            "market_summary": summary,
            "operation_strategy": op,
            "picks": picks,
            "candidate_count": funnel.get("after_filter", 0),
            "funnel": funnel,
        }
        try:
            new_items = _update_clue_log(
                "jegap", picks, payload["date"],
                lambda p: f"净利同比{(p.get('momentum') or {}).get('growth')}% · "
                          f"{(p.get('entry_label') or '断层')}",
            )
            payload["new_today"] = new_items
        except Exception as e:
            logger.warning(f"quarterly jegap clue log failed: {e}")
        _save_cache("jegap", payload)
        logger.info(
            f"quarterly[jegap]: 漏斗 预增公告{funnel['market_total']} → 全市场{funnel['after_filter']} "
            f"→ 可评分{funnel['scored']} → 断层{funnel['buy_points']} → 近{funnel.get('selected')}只可参与 "
            f"→ 产出{len(picks)}（报告期 {funnel.get('period_label')}）"
        )

        # 记录预测用于次日验证（与其它策略一致，走 levels 结算）
        try:
            from quantforge.prediction.tracker import PredictionTracker
            PredictionTracker.record_picks(payload["picks"], date=payload["date"],
                                           pick_strategy="jegap")
        except Exception as e:
            logger.warning(f"quarterly jegap: prediction recording failed: {e}")

        return payload
    finally:
        _RUNNING["jegap"] = False


# ── 季报预增：多源(机构荐股/研报/公众号/韭研公社)搜索预增线索 → AI 逐个分析 → 推荐 ──
# 用户需求：从机构荐股、研报、公众号、韭研公社、雪球等网站搜索「预增」类信息找线索，
# 再结合标的逐个分析预增幅度与理由后做出推荐。
# 说明：雪球无稳定免登录通路（本项目一贯不接入，见 review_framework 注释），故以
# 上述四源 + 东财官方业绩预告为骨架；东财预告提供「官方预增幅度」用于校正 AI 输出。

# 预增关键词：聚焦「业绩/利润同比大幅增长、超预期、扭亏、预喜」等措辞。
_PREINC_KEYWORDS: tuple[str, ...] = (
    "预增", "业绩预增", "净利预增", "利润预增", "预增公告", "业绩大增", "净利大增",
    "利润大增", "净利暴增", "业绩暴增", "业绩翻倍", "净利翻倍", "利润翻倍", "业绩高增",
    "业绩高增长", "净利高增", "超预期", "业绩超预期", "大超预期", "预喜", "业绩预喜",
    "扭亏", "扭亏为盈", "减亏", "预盈", "同比大增", "环比大增", "业绩拐点", "困境反转",
    "量利齐升", "增收增利", "业绩爆发", "盈利大增", "盈利高增",
)

_PREINC_LOOKBACK_DAYS = 20      # 预增线索回看天数（业绩季披露较集中，放宽到 20 天）
_PREINC_PER_SOURCE_CAP = 70
_PREINC_MAX_SIGNALS = 130


def _preinc_hit(text: str) -> list[str]:
    """返回 text 命中的预增关键词（去重保序）。"""
    t = text or ""
    out: list[str] = []
    for kw in _PREINC_KEYWORDS:
        if kw in t and kw not in out:
            out.append(kw)
    return out


def _preinc_begin(days: int = _PREINC_LOOKBACK_DAYS) -> str:
    return (_dt.date.today() - _dt.timedelta(days=days)).isoformat()


# ── 多源预增线索采集 ──────────────────────────────────────────────────────────

def _harvest_preinc_blog() -> list[dict]:
    """机构荐股 / 调研纪要（知识星球）：标题/正文含预增关键词。"""
    from quantforge.data.storage import db_cache as _db
    begin = _preinc_begin()
    out: list[dict] = []
    try:
        rows = _db.blog_posts_search(list(_PREINC_KEYWORDS), begin_date=begin, limit=250)
    except Exception as e:
        logger.debug(f"preinc harvest blog failed: {e}")
        rows = []
    for r in rows:
        title = (r.get("ai_title") or r.get("title") or "").strip()
        body = (r.get("content_text") or "").strip()
        kws = _preinc_hit(f"{title} {body}")
        if not kws:
            continue
        out.append({
            "source": "机构荐股", "source_kind": "blog",
            "title": title or body[:40], "snippet": body[:160],
            "date": (r.get("created_at") or "")[:10], "keywords": kws, "stocks": [],
        })
    return out[:_PREINC_PER_SOURCE_CAP]


def _harvest_preinc_stock_reports() -> list[dict]:
    """个股研报：标题含预增关键词；自带 stockCode 可直接定位个股。"""
    import sqlite3
    from quantforge.data.storage import db_cache as _db
    from quantforge.data.storage import stock_meta_cache
    out: list[dict] = []
    try:
        conn: sqlite3.Connection = _db._conn()
        like = " OR ".join(["title LIKE ?"] * len(_PREINC_KEYWORDS))
        params: list = [f"%{kw}%" for kw in _PREINC_KEYWORDS]
        params.append(_preinc_begin())
        rows = conn.execute(
            f"SELECT code, title, org, publish_date FROM stock_reports "
            f"WHERE ({like}) AND publish_date >= ? ORDER BY publish_date DESC LIMIT 250",
            params,
        ).fetchall()
    except Exception as e:
        logger.debug(f"preinc harvest stock_reports failed: {e}")
        rows = []
    names = {}
    try:
        names = stock_meta_cache.get_all_names()
    except Exception:
        pass
    for r in rows:
        title = (r["title"] or "").strip()
        kws = _preinc_hit(title)
        if not kws:
            continue
        code = (r["code"] or "").strip()
        nm = names.get(code) or names.get(code.zfill(6)) or ""
        out.append({
            "source": "个股研报", "source_kind": "stock_report",
            "title": title, "snippet": (r["org"] or "").strip(),
            "date": (r["publish_date"] or "")[:10], "keywords": kws,
            "stocks": [f"{nm}({code})"] if nm else ([code] if code else []),
        })
    return out[:_PREINC_PER_SOURCE_CAP]


def _harvest_preinc_industry_reports() -> list[dict]:
    """行业研报：标题/行业名含预增关键词（多为行业景气/业绩前瞻，作补充）。"""
    from quantforge.data.storage import db_cache as _db
    begin = _preinc_begin()
    out: list[dict] = []
    try:
        rows = _db.industry_reports_search(list(_PREINC_KEYWORDS), begin_date=begin, limit=200)
    except Exception as e:
        logger.debug(f"preinc harvest industry reports failed: {e}")
        rows = []
    for r in rows:
        title = (r.get("title") or "").strip()
        ind = (r.get("industry_name") or "").strip()
        kws = _preinc_hit(f"{title} {ind}")
        if not kws:
            continue
        out.append({
            "source": "行业研报", "source_kind": "industry_report",
            "title": title, "snippet": ind, "date": (r.get("publish_date") or "")[:10],
            "keywords": kws, "stocks": [],
        })
    return out[:_PREINC_PER_SOURCE_CAP]


def _harvest_preinc_fenchuan() -> list[dict]:
    """公众号（纷传快照）：标题/正文含预增关键词。"""
    out: list[dict] = []
    try:
        from quantforge.api.routes import fenchuan as _fc
        posts = (_fc._load_cache() or {}).get("posts") or []
    except Exception as e:
        logger.debug(f"preinc harvest fenchuan failed: {e}")
        posts = []
    begin = _preinc_begin()
    today = _dt.date.today().isoformat()
    for p in posts:
        title = (p.get("title") or "").strip()
        text = (p.get("text") or "").strip()
        kws = _preinc_hit(f"{title} {text}")
        if not kws:
            continue
        ptime = (p.get("time") or "")[:10]
        if ptime and not (begin <= ptime <= today):
            continue
        out.append({
            "source": "公众号", "source_kind": "fenchuan",
            "title": title or text[:40], "snippet": text[:160],
            "date": ptime, "keywords": kws, "stocks": [],
        })
    return out[:_PREINC_PER_SOURCE_CAP]


def _harvest_preinc_jiuyan() -> list[dict]:
    """韭研公社社区文章流：标题/正文含预增关键词（免登录签名抓取，带关联个股）。"""
    out: list[dict] = []
    try:
        from quantforge.data.feed import jiuyan
        rows = jiuyan.harvest_keyword_signals(
            list(_PREINC_KEYWORDS), lookback_days=_PREINC_LOOKBACK_DAYS, pages=8,
        )
    except Exception as e:
        logger.debug(f"preinc harvest jiuyan failed: {e}")
        rows = []
    for r in rows:
        out.append({
            "source": "韭研公社", "source_kind": "jiuyan",
            "title": r.get("title") or "", "snippet": r.get("snippet") or "",
            "date": r.get("date") or "", "keywords": r.get("keywords") or [],
            "stocks": r.get("stocks") or [],
            "url": f"https://www.jiuyangongshe.com/a/{r.get('article_id')}" if r.get("article_id") else "",
        })
    return out[:_PREINC_PER_SOURCE_CAP]


def _harvest_preinc_signals() -> dict:
    """汇总各源预增线索，去重 + 按时效/源权重/是否带个股排序。"""
    raw: list[dict] = []
    raw += _harvest_preinc_blog()       # 主源：机构荐股 / 调研纪要
    raw += _harvest_preinc_jiuyan()     # 主源：韭研公社
    raw += _harvest_preinc_stock_reports()
    raw += _harvest_preinc_industry_reports()
    raw += _harvest_preinc_fenchuan()

    seen: set[str] = set()
    uniq: list[dict] = []
    for s in raw:
        key = (s.get("title") or "")[:24]
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(s)

    today = _dt.date.today()

    def _rank(s: dict) -> float:
        try:
            d = _dt.datetime.strptime(s.get("date") or today.isoformat(), "%Y-%m-%d").date()
            age = (today - d).days
        except Exception:
            age = 3
        recency = max(0.3, 1.0 - age * 0.05)
        src_w = {
            "blog": 1.0, "jiuyan": 1.0, "stock_report": 0.85,
            "fenchuan": 0.7, "industry_report": 0.6,
        }.get(s.get("source_kind"), 0.6)
        kw_w = min(1.3, 1.0 + 0.08 * len(s.get("keywords") or []))
        stk_w = 1.15 if s.get("stocks") else 1.0
        return recency * src_w * kw_w * stk_w

    uniq.sort(key=_rank, reverse=True)
    signals = uniq[:_PREINC_MAX_SIGNALS]
    by_source: dict[str, int] = {}
    for s in signals:
        by_source[s["source"]] = by_source.get(s["source"], 0) + 1
    return {
        "signals": signals, "by_source": by_source, "total": len(signals),
        "updated_at": _dt.datetime.now().isoformat(),
    }


# ── 东财官方业绩预告（提供「官方预增幅度」用于校正 AI 输出）─────────────────────────

def _official_forecasts(period: str) -> tuple[dict, dict, list[dict]]:
    """全市场业绩预告（净利同比>20%）：返回 (按名索引, 按代码索引, 按幅度降序的精简榜)。

    period 为**预测目标季**（本季度）：公司发布的业绩预告即是对当季业绩的预测。
    """
    from quantforge.analysis import jegap
    rows = jegap.fetch_forecasts(period)   # [{code,name,growth,notice_date,predict_type,...}]
    by_name: dict[str, dict] = {}
    by_code: dict[str, dict] = {}
    for r in rows:
        by_code[r["code"]] = r
        if r.get("name"):
            by_name[r["name"]] = r
    compact = [
        {"code": r["code"], "name": r["name"], "growth": r.get("growth"),
         "predict_type": r.get("predict_type"), "notice_date": r.get("notice_date")}
        for r in sorted(rows, key=lambda x: -(x["growth"] or 0))
    ]
    return by_name, by_code, compact


# ── AI 逐个分析预增幅度与理由 → 推荐 ───────────────────────────────────────────

def _build_preinc_material(signals: list[dict], forecast_rows: list[dict]) -> str:
    groups: dict[str, list[dict]] = {}
    for s in signals:
        groups.setdefault(s["source"], []).append(s)
    parts: list[str] = []
    for src, items in groups.items():
        lines = []
        for s in items[:45]:
            tag = "/".join(s.get("keywords") or [])
            stk = ("｜相关：" + "、".join(s["stocks"])) if s.get("stocks") else ""
            d = s.get("date") or ""
            lines.append(f"· [{d}][{tag}] {s['title']}{stk}")
        parts.append(f"【{src}】\n" + "\n".join(lines))
    material = "\n\n".join(parts)[:11000]
    if forecast_rows:
        fl = []
        for r in forecast_rows[:70]:
            t = r.get("predict_type") or ""
            fl.append(f"· {r['name']}({r['code']}) 净利同比+{r.get('growth')}% {t}")
        material += "\n\n【东财官方业绩预告·预增幅度（净利同比，权威数据）】\n" + "\n".join(fl)
    return material[:13500]


async def _run_preinc_ai(harvest: dict, forecast_rows: list[dict],
                         by_name: dict, by_code: dict, period_label: str = "") -> dict:
    """综合多源预增线索 + 官方预告 → AI 逐个标的分析预增幅度/理由 → 推荐清单。"""
    from quantforge.api.ai_client import chat
    from quantforge.api.research_helpers import _loads_lenient
    from quantforge.api.routes.price_surge import _enrich_stocks, _name_to_code

    signals = harvest.get("signals") or []
    if not signals and not forecast_rows:
        return {
            "picks": [],
            "summary": "近期暂未从机构荐股/研报/公众号/韭研公社等源捕捉到明显的业绩预增线索。",
            "signal_count": 0, "generated_at": _dt.datetime.now().isoformat(),
        }

    material = _build_preinc_material(signals, forecast_rows)
    target = period_label or "本季度"
    system = (
        f"你是A股「业绩预增」主题分析师。任务：从下列多源线索（机构荐股/调研纪要、韭研公社"
        "为主，个股研报/公众号/行业研报为辅）与东财官方业绩预告中，挑出**当季（即预测目标季"
        f" {target}）业绩确实预增（净利润大幅增长/扭亏/超预期）**且逻辑扎实的个股，逐个**预测"
        f"其 {target} 的业绩**，分析『预增幅度（同比）』『环比趋势』与『预增理由』，给出推荐。"
        "要求实事求是：**预增幅度优先采用【官方业绩预告】里的净利同比数字**；无官方预告的标的，"
        "用线索中卖方/媒体提到的幅度并注明是观点预估、不得编造精确数字；环比（较上一季度的"
        "单季净利环比趋势）结合线索定性判断（明显改善/持平/走弱），无依据则写「待披露」；"
        "预增理由要落到具体驱动（量价齐升/订单放量/产品涨价/产能释放/新品/降本/并表/低基数等）。"
        "**只对有明确预增或扭亏线索的标的做预测**，没有预增/扭亏线索的标的不要预测、不要硬凑。"
    )
    user = (
        f"预测目标季：**{target}**（对每只标的，预测其该季业绩；若该标的最新仅披露上一季，"
        "则预测本季）。以下是近期多源采集到的『业绩预增』线索与官方业绩预告：\n\n" + material +
        "\n\n请综合判断，输出一个 JSON 对象，格式如下：\n"
        '{"summary":"一句话整体判断（本季哪些方向/标的的预增最值得关注，2-3句）",'
        '"picks":[{'
        '"name":"股票简称（A股，不要代码）",'
        '"increase":"预增幅度（如 净利同比+120%~150% / 净利同比+80% / 扭亏为盈；'
        '有官方预告的用官方数字，无则写卖方预估并标注）",'
        '"increase_source":"官方预告|卖方预估|媒体观点",'
        '"qoq":"环比趋势（如 单季净利环比明显改善/环比走强/环比持平/环比走弱/环比扭亏/待披露）",'
        '"reason":"预增理由（具体驱动因素，结合线索，2-3句）",'
        '"evidence":["支撑判断的线索标题1","线索标题2"],'
        '"catalyst":"短期催化（业绩披露窗、订单、涨价落地等）",'
        '"confidence":"高|中|低"}]}\n'
        "要求：\n"
        "1. **列出所有有预增/扭亏证据的标的，不要人为限制数量、不要自行删减**；按确定性与弹性排序；\n"
        "2. 每只必须给出 increase、qoq 与 reason，并尽量给 evidence（引用上文线索标题）；\n"
        "3. increase 有官方业绩预告的，increase_source 填『官方预告』并采用其净利同比数字；\n"
        "4. **只预测有预增或扭亏线索的标的**，没有此类线索的不要纳入；\n"
        "5. confidence：高=官方预告已出且增幅大/多源印证；中=卖方明确预估、趋势确立；低=预期/传闻；\n"
        "6. 只输出 JSON 对象本身，不要任何额外文字或代码块标记。"
    )

    text = await chat(system, user, max_tokens=8000, caller="quarterly_preincrease", timeout=420)
    data = _loads_lenient(text)
    if not isinstance(data, dict):
        data = {}
    picks = [p for p in (data.get("picks") or []) if isinstance(p, dict)]

    rev = _name_to_code()
    out_picks: list[dict] = []
    for p in picks:
        nm = str(p.get("name") or "").strip()
        if not nm:
            continue
        enr = _enrich_stocks([nm], rev)
        info = enr[0] if enr else {"name": nm, "code": ""}
        p["name"] = info.get("name") or nm
        p["code"] = info.get("code") or ""
        p["price"] = info.get("price")
        p["change_pct"] = info.get("change_pct")
        p["market_cap"] = info.get("market_cap")
        # 官方预告幅度校正：以东财权威数据覆盖 AI 的幅度判断
        off = (by_code.get(p["code"]) if p["code"] else None) or by_name.get(nm)
        if off:
            p["official_growth"] = off.get("growth")
            p["predict_type"] = off.get("predict_type")
            p["notice_date"] = off.get("notice_date")
            if off.get("growth") is not None:
                p["increase"] = f"净利同比+{off['growth']}%" + (f"（{off.get('predict_type')}）" if off.get("predict_type") else "")
                p["increase_source"] = "官方预告"
        ev = p.get("evidence")
        if isinstance(ev, str):
            p["evidence"] = [ev]
        elif not isinstance(ev, list):
            p["evidence"] = []
        out_picks.append(p)

    # 排序：官方预告确认者优先，再按置信度，再按官方增幅
    conf_rank = {"高": 0, "中": 1, "低": 2}
    out_picks.sort(key=lambda p: (
        0 if p.get("official_growth") is not None else 1,
        conf_rank.get(p.get("confidence"), 3),
        -(p.get("official_growth") or 0),
    ))
    for i, p in enumerate(out_picks, 1):
        p["rank"] = i

    return {
        "picks": out_picks,
        "summary": str(data.get("summary") or ""),
        "signal_count": len(signals),
        "by_source": harvest.get("by_source", {}),
        "generated_at": _dt.datetime.now().isoformat(),
    }


def _preinc_fallback_picks(forecast_rows: list[dict]) -> list[dict]:
    """AI 不可用/无产出时的兜底：按官方预告全量列出（已是预增/扭亏标的，不删减）。"""
    picks: list[dict] = []
    for i, r in enumerate(forecast_rows, 1):
        g = r.get("growth")
        t = r.get("predict_type") or ""
        picks.append({
            "rank": i, "name": r["name"], "code": r["code"],
            "increase": f"净利同比+{g}%" + (f"（{t}）" if t else ""),
            "increase_source": "官方预告",
            "qoq": "待披露",
            "official_growth": g, "predict_type": t, "notice_date": r.get("notice_date"),
            "reason": f"东财业绩预告净利润同比+{g}%（{t or '预增'}），具体增长驱动与环比趋势待结合公告与研报进一步跟踪。",
            "evidence": [], "catalyst": "业绩披露窗", "confidence": "中",
            "price": None, "change_pct": None,
        })
    return picks


async def _generate_preincrease() -> dict:
    """季报预增：多源搜集预增线索 + 官方预告 → AI 逐个分析幅度/理由 → 推荐清单。"""
    if _RUNNING.get("preincrease"):
        cached = _load_cache("preincrease")
        if cached:
            return cached
    _RUNNING["preincrease"] = True
    try:
        from quantforge.analysis import jegap
        # 预测目标 = 本季度（最近已披露季的下一季）：Q1已出→预测Q2，Q2已出→预测Q3。
        period = jegap.current_report_period()
        period_label = jegap._period_label(period)

        harvest = await asyncio.to_thread(_harvest_preinc_signals)
        by_name, by_code, forecast_rows = await asyncio.to_thread(_official_forecasts, period)

        try:
            result = await _run_preinc_ai(harvest, forecast_rows, by_name, by_code, period_label)
        except Exception as e:
            logger.warning(f"quarterly preincrease AI failed, fallback to 官方预告榜: {e}")
            result = {"picks": [], "summary": "", "by_source": harvest.get("by_source", {})}

        picks = result.get("picks") or []
        if not picks and forecast_rows:
            picks = _preinc_fallback_picks(forecast_rows)
            result["summary"] = result.get("summary") or (
                f"季报预增·{period_label}：AI 线索分析暂未产出，先以东财官方业绩预告增幅榜兜底展示。"
            )

        now = _dt.datetime.now()
        payload = {
            "generated_at": now.isoformat(),
            "date": _trade_date(now).isoformat(),
            "strategy": "preincrease",
            "strategy_label": "季报预增",
            "period_label": period_label,
            "summary": result.get("summary") or (
                f"季报预增·{period_label}：从机构荐股/研报/公众号/韭研公社等源搜集预增线索，"
                f"结合东财官方业绩预告逐个分析后推荐 {len(picks)} 只。"
            ),
            "picks": picks,
            "count": len(picks),
            "signal_count": harvest.get("total", 0),
            "by_source": harvest.get("by_source", {}),
            "forecast_top": forecast_rows[:40],     # 官方预增榜参考（精简，无行情）
            "forecast_count": len(forecast_rows),
        }
        try:
            new_items = _update_clue_log(
                "preincrease", picks, payload["date"],
                lambda p: f"{p.get('increase') or '预增'} · {p.get('confidence') or '中'}信心",
            )
            payload["new_today"] = new_items
        except Exception as e:
            logger.warning(f"quarterly preincrease clue log failed: {e}")
        _save_cache("preincrease", payload)
        logger.info(
            f"quarterly[preincrease]: {period_label} 线索{harvest.get('total', 0)}条 "
            f"+ 官方预告{len(forecast_rows)}只 → 推荐{len(picks)}只"
        )
        return payload
    finally:
        _RUNNING["preincrease"] = False


# ── 定时生成 ─────────────────────────────────────────────────────────────────
# 每日 22:00（晚10点，用户要求）重算两榜：净利润断层取当日最新行情/业绩判定，季报预增
# 重新搜集多源线索 + AI 分析；同时落每日线索日志（当日新增推荐）。启动时补跑当天缺失缓存。
# 默认开，QF_NO_QUARTERLY=1 关。
_SCHED_HM = (22, 0)


def _seconds_until(hour: int, minute: int) -> float:
    now = _dt.datetime.now()
    nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if nxt <= now:
        nxt += _dt.timedelta(days=1)
    return (nxt - now).total_seconds()


async def quarterly_scheduler() -> None:
    """季报预增 / 净利润断层 每日定时生成；启动补跑当天缺失的缓存。"""
    await asyncio.sleep(60)  # 让启动其它预热先跑(尤其市场 K 线预热)
    try:
        if not _load_cache("preincrease"):
            await _generate_preincrease()
        if not _load_cache("jegap"):
            await _generate_jegap()
    except Exception as e:
        logger.warning(f"quarterly startup backfill failed: {e}")

    while True:
        try:
            await asyncio.sleep(max(60, _seconds_until(*_SCHED_HM)))
            await _generate_preincrease()
            await _generate_jegap()
            logger.info("quarterly: 季报预增/净利润断层 定时重算完成")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"quarterly scheduler loop error: {e}")
            await asyncio.sleep(300)


# ── API endpoints ──────────────────────────────────────────────────────────────

@router.get("/preincrease")
async def get_preincrease():
    """季报预增推荐（缓存优先；无缓存则后台启动 AI 分析并返回生成中占位）。"""
    cached = _load_cache("preincrease")
    if cached:
        cached["from_cache"] = True
        return cached
    # AI 分析较慢（可达数分钟），不阻塞首个请求：后台生成，返回 pending 占位。
    if not _RUNNING.get("preincrease"):
        asyncio.create_task(_generate_preincrease())
    return {
        "strategy": "preincrease", "strategy_label": "季报预增",
        "pending": True, "picks": [], "count": 0,
        "summary": "正在从机构荐股/研报/公众号/韭研公社搜集预增线索并 AI 分析，约 1-2 分钟后刷新查看…",
    }


@router.post("/preincrease/refresh")
async def refresh_preincrease(background_tasks: BackgroundTasks, force: bool = False):
    if _RUNNING.get("preincrease"):
        return {"status": "already_running", "message": "季报预增榜正在生成中"}
    if not force and _load_cache("preincrease"):
        return {"status": "fresh", "message": "今日季报预增榜已是最新"}
    background_tasks.add_task(_generate_preincrease)
    return {"status": "started", "message": "季报预增分析已在后台启动，约 1-2 分钟后刷新查看"}


@router.get("/jegap")
async def get_jegap():
    """今日净利润断层榜（缓存优先，缺则现场生成）。"""
    cached = _load_cache("jegap")
    if cached:
        cached["from_cache"] = True
        return cached
    return await _generate_jegap()


@router.post("/jegap/refresh")
async def refresh_jegap(background_tasks: BackgroundTasks, force: bool = False):
    """后台强制重算今日净利润断层榜。"""
    if _RUNNING.get("jegap"):
        return {"status": "already_running", "message": "净利润断层分析正在进行中"}
    if not force and _load_cache("jegap"):
        return {"status": "fresh", "message": "今日净利润断层榜已是最新"}
    background_tasks.add_task(_generate_jegap)
    return {"status": "started", "message": "净利润断层分析已在后台启动，约30秒后刷新查看"}


@router.get("/clue-log")
async def get_clue_log(strategy: str = "", days: int = 30):
    """每日线索日志：每天新增推荐了哪些股票（按策略，倒序）。

    strategy 为空返回两策略；否则只返回该策略（jegap / preincrease）。
    """
    log = _load_clue_log()
    def _trim(entries):
        return [e for e in entries if e.get("new")][:days]
    if strategy in ("jegap", "preincrease"):
        return {"strategy": strategy, "entries": _trim(log.get(strategy, []))}
    return {
        "jegap": _trim(log.get("jegap", [])),
        "preincrease": _trim(log.get("preincrease", [])),
    }


@router.get("/jegap/status")
async def jegap_status():
    """运行状态 + K 线缓存覆盖度（断层判定依赖本地日 K 缓存）。"""
    cached = _load_cache("jegap")
    try:
        from quantforge.data.storage import db_cache as _db
        kline_codes = await asyncio.to_thread(_db.kline_code_count, "day", 40)
        market_codes = await asyncio.to_thread(_db.quote_count)
    except Exception:
        kline_codes = market_codes = 0
    return {
        "running": bool(_RUNNING.get("jegap")),
        "has_today": cached is not None,
        "generated_at": cached.get("generated_at") if cached else None,
        "pick_count": len(cached.get("picks", [])) if cached else 0,
        "kline_cached_codes": kline_codes,
        "market_codes": market_codes,
    }
