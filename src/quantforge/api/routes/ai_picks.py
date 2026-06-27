"""AI daily stock picks — every day the AI analyses momentum buy-point candidates.

The pick count is NOT fixed at 10: every stock the momentum scan flags as a buy
point is recommended, ranked best → worst. The dashboard home panel shows only the
top 10; the full /ai-picks page lists them all.

Flow:
  1. Momentum-scan a liquid pool from the realtime snapshot
  2. Keep every stock at / near a buy point (ranked best → worst, capped for tokens)
  3. Enrich each candidate with latest market data (price, change%, technical signals)
  4. Send to Doubao AI with a structured prompt
  5. Parse JSON response → cache for 24 h per calendar date
  6. Return picks + market summary

荐股一天更新两次：午盘收盘后(11:30-13:00 之间触发，时段 ``midday``)与下午收盘后
(15:00 之后触发，时段 ``close``)。两次分别落盘、互不覆盖；首页/``daily`` 显示当天
**最新一次**。时段由触发时间自动判定，无需外部参数。

Endpoints:
  GET  /api/ai-picks/daily      → today's *latest* slot picks, ranked (cached)
  POST /api/ai-picks/refresh    → force regenerate in background
  GET  /api/ai-picks/history    → list of cached slots + performance preview
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import datetime as _dt
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from loguru import logger

router = APIRouter(prefix="/ai-picks", tags=["ai-picks"])

_CACHE_DIR = Path("data/cache/ai_picks")
_RUNNING: dict[str, bool] = {}   # per-strategy flag to avoid concurrent regeneration

# 选股策略：momentum(规则化动能买卖点，默认) / pring(普林格KST周期)。
# momentum 沿用旧缓存键(无策略后缀)以兼容历史文件；pring 用 ``_pring`` 后缀另存。
_STRATEGIES = {
    "momentum": "动能买点",
    "pring": "普林格KST周期",
    "ultra": "超短量价",
    "probe": "试盘点",
}
_DEFAULT_STRATEGY = "momentum"


def _norm_strategy(s: str | None) -> str:
    return s if s in _STRATEGIES else _DEFAULT_STRATEGY


# ── Cache helpers ──────────────────────────────────────────────────────────────

# 时段定义：荐股一天两次 —— 午盘收盘后(midday)、下午收盘后(close)。
# 触发时间落入哪个区间就归到哪个时段；同一时段内重复刷新覆盖同一份，跨时段新建。
_SLOT_CN = {
    "preopen": "盘前",
    "midday": "午盘",
    "intraday": "盘中",
    "close": "收盘后",
}
# 当天时段的展示先后顺序（用于挑「最新一次」）。越靠后越新。
_SLOT_ORDER = {"preopen": 0, "midday": 1, "intraday": 2, "close": 3}


def _current_slot(now: _dt.datetime | None = None) -> str:
    """按当前时间自动判定荐股时段。

    - <11:30            → 盘前 (preopen)
    - 11:30–13:00       → 午盘收盘后 (midday)   ← 第一次荐股
    - 13:00–15:00       → 盘中 (intraday)
    - ≥15:00            → 收盘后 (close)        ← 第二次荐股
    """
    now = now or _dt.datetime.now()
    hm = now.hour * 60 + now.minute
    if hm < 11 * 60 + 30:
        return "preopen"
    if hm < 13 * 60:
        return "midday"
    if hm < 15 * 60:
        return "intraday"
    return "close"


def _trade_date(now: _dt.datetime | None = None) -> _dt.date:
    """荐股归属的交易日：周末顺延到下周一；工作日即当天。"""
    now = now or _dt.datetime.now()
    day = now.date()
    while day.weekday() >= 5:   # 5=Sat, 6=Sun
        day += _dt.timedelta(days=1)
    return day


def _slot_key(now: _dt.datetime | None = None, strategy: str = _DEFAULT_STRATEGY) -> str:
    """当前应写入/读取的缓存键。

    - momentum: ``YYYY-MM-DD_slot``（不带策略后缀，兼容历史缓存文件）
    - 其它策略: ``YYYY-MM-DD_slot_<strategy>``
    """
    now = now or _dt.datetime.now()
    base = f"{_trade_date(now).isoformat()}_{_current_slot(now)}"
    strategy = _norm_strategy(strategy)
    return base if strategy == _DEFAULT_STRATEGY else f"{base}_{strategy}"


def _today_key() -> str:
    """兼容旧调用点：返回当前时段键。"""
    return _slot_key()


def _cache_path(key: str) -> Path:
    return _CACHE_DIR / f"{key}.json"


def _parse_key(stem: str) -> tuple[str, str, str]:
    """解析缓存文件名 → ``(date, slot, strategy)``。

    支持三种形态：
      ``2026-06-11``            → (date, close, momentum)  # 旧无时段文件
      ``2026-06-11_close``      → (date, close, momentum)
      ``2026-06-11_close_pring``→ (date, close, pring)
    """
    parts = stem.split("_")
    # 末段是策略名？
    strategy = _DEFAULT_STRATEGY
    if len(parts) >= 3 and parts[-1] in _STRATEGIES and parts[-1] != _DEFAULT_STRATEGY:
        strategy = parts[-1]
        parts = parts[:-1]
    if len(parts) >= 2 and parts[-1] in _SLOT_ORDER:
        return "_".join(parts[:-1]), parts[-1], strategy
    return stem, "close", strategy


def _latest_today(strategy: str = _DEFAULT_STRATEGY) -> dict | None:
    """加载今天**最新一份**的荐股（首页/daily 用），限定指定策略。

    「最新」= 生成时间(generated_at)最近的一份。早先按 slot 时段排序，但周末/节假日
    顺延会让上一交易日的「盘中」文件与本次「盘前」文件落到同一 trade_date 上、且 slot
    rank 更高，导致旧文件压过刚生成的新文件。改以 generated_at 为准、slot 时段为兜底，
    保证刷新后页面立刻拿到最新结果。
    """
    if not _CACHE_DIR.exists():
        return None
    strategy = _norm_strategy(strategy)
    today = _trade_date().isoformat()
    candidates = list(_CACHE_DIR.glob(f"{today}_*.json"))
    # 向后兼容：旧的无时段文件 (data/cache/ai_picks/2026-06-11.json) —— 仅 momentum
    if strategy == _DEFAULT_STRATEGY:
        legacy = _CACHE_DIR / f"{today}.json"
        if legacy.exists():
            candidates.append(legacy)

    best: tuple = ()
    best_payload: dict | None = None
    for f in candidates:
        _, slot, strat = _parse_key(f.stem)
        if strat != strategy:
            continue
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        # 主键 generated_at（字符串 ISO 可直接比较），兜底 slot rank 再兜底 mtime
        key = (payload.get("generated_at") or "", _SLOT_ORDER.get(slot, -1), f.stat().st_mtime)
        if not best or key > best:
            best = key
            best_payload = payload
    return best_payload


# 旧名保留为别名，调用点无需大改
def _load_today() -> dict | None:
    return _latest_today()


def _save(data: dict, key: str | None = None, strategy: str = _DEFAULT_STRATEGY):
    key = key or _slot_key(strategy=strategy)
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(key).write_text(
            json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"ai_picks cache save failed: {e}")


def _list_history(strategy: str | None = None) -> list[dict]:
    """返回缓存时段列表，按日期+时段倒序，附基础元数据。

    ``strategy`` 给定时只返回该策略的记录；为 None 时返回全部(含策略标记)。
    """
    if not _CACHE_DIR.exists():
        return []
    want = _norm_strategy(strategy) if strategy else None
    files = sorted(
        _CACHE_DIR.glob("*.json"),
        key=lambda f: (_parse_key(f.stem)[0], _SLOT_ORDER.get(_parse_key(f.stem)[1], 0)),
        reverse=True,
    )[:120]
    result = []
    for f in files:
        date, slot, strat = _parse_key(f.stem)
        if want and strat != want:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result.append({
                "key": f.stem,
                "date": date,
                "slot": slot,
                "slot_label": _SLOT_CN.get(slot, slot),
                "strategy": strat,
                "strategy_label": _STRATEGIES.get(strat, strat),
                "generated_at": data.get("generated_at", ""),
                "pick_count": len(data.get("picks", [])),
                "no_buy_point": data.get("no_buy_point", False),
                "market_summary": data.get("market_summary", ""),
            })
        except Exception:
            continue
    return result


# ── Candidate collection — momentum buy/sell points (no strategy screener) ──────

# 全市场扫描：不再限制扫描池大小，对快照里**所有**已缓存 K 线的票算动能。
# K 线由后台 market_kline_warmer 预热灌库，扫描只读缓存（不现拉），所以并发可拉高。
# **不再对买点候选数设硬上限**：全部买点票都交给 AI，靠 map-reduce 分批并发跑 +
# 汇总，规避单次 prompt token / 超时限制（见 ``_call_ai``）。
_FALLBACK_TOP = 10      # if nothing is at a clean buy point, hand over this many best-scored
# **不再对 AI 产出（展示）只数设上限**：用户要求荐股不设 30 只限制，AI 选出多少全部展示。
_MAX_AI_CANDIDATES = 400  # 交给 AI 的候选安全上限——极端日买点暴多时防 token/成本爆，常态不触发
_MOMO_DAYS = 180        # K-line history for momentum scoring
_MOMO_CONCURRENCY = 24  # 只读 DB，可高并发；I/O 轻、无网络
_MIN_TURNOVER_YI = 0.3  # 最低成交额(亿)过滤——剔除几乎不成交的僵尸股，留流动性
_RECENT_ENTRY_DAYS = 0  # 「当日首次买入」窗口：买入信号穿越须发生在最新一根 K 线(0=今日)才算新买点

# ── Map-reduce 分批跑 AI ─────────────────────────────────────────────────────────
# 全量买点票（可能上百只）一次性塞进单条 prompt 会超 token / 超时，所以按 batch
# 切片，每片并发调一次 AI（map），各片独立产 picks，最后汇总合并（reduce）。
_AI_BATCH_SIZE = 25     # 每批喂给 AI 的候选数（单条 prompt 体量适中、产出稳定）
_AI_BATCH_CONCURRENCY = 4  # 并发批次数；太高会触发 LLM 限流/过载(529)

# ── 超短量价策略 (ultra) ─────────────────────────────────────────────────────
# 盘前集合竞价 09:20–09:25 选股、每 30s 滚动更新；**纯规则化、不走 AI**（AI 既慢又贵，
# 不适合 30s 高频刷新）。选股条件（须全部满足）：
#   1. 创业板(300/301) 或 科创板(688/689)
#   2. 5 日均量「首次」上穿 60 日均量（昨日尚未上穿、最新一根上穿——量能突破）
#   3. 今日涨幅 ≥ 3%（集合竞价/实时）
#   4. 近 10 个交易日累计涨幅 ≤ 20%（未过热、留出空间）
# 量能上穿与近 10 日涨幅来自**已收盘的日 K 缓存**（窗口内固定不变）；每 30s 变化的是
# 集合竞价的今日涨幅（实时拉取），故扫描分两段：先用缓存做历史筛，再实时校验今日涨幅。
_ULTRA_TODAY_GAIN_MIN = 3.0      # 今日涨幅下限(%)
_ULTRA_RECENT10_MAX = 20.0       # 近 10 日累计涨幅上限(%)
_ULTRA_VOL_SHORT = 5             # 短均量窗口
_ULTRA_VOL_LONG = 60            # 长均量窗口
_ULTRA_BOARDS = ("300", "301", "688", "689")  # 创业板 / 科创板代码前缀
_ULTRA_STOP_PCT = 5.0            # 超短止损幅度
_ULTRA_TARGET_PCT = 10.0         # 超短目标涨幅
# 盘前竞价扫描窗口与节奏（后台 ultra_scalp_scanner 用）
_ULTRA_WIN_START = 9 * 60 + 20   # 09:20
_ULTRA_WIN_END = 9 * 60 + 25     # 09:25
_ULTRA_SCAN_INTERVAL = 30        # 窗口内每 30 秒重扫一次

# ── 试盘线策略 (probe) ───────────────────────────────────────────────────────
# 「试盘」= 大资金拉升前的战前侦察：用一小部分资金突然放量拉抬，制造长上影、低位
# 突破前期高点的盘口，借机测试上方抛压与跟风盘。识别**近一个月内**形成试盘线的个股，
# 并判定当前价位相对试盘线的多空（线上看多、线下看空）。纯规则化、不走 AI。
# 试盘日须全部满足（doc 原文筛选条件）：
#   1. 非 ST、非北交所(4/8/920 开头)
#   2. 试盘日收盘价 < 80
#   3. 试盘日涨幅 0 < x ≤ 9.8%（当日未涨停）
#   4. 前一日未涨停
#   5. 试盘日成交量 ≥ 前一日 3 倍
#   6. 长上影线：上影 ≥ 实体 1 倍 且 ≥ 当日(高-低) 的 1/3
#   7. 低位突破前期高点：当日最高价创近 N 日新高，且此前未大涨（仍在低位）
_PROBE_LOOKBACK_DAYS = 22       # 「近一个月」：试盘日须落在最近 22 根 K 线内
_PROBE_PRIOR_HIGH_WIN = 20      # 「前期高点」回看窗口：突破近 20 日最高价（放宽：原 30）
_PROBE_VOL_MULT = 2.5           # 量能倍数：当日量 ≥ 前一日 2.5 倍（放宽：原 3.0，多招回）
_PROBE_PRICE_MAX = 80.0         # 股价上限
_PROBE_GAIN_MIN = 0.0           # 当日涨幅下限（须 > 0）
_PROBE_GAIN_MAX = 9.8           # 当日涨幅上限（未涨停）
_PROBE_UPPER_BODY_MULT = 0.7    # 上影线 ≥ 实体的倍数（放宽：原 1.0）
_PROBE_UPPER_RANGE_FRAC = 0.28  # 上影线 ≥ 当日(高-低) 的比例（放宽：原 0.33）
_PROBE_RUNUP_WIN = 20           # 「低位」判定：试盘日前累计涨幅回看窗口
_PROBE_RUNUP_MAX = 45.0         # 试盘日前近 20 日累计涨幅上限（放宽：原 35）
# 止损分级（doc 原文）：跌破试盘线下方 3 个点=黄牌警告，5 个点=红牌罚下(无条件离场)
_PROBE_WARN_PCT = 3.0           # 黄牌：试盘线下方 3% 警告
_PROBE_STOP_PCT = 5.0           # 红牌：试盘线下方 5% 止损
_PROBE_TARGET_PCT = 15.0        # 目标涨幅
_PROBE_BOARDS_20 = ("300", "301", "688", "689")  # 涨停 20% 的板块前缀
# 试盘后 3-7 日的健康确认（doc 原文）：缩量回踩——量能萎缩至试盘日 30%-50% 且不破试盘最低点
_PROBE_POST_WIN = 7             # 试盘日后观察窗口（个交易日）
_PROBE_PULLBACK_VOL_MAX = 0.5   # 回踩日量能 ≤ 试盘日 50%（缩量到位）
_PROBE_GIVEUP_VOL = 0.8         # 试盘失败判定：放量(≥试盘日 80%)下跌且破试盘最低点=主力放弃
# 大盘跳水日排除：试盘日若沪深300当日跌幅 ≤ 此阈值，长上影多为大盘拖累而非主力试盘，剔除
_PROBE_INDEX_CRASH = -1.2       # 沪深300 当日涨跌幅(%) ≤ -1.2 视为「大盘跳水日」
# 入场机会已过排除：试盘日收盘 → 今日现价已涨超此幅度，则追高风险大，不再推荐
_PROBE_MAX_RISE_SINCE = 18.0    # 试盘线至今涨幅上限(%)


def _mcap_to_yi(v) -> float | None:
    """Normalise snapshot market_cap (元) to 亿. Values already in 亿 pass through."""
    f = _safe_float(v)
    if f is None or f <= 0:
        return None
    return round(f / 1e8, 1) if f > 1e6 else round(f, 1)


def _load_bars_for_momentum(code: str) -> list[dict]:
    """Daily OHLCV via the shared loader chain (DB kline → parquet → efinance)."""
    try:
        from quantforge.api.routes.stock_analysis import _load_bars
        return _load_bars(code, _MOMO_DAYS)
    except Exception as e:
        logger.debug(f"ai_picks: bars load failed for {code}: {e}")
        return []


def _load_bars_cache_only(code: str) -> list[dict]:
    """全市场扫描专用：**只读本地 stock_kline 缓存，绝不触发网络拉取**。

    全市场 5000 只若逐只现拉会很慢且触发限流；K 线由后台 ``market_kline_warmer``
    预热灌库，这里命中多少扫多少。未预热的票返回空、被扫描跳过。
    """
    try:
        from quantforge.data.storage import db_cache as _db
        bars = _db.kline_load(str(code).strip().upper(), "day", _MOMO_DAYS)
        # 补 change_pct（表里可能为 0/缺），动能模型只用 OHLCV，这里直接返回即可
        return bars or []
    except Exception as e:
        logger.debug(f"ai_picks: cache-only bars load failed for {code}: {e}")
        return []


# 大盘基准代码：四维动能里「维度3·与大盘比较」的相对强弱参照（与 predictions 基准同源）
_BENCHMARK_CODE = "SH000300"


def _load_benchmark_bars() -> list[dict]:
    """加载沪深300 日 K（缓存优先，过期则补拉），作为四维动能维度3 的**大盘**基准。

    个股若能映射到所属行业板块，维度3 优先用「行业板块指数」(见 ``_build_sector_benchmarks``)；
    映射不到才退回这条大盘基准。一次加载、全市场复用；取不到返回空、维度3 优雅降级。
    """
    try:
        from quantforge.data.storage import db_cache as _db
        bars = _db.kline_load(_BENCHMARK_CODE, "day", _MOMO_DAYS)
        if not bars or bars[-1].get("date", "") < _dt.date.today().isoformat():
            try:
                from quantforge.api.routes.market import _kline_fetch
                fetched = _kline_fetch(_BENCHMARK_CODE, "day", max(_MOMO_DAYS, 320))
                if fetched:
                    _db.kline_upsert(_BENCHMARK_CODE, "day", fetched)
                    bars = _db.kline_load(_BENCHMARK_CODE, "day", _MOMO_DAYS)
            except Exception:
                pass
        return bars or []
    except Exception as e:
        logger.debug(f"ai_picks: benchmark bars load failed: {e}")
        return []


# ── 行业板块基准：把个股的「维度3·与大盘比较」升级为「与所属板块比较」 ────────────────
# 板块没有现成指数日 K（快照只有当日涨跌幅）。但 sector_constituents 表(行业 kind，由
# sector_summary_warmer 落库)给了每个行业的成分股名单；个股日 K 已被 market_kline_warmer
# 灌进缓存。于是用「成分股等权日收益」合成一条行业指数日 K（base 100），作为该行业全部
# 个股的相对强弱基准。整套映射按交易日缓存，一天两次荐股复用同一份。
_SECTOR_MIN_CONSTITUENTS = 8    # 成分股可评分数不足此值的行业不建指数（样本太小不稳）
_SECTOR_CAP_CONSTITUENTS = 120  # 每行业最多取多少成分股建指数（控成本；新浪行业平均~58只，多数全覆盖）
_SECTOR_BENCH_CACHE: dict[str, tuple] = {}   # {trade_date: (code_to_sector, sector_bars)}


def _equal_weight_index(closes_by_code: dict[str, dict[str, float]]) -> list[dict]:
    """把多只成分股的 {date: close} 合成等权指数日 K（base 100）。

    各成分股按自身首个有效收盘归一（消除价格量纲差异），再按日横向求均值（停牌/
    晚上市的成分股在其上市前不计入当日均值）。返回升序 ``[{date, close}]``。
    """
    import pandas as pd
    if len(closes_by_code) < _SECTOR_MIN_CONSTITUENTS:
        return []
    df = pd.DataFrame({c: pd.Series(s) for c, s in closes_by_code.items()}).sort_index()
    df = df.ffill()
    first = df.bfill().iloc[0]              # 每列首个有效值（已 ffill，bfill 取首个）
    norm = df.divide(first, axis=1)
    level = norm.mean(axis=1, skipna=True) * 100.0
    return [{"date": str(d), "close": round(float(v), 4)}
            for d, v in level.items() if pd.notna(v)]


def _build_sector_benchmarks() -> tuple[dict[str, str], dict[str, list[dict]]]:
    """构建 ``(code→行业名, 行业名→行业指数日K)``，按交易日缓存、一天复用。

    数据来源：``sector_constituents`` 表(行业 kind)给成分股名单，个股日 K 走只读缓存。
    任一环节缺失则该行业不建指数、其个股回退到大盘基准。
    """
    day = _trade_date().isoformat()
    cached = _SECTOR_BENCH_CACHE.get(day)
    if cached is not None:
        return cached

    from quantforge.data.storage import db_cache as _db
    boards = _db.get_sector_boards("industry") or []
    code_to_sector: dict[str, str] = {}
    sector_bars: dict[str, list[dict]] = {}

    for b in boards:
        name = (b.get("name") or "").strip()
        if not name:
            continue
        cons = _db.get_sector_constituents("industry", name) or []
        # 表里按当日涨跌幅排序；建指数前改按代码排序去除「取头部=取今日领涨」的偏置，
        # 否则等权指数会被当天涨得多的成分股拉高、虚增板块强度。
        cons = sorted(cons, key=lambda s: (s.get("code") or ""))
        closes_by_code: dict[str, dict[str, float]] = {}
        for s in cons[:_SECTOR_CAP_CONSTITUENTS]:
            code = (s.get("code") or "").strip()
            if not code:
                continue
            code_to_sector.setdefault(code.zfill(6), name)   # 先登记归属（即便没缓存）
            bars = _load_bars_cache_only(code)
            if not bars or len(bars) < 30:
                continue
            cm = {str(x["date"]): _safe_float(x.get("close"))
                  for x in bars if x.get("date") and _safe_float(x.get("close"))}
            if cm:
                closes_by_code[code] = cm
        idx = _equal_weight_index(closes_by_code)
        if idx:
            sector_bars[name] = idx

    result = (code_to_sector, sector_bars)
    _SECTOR_BENCH_CACHE.clear()           # 只保留当日一份，防跨日累积
    _SECTOR_BENCH_CACHE[day] = result
    logger.info(
        f"ai_picks: 行业基准构建完成 —— {len(boards)} 个行业, "
        f"{len(sector_bars)} 个建成指数, 覆盖 {len(code_to_sector)} 只个股映射"
    )
    return result


# ── 行业 / 概念分类映射：供前端按行业或概念筛选已生成的推荐 ─────────────────────────
# 一只股票通常属一个行业、多个同花顺概念。映射来自 sector_constituents 表
# (industry kind 给行业、concept kind 给概念，均由后台 warmer 落库)。按交易日缓存、
# 一天复用；首次构建会遍历全部行业+概念板块的成分股，之后命中缓存即返回。
_CLASSIFY_CACHE: dict[str, dict[str, dict]] = {}


def _build_code_classification() -> dict[str, dict]:
    """``code(zfill6) → {"industry","sw_industry","concepts":[...]}``，按交易日缓存。

    ``industry`` = 新浪行业(旧维度)；``sw_industry`` = 申万一级行业(动能买点页筛选用)；
    ``concepts`` = 同花顺概念成分。三者均由后台 warmer 落库，缺失则该字段留空。
    """
    day = _trade_date().isoformat()
    cached = _CLASSIFY_CACHE.get(day)
    if cached is not None:
        return cached

    from quantforge.data.storage import db_cache as _db
    out: dict[str, dict] = {}

    def _rec(code: str) -> dict:
        return out.setdefault(code, {"industry": None, "sw_industry": None, "concepts": []})

    try:
        for b in (_db.get_sector_boards("industry") or []):
            name = (b.get("name") or "").strip()
            if not name:
                continue
            for s in (_db.get_sector_constituents("industry", name) or []):
                code = (s.get("code") or "").strip().zfill(6)
                if code:
                    _rec(code)["industry"] = name
        # 申万一级行业（只读 DB，sw_industry_warmer 落库；不触网）
        try:
            from quantforge.data.feed import sw_industry as _sw
            for code, sw_name in (_sw.get_sw_industry_map() or {}).items():
                if code and sw_name:
                    _rec(code)["sw_industry"] = sw_name
        except Exception as e:
            logger.debug(f"ai_picks: 申万分类合并失败: {e}")
        for b in (_db.get_sector_boards("concept") or []):
            name = (b.get("name") or "").strip()
            if not name:
                continue
            for s in (_db.get_sector_constituents("concept", name) or []):
                code = (s.get("code") or "").strip().zfill(6)
                if not code:
                    continue
                rec = _rec(code)
                if name not in rec["concepts"]:
                    rec["concepts"].append(name)
    except Exception as e:
        logger.warning(f"ai_picks: classification build failed: {e}")

    _CLASSIFY_CACHE.clear()
    _CLASSIFY_CACHE[day] = out
    logger.info(f"ai_picks: 行业/概念分类映射构建完成 —— 覆盖 {len(out)} 只个股")
    return out


def _apply_classification(payload: dict | None, cls: dict[str, dict]) -> dict | None:
    """给 payload.picks 逐只补 ``industry`` / ``concepts`` 字段（前端行业/概念筛选用）。

    行业优先沿用已有 ``sector``（动能策略附的权威行业归属），缺失才用映射补；
    概念恒取自映射。原地修改并返回 payload。
    """
    if not payload or not isinstance(payload, dict):
        return payload
    for p in (payload.get("picks") or []):
        code = (p.get("code") or "").strip().zfill(6)
        info = cls.get(code) or {}
        if not p.get("sector") and info.get("industry"):
            p["sector"] = info["industry"]
        p["industry"] = p.get("sector") or info.get("industry") or ""
        p["sw_industry"] = info.get("sw_industry") or ""
        p["concepts"] = info.get("concepts") or []
    return payload


async def _enrich_classification(payload: dict | None) -> dict | None:
    """异步包装：在线程里构建/取分类映射，再原地补到 picks（不阻塞事件循环）。"""
    if not payload or not (payload.get("picks") or []):
        return payload
    cls = await asyncio.to_thread(_build_code_classification)
    return _apply_classification(payload, cls)


# ── 板块剔除：保险 / 银行 / 证券 ─────────────────────────────────────────────────
# 用户要求 AI 荐股剔除保险、银行、证券板块的个股。
#
# 数据现状：快照表无行业列；新浪行业分类把银行/证券/保险全并进一个「金融行业」板块
# （太粗，会误伤信托/期货/多元金融），新浪概念里只有「保险重仓/券商重仓」(被持仓口径
# 而非成分)。故采用「股名关键字 + 显式代码名单」双重剔除，纯本地判定、不依赖网络：
#   · 关键字：名称含「银行/证券/保险」的几乎涵盖全部银行、绝大多数券商及部分险企；
#   · 显式名单：补齐名称里不含关键字的金融龙头（中国平安、东方财富、国泰海通…）。
_EXCLUDE_NAME_KEYWORDS = ("银行", "证券", "保险")

# 名称不含上述关键字、但属保险/证券板块的个股（6位代码）。银行类名称均含「银行」无需补。
_EXCLUDE_CODES: frozenset[str] = frozenset({
    # 保险
    "601318",  # 中国平安
    "601628",  # 中国人寿
    "601601",  # 中国太保
    "601319",  # 中国人保
    "000627",  # 天茂集团（旗下国华人寿）
    # 证券 / 券商
    "601211",  # 国泰海通（原国泰君安）
    "300059",  # 东方财富（互联网券商）
    "601066",  # 中信建投
    "000712",  # 锦龙股份（参控东莞/中山证券）
    "600705",  # 中航产融
    "600864",  # 哈投股份（旗下江海证券）
    "000987",  # 越秀资本（旗下广州期货/证券）
    "600095",  # 湘财股份（湘财证券）
    "600155",  # 华创云信（华创证券）
})


def _excluded_codes() -> frozenset[str]:
    """需按代码剔除的个股集合（保险/证券板块中名称不含关键字者）。"""
    return _EXCLUDE_CODES


# ── 老登股剔除：传统周期 / 地产 / 交运 / 纺服等行业 ─────────────────────────────────
# 用户要求 AI 荐股在第一步过滤即剔除「老登股」——即建筑装饰/环保工程/房地产开发/园区开发/
# 家用轻工/纺织制造/服装家纺/钢铁/非汽车交运/交运设备服务/港口航运/公路铁路运输/公交/
# 机场航运/物流/包装印刷/综合 这些传统周期与公用行业。上列是申万口径行业名；本地没有
# 申万映射（快照表无行业列，efinance/push2 又被代理劫持不可用），故映射到库里**新浪行业**
# 板块(sector_constituents 的 industry kind)取成分股代码并集来命中。
#
# 注意取舍：新浪行业把交运细分(港口/航运/公路/铁路/公交/机场/物流)全并进「交通运输」+
# 「公路桥梁」两板块，正好一并剔除；但对建筑装饰/中字头基建覆盖很差(中国建筑/东方雨虹等
# 根本没分进任何新浪板块)，故用显式代码名单补齐。不剔「飞机制造」(军工/航空装备非老登)、
# 不剔「汽车制造」(用户口径为非汽车交运)。纯本地判定、按板块成分代码命中，prod 同样可用。
_LAODENG_SINA_BOARDS: tuple[str, ...] = (
    "房地产",      # 房地产开发
    "开发区",      # 园区开发
    "环保行业",    # 环保工程
    "家具行业",    # 家用轻工
    "纺织行业",    # 纺织制造
    "纺织机械",    # 纺织制造（设备）
    "服装鞋类",    # 服装家纺
    "钢铁行业",    # 钢铁
    "船舶制造",    # 非汽车交运（船舶）
    "交通运输",    # 港口航运/公交/机场航运/物流/交运设备服务
    "公路桥梁",    # 公路铁路运输
    "印刷包装",    # 包装印刷
    "综合行业",    # 综合
    "其它行业",    # 综合（杂项）
    "建筑建材",    # 建筑装饰（新浪覆盖极少，配合下方代码名单）
)

# 新浪行业漏分的建筑装饰 / 中字头基建龙头（6位代码，已逐一核名）。
_LAODENG_EXTRA_CODES: frozenset[str] = frozenset({
    "601668",  # 中国建筑
    "601390",  # 中国中铁
    "601186",  # 中国铁建
    "601800",  # 中国交建
    "601669",  # 中国电建
    "601117",  # 中国化学
    "601868",  # 中国能建
    "600170",  # 上海建工
    "600820",  # 隧道股份
    "002271",  # 东方雨虹
    "000786",  # 北新建材
    "002791",  # 坚朗五金
    "002541",  # 鸿路钢构
    "002081",  # 金螳螂
    "002375",  # 亚厦股份
    "601886",  # 江河集团
    "002047",  # 宝鹰股份
})

_LAODENG_CACHE: dict[str, frozenset[str]] = {}   # {trade_date: 代码集合}，一天复用


def _laodeng_codes() -> frozenset[str]:
    """老登股代码集合 = 指定新浪行业板块成分 ∪ 显式补充名单。按交易日缓存、一天复用。

    ``QF_NO_LAODENG_FILTER=1`` 可整体关闭（返回空集，第一步过滤即不剔老登）。
    """
    if os.environ.get("QF_NO_LAODENG_FILTER") == "1":
        return frozenset()
    from quantforge.data.storage import db_cache as _db

    key = _dt.date.today().isoformat()
    cached = _LAODENG_CACHE.get(key)
    if cached is not None:
        return cached

    codes: set[str] = set(_LAODENG_EXTRA_CODES)
    for board in _LAODENG_SINA_BOARDS:
        for s in (_db.get_sector_constituents("industry", board) or []):
            c = str(s.get("code") or "").strip()
            if c:
                codes.add(c.zfill(6))
    result = frozenset(codes)
    _LAODENG_CACHE[key] = result
    logger.info(
        f"ai_picks: 老登股剔除名单构建 —— {len(result)} 只"
        f"（{len(_LAODENG_SINA_BOARDS)} 个新浪行业 ∪ 补充 {len(_LAODENG_EXTRA_CODES)} 只）"
    )
    return result


def _build_pool() -> tuple[list[dict], int]:
    """全市场池：分页取全部快照行，按基础规则过滤（剔退市/低成交额/保险银行证券/老登行业；保留 ST、保留涨停）。

    返回 ``(过滤后的池, 全市场快照总数)``——后者用于漏斗第一级展示。
    """
    from quantforge.data.storage import db_cache as _db

    excluded = _excluded_codes()
    laodeng = _laodeng_codes()   # 老登股（传统周期/地产/交运/纺服等行业）代码集合

    pool: list[dict] = []
    page = 1
    market_total = 0
    while True:
        rows, total = _db.quote_query(page=page, page_size=500)
        market_total = total or market_total
        if not rows:
            break
        for r in rows:
            code = (r.get("code") or "").strip()
            name = (r.get("name") or "")
            # 不剔除 ST（用户要求 AI 荐股保留 ST）；仅剔退市股（基本无法交易）
            if not code or "退" in name:
                continue
            # 剔除保险/银行/证券板块：股名关键字 + 显式代码名单
            if any(k in name for k in _EXCLUDE_NAME_KEYWORDS) or code.zfill(6) in excluded:
                continue
            # 剔除老登股：传统周期/地产/交运/纺服等行业（新浪行业成分 + 中字头基建名单）
            if code.zfill(6) in laodeng:
                continue
            # 不剔除涨停（用户要求 AI 荐股保留涨停标的）
            to = _safe_float(r.get("turnover"))  # 成交额(元)
            if to is not None and to > 0 and to < _MIN_TURNOVER_YI * 1e8:
                continue                          # 成交额过低的僵尸股剔除
            pool.append(r)
        if (market_total and len(pool) >= market_total) or len(rows) < 500:
            break
        page += 1
    return pool, market_total or len(pool)


def _base_cand(r: dict) -> dict:
    """从快照行抽出与策略无关的公共字段。"""
    return {
        "code": (r.get("code") or "").strip(),
        "name": r.get("name", ""),
        "price": _safe_float(r.get("price")),
        "change_pct": _safe_float(r.get("change_pct")),
        "pe": _safe_float(r.get("pe")),
        "pb": _safe_float(r.get("pb")),
        "turnover_rate": _safe_float(r.get("turnover_rate")),
        "market_cap": _mcap_to_yi(r.get("market_cap")),
    }


def _scan_momentum(r: dict, bars: list[dict], cfg, benchmark_bars: list[dict] | None = None,
                   benchmark_label: str = "大盘") -> dict | None:
    from quantforge.analysis.momentum import compute_momentum
    try:
        mom = compute_momentum(bars, cfg, benchmark_bars=benchmark_bars,
                               benchmark_label=benchmark_label)
    except Exception as e:
        logger.debug(f"ai_picks: momentum failed for {r.get('code')}: {e}")
        return None
    cur = mom.get("current") or {}
    score = _safe_float(cur.get("score")) or 0.0
    state = cur.get("state")
    last_sig = (mom.get("signals") or [])[-1:] or [{}]
    sig = last_sig[0]
    # 只认**当日首次买入**：当前处于 buy，且最后一个信号是 buy（state 由非买入
    # 翻成 buy 的那次穿越——`_extract_signals` 只记录状态转换，故它天然是「首次提
    # 示买入」而非「持有 buy 多日」），且该穿越恰好落在最新一根 K 线（bars_ago==0）。
    # 即只推「今天才冒头」的全新买点，持有多日或滞后几天的旧买点一律不算。
    bars_ago = None
    if state == "buy" and sig.get("type") == "buy":
        sig_date = str(sig.get("date") or "")
        if sig_date:
            bar_dates = [str((b or {}).get("date") or "") for b in bars]
            try:
                # 从尾部找该买入信号所在 K 线，算距今多少根（0 = 最后一根/今天）
                bars_ago = bar_dates[::-1].index(sig_date)
            except ValueError:
                bars_ago = None
    entry = bars_ago is not None and bars_ago <= _RECENT_ENTRY_DAYS
    c = _base_cand(r)
    c["_entry"] = bool(entry)
    c["momentum"] = {
        "entry_bars_ago": bars_ago,   # 距今多少个交易日前首次提示买入（0=今日）
        "score": round(score, 1),
        "state": state,
        "direction": cur.get("direction"),
        "dimensions": cur.get("dimensions"),   # 四维动能（自身历史/与价格/与大盘/反向）
        "rsi": _safe_float(cur.get("rsi")),
        "buy_price": _safe_float(cur.get("buy_price")),
        "stop_price": _safe_float(cur.get("stop_price")),
        "target_price": _safe_float(cur.get("target_price")),
        "stop_pct": _safe_float(cur.get("stop_pct")),
        "target_pct": _safe_float(cur.get("target_pct")),
        "rr": _safe_float(cur.get("rr")),
        "support": _safe_float(cur.get("support")),
        "resistance": _safe_float(cur.get("resistance")),
        "last_signal": last_sig[0],
    }
    return c


def _scan_pring(r: dict, bars: list[dict], cfg) -> dict | None:
    """普林格 KST 周期扫描：买点 = 零轴下方/附近金叉 + 长周期向上 + 站上MA50。"""
    from quantforge.analysis import pring
    try:
        k = pring.analyze(bars, cfg)
    except Exception as e:
        logger.debug(f"ai_picks: pring failed for {r.get('code')}: {e}")
        return None
    if not k:
        return None
    # 普林格 KST 不卡「首次买入点」：凡处于多头(站上信号线+长周期向上，
    # 即 state ∈ {buy, hold})即纳入，按 KST 评分排序。不要求严格低位金叉。
    entry = k.get("state") in ("buy", "hold")
    c = _base_cand(r)
    c["_entry"] = bool(entry)
    # 复用 momentum 字段位承载价位/评分，前端与下游 reconcile 无需区分策略；
    # pring 专属信息(KST/阶段/金叉)放在 momentum 里附带字段。
    c["momentum"] = {
        "score": k.get("score"),
        "state": k.get("state"),
        "direction": k.get("direction"),
        "buy_price": k.get("buy_price"),
        "stop_price": k.get("stop_price"),
        "target_price": k.get("target_price"),
        "stop_pct": k.get("stop_pct"),
        "target_pct": k.get("target_pct"),
        "rr": k.get("rr"),
        "support": k.get("support"),
        "resistance": k.get("resistance"),
        "kst": k.get("kst"),
        "kst_signal": k.get("kst_signal"),
        "stage": k.get("stage"),
        "stage_label": k.get("stage_label"),
        "golden_cross": k.get("golden_cross"),
        "ma50": k.get("ma50"),
        "last_signal": k.get("last_signal", {}),
    }
    return c


async def _collect_candidates(strategy: str = _DEFAULT_STRATEGY) -> tuple[list[dict], bool, dict]:
    """全市场扫描，按 ``strategy`` 产出候选买点，并返回逐级漏斗计数。

    流程（即漏斗各级）：
    1. 从行情快照取**全市场**股票（market_total），剔退市/极低成交额/保险银行证券/老登行业（保留 ST、保留涨停）→ after_filter。
    2. 对每只**只读本地 K 线缓存**算所选策略指标（缓存由后台预热，未缓存跳过）→ scored。
    3. 保留处于该策略明确买点的标的（buy_points），按评分从好到坏排序。
    4. **全部买点**交给 AI（selected，map-reduce 分批跑）；无买点时回退到评分最好的若干只。
       AI 产出不再截断，选出多少全部展示（见 ``_generate``）。

    返回 ``(chosen, has_buy_point, funnel)``，funnel 为各级计数字典。
    """
    strategy = _norm_strategy(strategy)

    if strategy == "pring":
        from quantforge.analysis.pring import PringConfig
        cfg = PringConfig()
        scan_fn = _scan_pring
    else:
        from quantforge.analysis.momentum import MomentumConfig
        cfg = MomentumConfig()
        scan_fn = _scan_momentum

    pool, market_total = _build_pool()
    funnel = {
        "market_total": market_total,   # 全市场快照总数
        "after_filter": len(pool),      # 剔退市/低成交额后（保留 ST/涨停）
        "scored": 0,                    # 有 K 线缓存、可算指标
        "buy_points": 0,                # 处于该策略明确买点
        "selected": 0,                  # 交给 AI 的候选数（全部买点）
        "cap": 0,                       # AI 产出无上限（0=不限）；recommended 为实际产出数
    }
    if not pool:
        logger.warning("ai_picks: snapshot empty, no scan pool available")
        return [], False, funnel

    # 四维动能维度3 的基准（momentum 策略才需要）：
    #   · 行业基准 = 个股所属行业的等权指数（优先，更贴近「板块相对强弱」）
    #   · 大盘基准 = 沪深300（个股映射不到行业时回退）
    # 两者各加载一次、全市场复用。
    benchmark_bars = None
    code_to_sector: dict[str, str] = {}
    sector_bars: dict[str, list[dict]] = {}
    if strategy == "momentum":
        benchmark_bars = await asyncio.to_thread(_load_benchmark_bars)
        code_to_sector, sector_bars = await asyncio.to_thread(_build_sector_benchmarks)
        if not benchmark_bars and not sector_bars:
            logger.warning("ai_picks: 大盘/行业基准均缺失，四维动能「维度3」本轮退出加权")

    # 只读缓存的全市场扫描（高并发，无网络）
    sem = asyncio.Semaphore(_MOMO_CONCURRENCY)

    async def _scan(r: dict) -> dict | None:
        async with sem:
            bars = await asyncio.to_thread(_load_bars_cache_only, (r.get("code") or "").strip())
        if not bars or len(bars) < 40:
            return None
        if scan_fn is _scan_momentum:
            code6 = (r.get("code") or "").strip().zfill(6)
            sector = code_to_sector.get(code6)
            sbars = sector_bars.get(sector) if sector else None
            # 行业指数够长就用行业、否则回退大盘
            if sbars and len(sbars) >= 40:
                res = _scan_momentum(r, bars, cfg, sbars, benchmark_label=sector)
            else:
                res = _scan_momentum(r, bars, cfg, benchmark_bars, benchmark_label="大盘")
            # 附权威行业归属（来自 sector_constituents 映射，比 AI 自填可靠），供前端分板块筛选
            if res is not None and sector:
                res["sector"] = sector
            return res
        return scan_fn(r, bars, cfg)

    scanned = await asyncio.gather(*[_scan(r) for r in pool])
    cands = [c for c in scanned if c]

    # rank best → worst by score
    cands.sort(key=lambda x: -(x["momentum"]["score"] or 0))
    entries = [c for c in cands if c["_entry"]]
    funnel["scored"] = len(cands)
    funnel["buy_points"] = len(entries)
    # 全部买点都交给 AI 选（map-reduce 分批跑，规避单 prompt token/超时），不在入口截断，
    # AI 产出也不再截断。仅保留极端日的安全上限防成本爆。无买点时回退评分最好的若干只。
    has_buy_point = bool(entries)
    base = entries if entries else cands[:_FALLBACK_TOP]
    chosen = base[:_MAX_AI_CANDIDATES]
    funnel["selected"] = len(chosen)
    logger.info(
        f"ai_picks[{strategy}]: 漏斗 全市场{market_total} → 过滤后{len(pool)} → "
        f"可评分{len(cands)} → 买点{len(entries)} → 交给AI{len(chosen)}(产出不限)"
        + ("" if len(cands) >= len(pool) * 0.5 else "（缓存命中偏低，K线预热可能尚未跑完）")
    )
    return chosen, has_buy_point, funnel


# ── 超短量价策略 (ultra) ─────────────────────────────────────────────────────

def _is_ultra_board(code: str) -> bool:
    """是否创业板/科创板（按 6 位代码前缀）。"""
    return (code or "").strip().zfill(6).startswith(_ULTRA_BOARDS)


def _build_ultra_pool() -> tuple[list[dict], int]:
    """创业板/科创板池：分页取快照行，仅剔退市股，按板块前缀过滤（不剔 ST）。

    **不在此处按涨幅/成交额过滤**——今日涨幅留到实时阶段校验（集合竞价时快照涨幅可能
    尚未更新），且创业板/科创板涨停为 20%，用主板的「近涨停」阈值会误杀。
    返回 ``(过滤后的池, 创业板+科创板总数)``。
    """
    from quantforge.data.storage import db_cache as _db

    pool: list[dict] = []
    page = 1
    board_total = 0
    while True:
        rows, total = _db.quote_query(page=page, page_size=500)
        if not rows:
            break
        for r in rows:
            code = (r.get("code") or "").strip()
            if not code or not _is_ultra_board(code):
                continue
            board_total += 1
            name = (r.get("name") or "")
            if "退" in name:   # 仅剔退市股，不剔 ST
                continue
            pool.append(r)
        if len(rows) < 500:
            break
        page += 1
    return pool, board_total


def _scan_ultra(r: dict, bars: list[dict]) -> dict | None:
    """超短量价规则扫描（缓存/历史部分）：5日均量首次上穿60日均量 + 近10日涨幅≤20%。

    今日涨幅 ≥3% 不在此判定（须实时数据），留到 ``_ultra_realtime_filter``。
    数据不足返回 ``None``；历史条件不满足也返回 ``None``。
    """
    import statistics as _st

    vols = [(_safe_float(b.get("volume")) or 0.0) for b in bars]
    closes = [_safe_float(b.get("close")) for b in bars]
    if len(vols) < _ULTRA_VOL_LONG + 1 or len(closes) < 11:
        return None
    if any(c is None or c <= 0 for c in closes[-11:]):
        return None

    vol5_now = _st.mean(vols[-_ULTRA_VOL_SHORT:])
    vol60_now = _st.mean(vols[-_ULTRA_VOL_LONG:])
    vol5_prev = _st.mean(vols[-_ULTRA_VOL_SHORT - 1:-1])
    vol60_prev = _st.mean(vols[-_ULTRA_VOL_LONG - 1:-1])
    if vol60_now <= 0 or vol60_prev <= 0:
        return None
    # 「首次」上穿：昨日 5 日均量 ≤ 60 日均量，最新一根 5 日均量 > 60 日均量
    if not (vol5_prev <= vol60_prev and vol5_now > vol60_now):
        return None

    recent10 = (closes[-1] / closes[-11] - 1.0) * 100.0
    if recent10 > _ULTRA_RECENT10_MAX:
        return None

    c = _base_cand(r)
    c["_entry"] = True   # 历史条件已满足；今日涨幅在实时阶段最终确认
    code6 = c["code"].zfill(6)
    c["_ultra"] = {
        "vol5": round(vol5_now, 0),
        "vol60": round(vol60_now, 0),
        "vol_ratio": round(vol5_now / vol60_now, 2),
        "recent10_chg": round(recent10, 1),
        "board": "科创板" if code6.startswith(("688", "689")) else "创业板",
    }
    return c


async def _collect_ultra() -> tuple[list[dict], dict]:
    """超短量价缓存扫描：返回通过「量能上穿+近10日涨幅」的候选 + 漏斗(未含今日涨幅)。"""
    pool, board_total = await asyncio.to_thread(_build_ultra_pool)
    funnel = {
        "market_total": board_total,    # 创业板+科创板全部
        "after_filter": len(pool),      # 剔 ST/退市
        "scored": 0,                    # 有 K 线缓存可计算
        "buy_points": 0,                # 量能首次上穿 + 近10日涨幅≤20%
        "selected": 0,                  # 再加今日涨幅≥3%（最终入选）
        "cap": 0,                       # 无产出上限
    }
    if not pool:
        return [], funnel

    sem = asyncio.Semaphore(_MOMO_CONCURRENCY)
    scored_n = 0

    async def _scan(r: dict):
        nonlocal scored_n
        async with sem:
            bars = await asyncio.to_thread(_load_bars_cache_only, (r.get("code") or "").strip())
        if not bars or len(bars) < _ULTRA_VOL_LONG + 1:
            return None
        scored_n += 1
        return _scan_ultra(r, bars)

    scanned = await asyncio.gather(*[_scan(r) for r in pool])
    cands = [c for c in scanned if c]
    cands.sort(key=lambda c: -(c["_ultra"]["vol_ratio"] or 0))
    funnel["scored"] = scored_n
    funnel["buy_points"] = len(cands)
    return cands, funnel


async def _ultra_realtime_filter(cands: list[dict]) -> list[dict]:
    """实时校验今日涨幅 ≥3%（集合竞价/盘中），并回填最新价/涨幅。"""
    if not cands:
        return []
    finals: list[dict] = []
    try:
        from quantforge.data.feed import datasource
        codes = [c["code"].zfill(6) for c in cands]
        q = await asyncio.to_thread(datasource.quotes, codes)
    except Exception as e:
        logger.warning(f"ai_picks ultra: realtime quotes failed: {e}")
        q = {}
    for c in cands:
        code = c["code"].zfill(6)
        v = (q or {}).get(code) or {}
        chg = _safe_float(v.get("change_pct"))
        price = _safe_float(v.get("price"))
        if chg is None:
            chg = c.get("change_pct")   # 兜底用快照涨幅
        if chg is None or chg < _ULTRA_TODAY_GAIN_MIN:
            continue
        c["change_pct"] = chg
        if price and price > 0:
            c["price"] = price
        c["_ultra"]["today_chg"] = round(chg, 2)
        finals.append(c)
    return finals


def _build_ultra_picks(cands: list[dict]) -> list[dict]:
    """把超短候选直接转成 picks（规则化，不走 AI）。按 今日涨幅+量比 排序。"""
    def _score(c: dict) -> float:
        u = c["_ultra"]
        return (u.get("today_chg") or 0) * 2 + (u.get("vol_ratio") or 1) * 10

    cands = sorted(cands, key=lambda c: -_score(c))
    picks: list[dict] = []
    for i, c in enumerate(cands, 1):
        u = c["_ultra"]
        price = c.get("price")
        gain = u.get("today_chg") or 0.0
        r10 = u.get("recent10_chg")
        vr = u.get("vol_ratio")
        board = u.get("board")
        buy = round(price, 2) if price else None
        stop = round(price * (1 - _ULTRA_STOP_PCT / 100), 2) if price else None
        target = round(price * (1 + _ULTRA_TARGET_PCT / 100), 2) if price else None
        conf = int(min(98.0, max(55.0, 55 + gain * 2 + ((vr or 1) - 1) * 15)))
        picks.append({
            "rank": i,
            "code": c["code"],
            "name": c["name"],
            "sector": board,
            "reason": (
                f"{board}个股，5日均量首次上穿60日均量（量比{vr}）量能突破；"
                f"今日竞价涨{gain:+.2f}%放量启动，近10日累计涨幅{r10:+.1f}%尚未过热，"
                "符合超短量价突破打法。"
            ),
            "signals": [
                "5日均量上穿60日均量", f"量比 {vr}",
                f"今日 {gain:+.2f}%", f"10日 {r10:+.1f}%",
            ],
            "buy_price": buy,
            "stop_price": stop,
            "target_price": target,
            "target_pct": _ULTRA_TARGET_PCT,
            "stop_pct": _ULTRA_STOP_PCT,
            "checklist": [
                "竞价涨幅维持 ≥3% 且非涨停一字（无法买入）",
                "开盘后量能持续放大、分时承接有力",
                "所属板块情绪配合、大盘无系统性风险",
            ],
            "confidence": conf,
            "risk_level": "高",
            "holding_period": "1-3日",
            "price": price,
            "change_pct": gain,
            "pe": c.get("pe"),
            "pb": c.get("pb"),
            "momentum": {
                "score": conf,
                "state": "buy",
                "vol_ratio": vr,
                "recent10_chg": r10,
                "today_chg": gain,
                "buy_price": buy,
                "stop_price": stop,
                "target_price": target,
                "stop_pct": _ULTRA_STOP_PCT,
                "target_pct": _ULTRA_TARGET_PCT,
            },
        })
    return picks


def _ultra_summary(picks: list[dict]) -> tuple[str, str]:
    if picks:
        summary = (
            f"超短量价·盘前竞价扫描：创业板/科创板中「5日均量首次上穿60日均量 + 今日涨幅≥3% + "
            f"近10日涨幅≤20%」的标的共 {len(picks)} 只，已按今日涨幅与量比排序。"
        )
        op = "超短打法：量能突破叠加竞价强势，开盘择机参与；严格止损、当日或次日了结、不恋战。"
    else:
        summary = (
            "超短量价：当前竞价时段暂无同时满足「量能首次上穿 + 今日涨幅≥3% + 近10日涨幅≤20%」"
            "的创业板/科创板标的，建议耐心等待或观望。"
        )
        op = "今日竞价暂无符合条件的超短标的，空仓等待。"
    return summary, op


# ── 试盘线策略 (probe) ───────────────────────────────────────────────────────

def _is_north_exchange(code: str) -> bool:
    """是否北交所个股（4/8/920 开头）。"""
    c = (code or "").strip().zfill(6)
    return c.startswith(("4", "8")) or c.startswith("920")


def _limit_pct(code: str) -> float:
    """该股涨停幅度(%)：创业/科创 20%，其余主板 10%（已剔 ST，不考虑 5%）。"""
    c = (code or "").strip().zfill(6)
    return 19.8 if c.startswith(_PROBE_BOARDS_20) else 9.8


def _probe_index_change_map() -> dict[str, float]:
    """沪深300 各交易日涨跌幅(%)，用于排除「大盘跳水日」的假试盘。

    取不到则返回空 dict（此时不做大盘过滤，优雅降级）。复用 predictions 基准同源的
    SH000300 日 K（缓存优先，过期则现拉补缓存）。
    """
    try:
        from quantforge.data.storage import db_cache as _db
        bars = _db.kline_load("SH000300", "day")
        if not bars or bars[-1].get("date", "") < _dt.date.today().isoformat():
            try:
                from quantforge.api.routes.market import _kline_fetch
                fetched = _kline_fetch("SH000300", "day", 320)
                if fetched:
                    _db.kline_upsert("SH000300", "day", fetched)
                    bars = _db.kline_load("SH000300", "day")
            except Exception:
                pass
        rows = sorted(
            [b for b in (bars or []) if b.get("date") and _safe_float(b.get("close"))],
            key=lambda b: b["date"],
        )
        out: dict[str, float] = {}
        for i in range(1, len(rows)):
            pc = _safe_float(rows[i - 1]["close"])
            cl = _safe_float(rows[i]["close"])
            if pc and pc > 0 and cl is not None:
                out[rows[i]["date"]] = round((cl / pc - 1.0) * 100.0, 2)
        return out
    except Exception as e:
        logger.debug(f"ai_picks probe: index change map unavailable: {e}")
        return {}


def _scan_probe(r: dict, bars: list[dict], index_chg: dict[str, float] | None = None) -> dict | None:
    """扫描近一个月内的试盘线：在最近 ``_PROBE_LOOKBACK_DAYS`` 根 K 线里，取**最近一根**
    同时满足全部试盘条件的 K 线作为试盘日。无则返回 ``None``。

    bars 为升序日 K（最后一根=最新）。返回带 ``_probe`` 元数据的候选。
    """
    code = (r.get("code") or "").strip()
    name = r.get("name") or ""
    # 非 ST、非退市、非北交所
    if "退" in name or "ST" in name.upper() or _is_north_exchange(code):
        return None

    n = len(bars)
    if n < _PROBE_PRIOR_HIGH_WIN + 3:
        return None
    limit = _limit_pct(code)

    # 从最新往回找最近一根试盘线（落在近一个月内）
    start = max(_PROBE_PRIOR_HIGH_WIN + 1, n - _PROBE_LOOKBACK_DAYS)
    hit = None
    for i in range(n - 1, start - 1, -1):
        b = bars[i]
        prev = bars[i - 1]
        o = _safe_float(b.get("open"))
        h = _safe_float(b.get("high"))
        lo = _safe_float(b.get("low"))
        cl = _safe_float(b.get("close"))
        pc = _safe_float(prev.get("close"))
        v = _safe_float(b.get("volume")) or 0.0
        pv = _safe_float(prev.get("volume")) or 0.0
        if None in (o, h, lo, cl, pc) or pc <= 0 or pv <= 0 or h <= lo:
            continue
        probe_date = str(b.get("date") or "")
        # 0. 排除「大盘跳水日」：沪深300当日大跌时，长上影多为大盘拖累而非主力试盘
        idx_chg = (index_chg or {}).get(probe_date)
        if idx_chg is not None and idx_chg <= _PROBE_INDEX_CRASH:
            continue
        # 2. 收盘价 < 80
        if cl > _PROBE_PRICE_MAX:
            continue
        # 3. 当日涨幅 0 < x ≤ 9.8%
        gain = (cl / pc - 1.0) * 100.0
        if not (_PROBE_GAIN_MIN < gain <= _PROBE_GAIN_MAX):
            continue
        # 4. 前一日未涨停
        ppc = _safe_float(bars[i - 2].get("close"))
        if ppc and ppc > 0 and (pc / ppc - 1.0) * 100.0 >= limit:
            continue
        # 5. 当日量 ≥ 前一日 3 倍
        if v < _PROBE_VOL_MULT * pv:
            continue
        # 6. 长上影线
        body = abs(cl - o)
        upper = h - max(o, cl)
        rng = h - lo
        if upper < body * _PROBE_UPPER_BODY_MULT or upper < rng * _PROBE_UPPER_RANGE_FRAC:
            continue
        # 7. 低位突破前期高点：当日最高 > 前 N 日最高
        prior_highs = [(_safe_float(x.get("high")) or 0.0) for x in bars[i - _PROBE_PRIOR_HIGH_WIN:i]]
        if not prior_highs or h <= max(prior_highs):
            continue
        # 「低位」：试盘日前累计涨幅不过高（排除已大涨的高位放量）
        base = _safe_float(bars[max(0, i - _PROBE_RUNUP_WIN)].get("close"))
        if base and base > 0 and (cl / base - 1.0) * 100.0 > _PROBE_RUNUP_MAX:
            continue
        hit = (i, o, h, lo, cl, v, pv, gain)
        break

    if not hit:
        return None

    i, o, h, lo, cl, v, pv, gain = hit
    days_since = (n - 1) - i   # 距今多少个交易日（0=今天就是试盘日）

    # 试盘日后 3-7 日窗口的表现（doc：缩量回踩确认 / 放量下跌=主力放弃）
    post = bars[i + 1:i + 1 + _PROBE_POST_WIN]
    pullback_ok = False   # 缩量回踩到位：量萎缩至试盘日 ≤50% 且不破试盘最低点
    giveup = False        # 主力放弃迹象：放量下跌并跌破试盘最低点
    if post and v > 0:
        vols_post = [(_safe_float(x.get("volume")) or 0.0) for x in post]
        lows_post = [(_safe_float(x.get("low")) or lo) for x in post]
        closes_post = [(_safe_float(x.get("close")) or cl) for x in post]
        if min(vols_post) <= v * _PROBE_PULLBACK_VOL_MAX and min(lows_post) >= lo * 0.985:
            pullback_ok = True
        for j in range(len(post)):
            # 放量(≥试盘日0.8倍)下跌、收盘走低且跌破试盘最低点 → 试盘失败/主力放弃
            if vols_post[j] >= v * _PROBE_GIVEUP_VOL and closes_post[j] < cl and lows_post[j] < lo:
                giveup = True
                break

    c = _base_cand(r)
    c["_entry"] = True
    probe_date = str(bars[i].get("date") or "")
    c["_probe"] = {
        "probe_date": probe_date,
        "days_since": days_since,
        "probe_high": round(h, 2),     # 有效突破参考（站上=线上看多）
        "probe_close": round(cl, 2),   # 试盘线（收盘）——多空分界
        "probe_low": round(lo, 2),     # 试盘最低点——支撑/止损位
        "probe_gain": round(gain, 2),
        "vol_ratio": round(v / pv, 2) if pv else None,
        "pullback_ok": pullback_ok,
        "giveup": giveup,              # 试盘后放量下跌破位=主力放弃
        "index_chg": (index_chg or {}).get(probe_date),  # 试盘日大盘涨跌幅
    }
    return c


async def _collect_probe() -> tuple[list[dict], dict]:
    """全市场扫描近一个月内的试盘线候选 + 漏斗计数（纯规则，只读 K 线缓存）。"""
    pool, market_total = await asyncio.to_thread(_build_pool)
    funnel = {
        "market_total": market_total,   # 全市场快照总数
        "after_filter": len(pool),      # 剔退市/低成交额/金融板块（含 ST/北交所，后续剔）
        "scored": 0,                    # 有 K 线缓存可计算
        "buy_points": 0,                # 形成试盘线
        "selected": 0,                  # 入选（=试盘线）
        "cap": 0,
    }
    if not pool:
        return [], funnel

    # 大盘日涨跌幅（用于排除大盘跳水日的假试盘）——一次加载，全程复用
    index_chg = await asyncio.to_thread(_probe_index_change_map)

    sem = asyncio.Semaphore(_MOMO_CONCURRENCY)
    scored_n = 0

    async def _scan(r: dict):
        nonlocal scored_n
        async with sem:
            bars = await asyncio.to_thread(_load_bars_cache_only, (r.get("code") or "").strip())
        if not bars or len(bars) < _PROBE_PRIOR_HIGH_WIN + 3:
            return None
        scored_n += 1
        return _scan_probe(r, bars, index_chg)

    scanned = await asyncio.gather(*[_scan(r) for r in pool])
    cands = [c for c in scanned if c]
    funnel["scored"] = scored_n
    funnel["buy_points"] = len(cands)
    funnel["selected"] = len(cands)
    return cands, funnel


# 入场状态优先级（排序用）：已到 > 临近 > 今日试盘 > 等待突破 > 破位放弃
_PROBE_ENTRY_RANK = {"ready": 0, "near": 1, "today": 2, "watch": 3, "failed": 4}


def _probe_entry(c: dict) -> dict:
    """判定试盘后「入场点是否已到」。

    试盘战法：找到试盘线后**从次日起**，有效站上试盘线高点 = 线上看多(入场)，
    跌破试盘线 = 线下看空(放弃)；最理想的入场是「缩量回踩不破最低点后再度突破」。
    返回 ``{ready, state, label, note, color_state}``：
      · ready  入场点已到（现价站上试盘线高点）
      · near   临近入场（已缩量回踩到位，等站上高点）
      · today  今日试盘（试盘当日，次日起才看突破）
      · watch  等待突破（在试盘线~高点间整理）
      · failed 破位放弃（跌破试盘线，线下看空）
    """
    pb = c["_probe"]
    price = c.get("price")
    days = pb.get("days_since", 0)
    high = pb.get("probe_high")
    close = pb.get("probe_close")
    low = pb.get("probe_low")
    pullback = pb.get("pullback_ok")
    giveup = pb.get("giveup")

    # 主力放弃：试盘后已出现放量下跌破试盘最低点（doc 失败情形之一），直接判失败
    if giveup:
        return {"ready": False, "state": "failed", "label": "试盘失败",
                "note": f"试盘后已现放量下跌、跌破试盘最低点 {low}，主力大概率放弃控盘，勿参与",
                "color_state": "sell"}
    if days == 0:
        return {"ready": False, "state": "today", "label": "今日试盘",
                "note": f"试盘当日，从次日起观察能否有效站上试盘线高点 {high}",
                "color_state": "hold"}
    if not price:
        return {"ready": False, "state": "watch", "label": "待确认",
                "note": "缺实时价，暂无法判定是否突破", "color_state": "hold"}
    if price < close:
        return {"ready": False, "state": "failed", "label": "暂不入场",
                "note": f"已跌破试盘线 {close}（线下看空），试盘暂告失败，勿入场抄底",
                "color_state": "sell"}
    if price > high:
        note = (f"已缩量回踩不破试盘最低点后再度站上高点 {high}，回踩确认、入场点已到"
                if pullback else f"现价已有效站上试盘线高点 {high}（线上看多），入场点已到")
        return {"ready": True, "state": "ready", "label": "入场点已到",
                "note": note, "color_state": "buy"}
    # close <= price <= high：回踩/整理区
    if pullback:
        return {"ready": False, "state": "near", "label": "临近入场",
                "note": f"已缩量回踩到位，价在试盘线 {close}~高点 {high} 间，站上 {high} 即入场",
                "color_state": "hold"}
    return {"ready": False, "state": "watch", "label": "等待突破",
            "note": f"价在试盘线 {close}~高点 {high} 间整理，等有效站上 {high} 再入场",
            "color_state": "hold"}


def _build_probe_picks(cands: list[dict]) -> list[dict]:
    """把试盘线候选转成 picks（规则化，不走 AI）。

    排序：入场点已到优先 → 临近 → 今日试盘 → 等待 → 破位放弃；同档内试盘日越近、
    量比越大越靠前。
    """
    for c in cands:
        c["_entry_info"] = _probe_entry(c)

    cands = sorted(cands, key=lambda c: (
        _PROBE_ENTRY_RANK.get(c["_entry_info"]["state"], 9),
        c["_probe"].get("days_since", 99),
        -(c["_probe"].get("vol_ratio") or 0),
    ))

    picks: list[dict] = []
    for idx, c in enumerate(cands, 1):
        pb = c["_probe"]
        e = c["_entry_info"]
        price = c.get("price")
        e_state = e["state"]
        days = pb.get("days_since", 0)
        when = "今日" if days == 0 else f"{days}个交易日前"
        vr = pb.get("vol_ratio")
        probe_high = pb.get("probe_high")
        probe_low = pb.get("probe_low")
        probe_close = pb.get("probe_close")
        # 买入参考：入场点已到则取现价跟进，否则挂在试盘线高点(突破触发价)
        if price and e_state == "ready":
            buy = round(price, 2)
        else:
            buy = probe_high
        # 止损分级（doc）：以试盘线(收盘价)为基准，下方 3 个点黄牌、5 个点红牌(无条件离场)。
        # 红牌价取「试盘线-5%」与「试盘最低点」中较高者——两者皆破，更应离场。
        warn = round(probe_close * (1 - _PROBE_WARN_PCT / 100), 2) if probe_close else None
        stop = round(probe_close * (1 - _PROBE_STOP_PCT / 100), 2) if probe_close else None
        if stop and probe_low and probe_low > stop:
            stop = probe_low
        target = round(buy * (1 + _PROBE_TARGET_PCT / 100), 2) if buy else None
        stop_pct = round((1 - stop / buy) * 100, 1) if (buy and stop) else _PROBE_STOP_PCT
        # 置信度：入场状态 + 试盘日远近 + 缩量回踩
        conf = 58
        conf += {"ready": 22, "near": 10, "today": 2, "watch": 0, "failed": -14}.get(e_state, 0)
        conf += max(0, 10 - days)
        if pb.get("pullback_ok"):
            conf += 6
        conf = int(min(95, max(42, conf)))
        risk = "高" if e_state == "failed" else "中"

        signals = [
            e["label"],                       # 入场判定置于首位，最醒目
            f"{when}试盘线", f"放量{vr}倍" if vr else "放量",
            "长上影试盘", "突破前期高点",
        ]
        if pb.get("pullback_ok"):
            signals.append("已缩量回踩")

        idx_chg = pb.get("index_chg")
        idx_clause = f"（试盘日大盘{idx_chg:+.1f}%，非跳水日）" if isinstance(idx_chg, (int, float)) else ""
        reason = (
            f"{when}（{pb.get('probe_date')}）放量{vr}倍拉出长上影试盘线、突破前期高点{idx_clause}，"
            f"试盘日涨{pb.get('probe_gain')}%、最高{probe_high}、收{probe_close}，疑似大资金拉升前测试上方抛压。"
            f"【入场判定】{e['note']}。"
        )
        if pb.get("giveup"):
            reason += "但其后已出现放量下跌、跌破试盘最低点，主力疑似放弃控盘，应回避。"
        elif pb.get("pullback_ok"):
            reason += "其后已出现缩量回踩、未破试盘最低点，洗盘特征较健康。"

        # 入场触发条件随状态而变：未到则强调「站上高点才进」，已到则直接跟进
        if e_state == "ready":
            entry_rule = f"入场点已到：现价站上试盘线高点 {probe_high}，可顺势跟进（轻仓试）"
        elif e_state == "failed":
            entry_rule = f"暂不入场：已跌破试盘线 {probe_close}（线下看空），等重新站上再议"
        else:
            entry_rule = f"等入场：次日起有效站上试盘线高点 {probe_high} 再进场（线上看多、线下看空）"

        picks.append({
            "rank": idx,
            "code": c["code"],
            "name": c["name"],
            "sector": "",
            "reason": reason,
            "signals": signals,
            "buy_price": buy,
            "stop_price": stop,
            "warn_price": warn,           # 黄牌：试盘线下方 3% 警告位
            "target_price": target,
            "target_pct": _PROBE_TARGET_PCT,
            "stop_pct": stop_pct,
            # ── 入场点标注（前端醒目展示）─────────────────────────
            "entry_ready": e["ready"],
            "entry_state": e_state,
            "entry_label": e["label"],
            "entry_note": e["note"],
            "checklist": [
                entry_rule,
                f"止损分级：跌破试盘线下方 3 点({warn}) 黄牌减仓，跌破 5 点({stop}) 红牌无条件清仓",
                "理想形态：试盘后 3-7 日缩量回踩(量萎缩至试盘日 30%-50%)、不破试盘最低点",
                "回避三类失败：高开即遇强抛压放量下杀 / 拉高现大量跟风散户 / 横盘不拉反放量下跌(主力放弃)",
            ],
            "confidence": conf,
            "risk_level": risk,
            "holding_period": "3-10日",
            "price": price,
            "change_pct": c.get("change_pct"),
            "pe": c.get("pe"),
            "pb": c.get("pb"),
            "no_buy_point": e_state == "failed",
            "momentum": {
                "score": conf,
                "state": e["color_state"],
                "probe_date": pb.get("probe_date"),
                "days_since": days,
                "vol_ratio": vr,
                "probe_high": probe_high,
                "probe_close": probe_close,
                "probe_low": probe_low,
                "index_chg": pb.get("index_chg"),
                "status_label": e["label"],
                "entry_ready": e["ready"],
                "entry_state": e_state,
                "pullback_ok": pb.get("pullback_ok"),
                "giveup": pb.get("giveup"),
                "buy_price": buy,
                "stop_price": stop,
                "warn_price": warn,
                "target_price": target,
                "stop_pct": stop_pct,
                "target_pct": _PROBE_TARGET_PCT,
            },
        })
    return picks


def _probe_summary(picks: list[dict]) -> tuple[str, str]:
    if picks:
        n_ready = sum(1 for p in picks if p.get("entry_ready"))
        n_near = sum(1 for p in picks if p.get("entry_state") == "near")
        summary = (
            f"试盘线扫描：近一个月内全市场共发现 {len(picks)} 只形成试盘线(放量长上影+低位突破前期高点)"
            f"的个股，其中 {n_ready} 只【入场点已到】(现价站上试盘线高点)、{n_near} 只临近入场。"
            "试盘是大资金拉升前的战前侦察，线上看多、线下看空，务必带好止损。"
        )
        op = "试盘战法：仅对【入场点已到】者顺势轻仓跟进；跌破试盘线下方 3 点黄牌减仓、5 点红牌清仓；其余等有效突破再说。"
    else:
        summary = "试盘线：近一个月内全市场暂无符合「放量长上影 + 低位突破前期高点」的试盘线标的，建议耐心等待。"
        op = "当前无试盘线标的，空仓等待主力出手。"
    return summary, op


async def _generate_probe() -> dict:
    """试盘线产出：全市场缓存扫描近一个月试盘线 → 实时回填现价 → 规则化构建 picks（不走 AI）。

    调用方 ``_generate`` 已持有 ``_RUNNING['probe']`` 标志并负责清理。
    """
    cands, funnel = await _collect_probe()
    cands = await _enrich_candidates(cands)   # 回填实时现价/涨跌，用于判定线上/线下
    # 排除「到今天已涨很多」的：试盘线至今涨幅超阈值=入场机会已过、追高风险大
    kept: list[dict] = []
    overrun = 0
    for c in cands:
        price = c.get("price")
        pc = c["_probe"].get("probe_close")
        if price and pc and pc > 0 and (price / pc - 1.0) * 100.0 > _PROBE_MAX_RISE_SINCE:
            overrun += 1
            continue
        kept.append(c)
    funnel["overrun"] = overrun          # 因已涨过多被剔除的数量
    funnel["selected"] = len(kept)       # 涨幅可控、仍有入场价值
    picks = _build_probe_picks(kept)
    funnel["recommended"] = len(picks)
    has_buy_point = bool(picks)
    summary, op = _probe_summary(picks)

    now = _dt.datetime.now()
    payload = {
        "generated_at": now.isoformat(),
        "date": _trade_date(now).isoformat(),
        "slot": _current_slot(now),
        "slot_label": _SLOT_CN.get(_current_slot(now), ""),
        "strategy": "probe",
        "strategy_label": _STRATEGIES["probe"],
        "no_buy_point": not has_buy_point,
        "market_summary": summary,
        "operation_strategy": op,
        "picks": picks,
        "candidate_count": funnel.get("buy_points", 0),
        "funnel": funnel,
    }
    _save(payload, strategy="probe")
    logger.info(
        f"ai_picks[probe]: 漏斗 全市场{funnel['market_total']} → 过滤后{funnel['after_filter']} "
        f"→ 可评分{funnel['scored']} → 试盘线{funnel['buy_points']}(已排除大盘跳水日) "
        f"→ 剔除已涨多{funnel.get('overrun', 0)} → 涨幅可控{funnel['selected']} → 产出{len(picks)}"
    )

    # 记录预测用于次日验证（走 levels 结算，与 pring/ultra 一致）
    try:
        from quantforge.prediction.tracker import PredictionTracker
        PredictionTracker.record_picks(payload["picks"], date=payload["date"],
                                       pick_strategy="probe")
    except Exception as e:
        logger.warning(f"ai_picks probe: prediction recording failed: {e}")

    return payload


# ── Market data enrichment ─────────────────────────────────────────────────────

def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    except Exception:
        return None


async def _enrich_candidates(candidates: list[dict]) -> list[dict]:
    """Add latest price, change%, valuation to each candidate.

    Uses the project data-source facade (Tencent/iFinD) rather than efinance
    (EastMoney), which is intermittently blocked in this environment. The facade
    matches quotes by code, so there is no risk of column/row misalignment.
    """
    if not candidates:
        return candidates

    try:
        from quantforge.data.feed import datasource
        codes = [c["code"].zfill(6) for c in candidates if c.get("code")]

        q = await asyncio.to_thread(datasource.quotes, codes)

        for c in candidates:
            code = (c.get("code") or "").zfill(6)
            v = (q or {}).get(code)
            if not v:
                continue
            c["price"]      = _safe_float(v.get("price"))
            c["change_pct"] = _safe_float(v.get("change_pct"))
            c["high"]       = _safe_float(v.get("high"))
            c["low"]        = _safe_float(v.get("low"))
            c["pre_close"]  = _safe_float(v.get("last_close"))
            c["turnover"]   = _safe_float(v.get("turnover_pct"))
            c["amplitude"]  = _safe_float(v.get("amplitude_pct"))
            # Valuation — only fill when missing (screener data may be richer)
            if not c.get("pe"):
                c["pe"] = _safe_float(v.get("pe_ttm"))
            if not c.get("pb"):
                c["pb"] = _safe_float(v.get("pb"))
            if not c.get("market_cap"):
                c["market_cap"] = _safe_float(v.get("mcap_yi"))
    except Exception as e:
        logger.warning(f"ai_picks: realtime enrich failed: {e}")

    return candidates


# ── Price-level reconciliation ──────────────────────────────────────────────────

# If the AI's buy price drifts more than this fraction from the live price, we
# treat its absolute levels as unreliable and rebuild them from the percentages.
_DRIFT_THRESHOLD = 0.30


def _authoritative_prices(codes: list[str]) -> dict[str, float]:
    """Fetch real-time prices via the project data-source facade (Tencent/iFinD).

    More reliable here than efinance (EastMoney), which is intermittently
    blocked in this environment. Returns {code(zfill6): price}.
    """
    if not codes:
        return {}
    try:
        from quantforge.data.feed import datasource
        q = datasource.quotes([c.zfill(6) for c in codes])
    except Exception as e:
        logger.warning(f"ai_picks: authoritative price fetch failed: {e}")
        return {}
    out: dict[str, float] = {}
    for code, v in (q or {}).items():
        p = _safe_float(v.get("price"))
        if p and p > 0:
            out[code.zfill(6)] = p
    return out


def _reconcile_price_levels(picks: list[dict]) -> None:
    """Rebuild buy/target/stop in-place when they drift too far from live price.

    Keeps the model's *intent* (target_pct / stop_pct) but re-anchors the
    absolute prices to the authoritative current price. If the percentages are
    missing, falls back to sensible defaults (+10% target, -7% stop) and a buy
    band straddling the current price.
    """
    if not picks:
        return
    codes = [p.get("code", "") for p in picks if p.get("code")]
    live = _authoritative_prices(codes)
    if not live:
        return

    for pick in picks:
        code = (pick.get("code") or "").zfill(6)
        cur = live.get(code)
        if not cur:
            continue
        # Always trust the authoritative live price for display/space calc.
        pick["price"] = cur

        buy = _safe_float(pick.get("buy_price"))
        if not buy or buy <= 0:
            continue
        drift = abs(buy - cur) / cur
        if drift <= _DRIFT_THRESHOLD:
            continue   # AI levels are in the right ballpark, leave them

        # Levels are off by too much — rebuild from percentages around live price.
        tgt_pct = _safe_float(pick.get("target_pct"))
        stp_pct = _safe_float(pick.get("stop_pct"))
        if tgt_pct is None or tgt_pct <= 0:
            tgt_pct = 10.0
        if stp_pct is None or stp_pct <= 0:
            stp_pct = 7.0

        pick["buy_price"] = round(cur, 2)
        pick["target_price"] = round(cur * (1 + tgt_pct / 100), 2)
        pick["stop_price"] = round(cur * (1 - stp_pct / 100), 2)
        pick["target_pct"] = round(tgt_pct, 1)
        pick["stop_pct"] = round(stp_pct, 1)
        pick["levels_adjusted"] = True
        logger.info(
            f"ai_picks: re-anchored {code} levels (buy {buy}→{pick['buy_price']}, "
            f"live {cur}, drift {drift:.0%})"
        )


# ── AI analysis ────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """你是一位专业的A股技术派交易员，以"动能买卖点"为核心切入点选股，不依赖多因子策略命中。
你将收到一批已通过规则化动能模型扫描的候选股票，每只都附带：动能分(0-100)、动能状态(buy/hold/reduce/sell)、
动能方向(accelerating/rising/flat/falling)、RSI、以及由ATR锚定的买入价/止损价/目标价、盈亏比(rr)、支撑位/压力位、
最近一次动能买/卖信号，以及实时行情与估值(PE/PB)。

【四维动能（核心判据）】动能分由四个相互独立的维度交叉印证而来，每只候选都附「四维」明细，务必据此甄别：
  · 维度1 自身历史：当前动能相对它自己过去水位的高低（强势扩张/温和走强/走弱）。过热（自身极值）要警惕追高。
  · 维度2 与价格：动能与价格谁领先。「动能领先」=价格未充分反映、蓄势/底背离（偏多）；「顶背离」=价创新高动能没跟上（偏空，慎推）。
  · 维度3 与板块/大盘：相对**所属行业板块**(映射不到则相对沪深300大盘)的区间强弱，标签会注明基准名(如「vs电力行业」)。「跑赢」才是真强（板块里的领头羊），「跑输」多为随大流甚至板块拖后腿，优先级下调。
  · 维度4 反向动能：衰竭/反转压力（超买·动能掉头·放量长上影·MACD收敛）。压力「高」者即便动能分不低也要剔除或降级。

选股原则（务必遵守）：
1. 只选处在动能买点或买点临近的标的：动能状态为buy，或方向为rising/accelerating且动能分较高；
   动能转弱(reduce/sell/falling)的一律不推荐。**不要人为限制推荐数量(不是只选10只)——
   候选里所有仍处于有效买点的标的都要列入 picks，按动能强弱从好到坏排序、rank连续编号。**
2. **用四维动能交叉过滤**：优先「自身历史强势 + 动能领先价格 + 跑赢大盘 + 反向压力低」四维共振者；
   出现明显顶背离(维度2为负)或反向压力高(维度4)的，要么剔除、要么明确降级并在理由里点名风险。
3. 优先动能分高、盈亏比(rr)≥2、且未严重超买(RSI不过热)的标的。
4. 价位以候选数据里给出的动能买入价/止损价/目标价为基准，可微调但不要凭空虚构远离现价的价位。
5. 止损幅度不超过8%；给出明确的操作前置条件清单（满足全部条件才进场）。
6. 推荐理由必须围绕动能买卖点与四维动能展开（哪几维共振/是否跑赢大盘/有无背离与衰竭），辅以估值佐证。

输出格式要求：严格返回JSON，不要任何markdown或其他文字，格式如下：
{
  "market_summary": "一句话描述今日A股市场整体环境和操作思路",
  "operation_strategy": "今日整体操作策略：进攻/均衡/防守，及理由",
  "picks": [
    {
      "rank": 1,
      "code": "股票代码（6位）",
      "name": "股票名称",
      "sector": "所属行业",
      "reason": "推荐理由，2-3句话，以动能买卖点为切入：动能状态/方向+买点位置+量价/估值佐证",
      "signals": ["动能信号1", "动能信号2", "动能信号3"],
      "buy_price": 精确买入价如12.50,
      "stop_price": 精确止损价如11.80,
      "target_price": 精确目标价如14.20,
      "target_pct": 目标涨幅百分比数字如12.5,
      "stop_pct": 止损幅度百分比数字如5.0,
      "checklist": [
        "条件1: 价格回踩MA20且站稳",
        "条件2: 成交量相对前日缩量",
        "条件3: 大盘无系统性风险"
      ],
      "confidence": 置信度0-100整数,
      "risk_level": "低|中|高",
      "holding_period": "持有周期如1-2周"
    }
  ]
}
"""


_PRING_SYSTEM_PROMPT = """你是一位以马丁·普林格(Martin Pring)市场周期理论与 KST(Know Sure Thing) 动量指标
为核心的中长线波段交易员。你将收到一批已通过普林格 KST 扫描的候选股票，每只都附带：
综合评分(0-100)、买卖状态(buy/hold/reduce/sell)、KST 值与其信号线、所处普林格六阶段
(阶段一见底回升…阶段六下行筑底)、是否 KST 金叉、MA50、以及由 ATR 锚定的买入/止损/目标价、
盈亏比(rr)、支撑/压力，及实时行情与估值(PE/PB)。

选股原则（务必遵守）：
1. 只选处在普林格周期买点的标的：KST 在零轴下方/附近金叉(低位金叉最优)、长周期 KST 方向向上、
   股价站上 MA50、所处阶段为一至三(底部回升至上行)。已进入阶段四至六(见顶回落/下行)的不推荐。
   **不要人为限制推荐数量——候选里所有仍处于有效周期买点的标的都要列入 picks，按评分从好到坏
   排序、rank 连续编号。**
2. 这是中长线策略：持有周期以「数周至数月」为宜，优先盈亏比(rr)≥2、KST 刚转头向上者，避免高位追涨。
3. 价位以候选给出的买入/止损/目标价为基准，可微调但不要凭空虚构远离现价的价位；止损幅度不超过8%。
4. 推荐理由必须围绕普林格周期与 KST 展开（零轴下方金叉/长短周期共振/站上MA50/所处阶段），辅以估值佐证。
5. checklist 给出明确的中长线进场前置条件（如：KST 金叉确认不背离、长周期 KST 同步向上、回踩MA50不破）。

输出格式要求：严格返回JSON，不要任何markdown或其他文字，格式如下：
{
  "market_summary": "一句话描述当前A股所处的市场周期位置与中长线布局思路",
  "operation_strategy": "整体周期操作策略：底部布局/趋势持有/逢高减仓，及理由",
  "picks": [
    {
      "rank": 1,
      "code": "股票代码（6位）",
      "name": "股票名称",
      "sector": "所属行业",
      "reason": "推荐理由，2-3句话，以普林格周期/KST为切入：KST位置与金叉+所处阶段+趋势/估值佐证",
      "signals": ["KST零下金叉", "长周期向上", "站上MA50"],
      "buy_price": 精确买入价如12.50,
      "stop_price": 精确止损价如11.80,
      "target_price": 精确目标价如14.20,
      "target_pct": 目标涨幅百分比数字如12.5,
      "stop_pct": 止损幅度百分比数字如5.0,
      "checklist": [
        "条件1: KST 金叉且未与价格背离",
        "条件2: 长周期 KST 同步向上",
        "条件3: 股价站稳 MA50 之上"
      ],
      "confidence": 置信度0-100整数,
      "risk_level": "低|中|高",
      "holding_period": "持有周期如1-3个月"
    }
  ]
}
"""


_STATE_CN = {"buy": "买入", "hold": "持有", "reduce": "减仓", "sell": "卖出"}
_DIR_CN = {"accelerating": "加速向上", "rising": "上行", "flat": "走平", "falling": "下行"}


def _system_prompt(strategy: str) -> str:
    return _PRING_SYSTEM_PROMPT if strategy == "pring" else _SYSTEM_PROMPT


def _fmt_dimensions(dims: dict) -> str:
    """把四维动能快照压成一段紧凑文字喂给 AI（含档位标签 + 数值）。

    例：四维[自身史:强势扩张(+62)·与价:动能领先(+28)·大盘:跑赢(+41)·反向压力:低(12)]
    """
    sh = dims.get("self_history") or {}
    mp = dims.get("mom_vs_price") or {}
    vm = dims.get("vs_market") or {}
    rv = dims.get("reverse") or {}

    def _seg(prefix: str, d: dict) -> str | None:
        lab = d.get("label")
        sc = d.get("score")
        if lab is None and sc is None:
            return None
        if sc is None:
            return f"{prefix}:{lab}"
        return f"{prefix}:{lab}({sc:+.0f})" if prefix != "反向压力" else f"{prefix}:{lab}({sc:.0f})"

    # 维度3 用实际基准名（行业名/大盘），让 AI 知道是「跑赢所属板块」还是「跑赢大盘」
    bench_name = vm.get("benchmark") or "大盘"
    segs = [
        _seg("自身史", sh),
        _seg("与价", mp),
        _seg(f"vs{bench_name}", vm),
        _seg("反向压力", rv),
    ]
    segs = [s for s in segs if s]
    return "四维[" + "·".join(segs) + "]" if segs else ""


def _build_user_prompt(candidates: list[dict], has_buy_point: bool = True,
                       strategy: str = _DEFAULT_STRATEGY) -> str:
    today = _dt.date.today().strftime("%Y年%m月%d日")
    is_pring = strategy == "pring"
    scan_desc = "已按普林格 KST 周期扫描，按综合评分排序" if is_pring else "已按动能买卖点扫描，按动能强弱排序"
    lines = [
        f"今日日期：{today}", "",
        f"候选股票数据（{scan_desc}）：", "",
    ]

    for i, c in enumerate(candidates, 1):
        code = c.get("code", "")
        name = c.get("name", "")
        price = c.get("price")
        change = c.get("change_pct")
        pe = c.get("pe")
        pb = c.get("pb")
        mktcap = c.get("market_cap")
        m = c.get("momentum", {})

        parts = [f"{i}. {code} {name}"]
        if price:
            parts.append(f"现价{price}")
        if change is not None:
            parts.append(f"涨跌{change:+.2f}%")
        if m.get("score") is not None:
            parts.append(f"{'综合分' if is_pring else '动能分'}{m['score']}")
        if m.get("state"):
            parts.append(f"状态{_STATE_CN.get(m['state'], m['state'])}")
        if is_pring:
            if m.get("kst") is not None:
                parts.append(f"KST{m['kst']}/信号{m.get('kst_signal')}")
            if m.get("stage_label"):
                parts.append(m["stage_label"])
            if m.get("golden_cross"):
                parts.append("KST金叉")
            if m.get("ma50") is not None:
                parts.append(f"MA50={m['ma50']}")
        else:
            if m.get("direction"):
                parts.append(f"方向{_DIR_CN.get(m['direction'], m['direction'])}")
            if m.get("rsi") is not None:
                parts.append(f"RSI{m['rsi']:.0f}")
            dims = m.get("dimensions") or {}
            if dims:
                parts.append(_fmt_dimensions(dims))
            ba = m.get("entry_bars_ago")
            if ba is not None:
                parts.append("今日首次买点" if ba == 0 else f"{ba}日前首次买点")
        if m.get("buy_price"):
            parts.append(f"建议买入{m['buy_price']}")
        if m.get("stop_price"):
            parts.append(f"止损{m['stop_price']}")
        if m.get("target_price"):
            parts.append(f"目标{m['target_price']}")
        if m.get("rr"):
            parts.append(f"盈亏比{m['rr']}")
        if m.get("support") and m.get("resistance"):
            parts.append(f"支撑{m['support']}/压力{m['resistance']}")
        if pe:
            parts.append(f"PE={pe}")
        if pb:
            parts.append(f"PB={pb}")
        if mktcap:
            parts.append(f"市值{mktcap:.0f}亿" if mktcap > 100 else f"市值{mktcap:.1f}亿")
        lines.append(" | ".join(parts))

    lines.append("")
    if is_pring:
        if has_buy_point:
            lines.append(
                f"以上共 {len(candidates)} 只候选，均已通过普林格 KST 扫描、处于明确周期买点(状态buy：零轴下方/附近金叉+长周期向上+站上MA50)。"
                "请以普林格周期与 KST 为切入，将其中【所有】仍处于有效周期买点的标的【全部】纳入推荐，"
                "不要遗漏；按推荐优先级从好到坏排序，rank 从1开始连续编号。已进入阶段四至六(见顶/下行)的才剔除。"
                "这是中长线策略，持有周期以数周至数月为宜；价位以候选给出的买入/止损/目标价为基准。"
            )
        else:
            lines.append(
                f"【重要】今日全市场扫描后，没有任何标的形成明确的普林格 KST 周期买点。以上 {len(candidates)} 只"
                "仅是当前 KST 形态相对较好的【观察标的】，并非可立即进场的买点。"
                "请在 market_summary 与 operation_strategy 中点明【今日无明确周期买点、建议耐心等待底部金叉确认】，"
                "并在每只 reason 里说明它尚未形成 KST 低位金叉、需等待确认；checklist 第一条统一写明"
                "『等待 KST 在零轴下方/附近金叉、长周期同步向上后再考虑进场』。仍按评分排序、rank 连续编号。"
            )
    elif has_buy_point:
        lines.append(
            f"以上共 {len(candidates)} 只候选，均已通过规则化动能扫描、动能状态为明确买点(buy)，"
            "且都是【当日(最新一根K线)首次提示买入】的全新买点(非持有多日或滞后几天的旧买点)，"
            "每只附「今日首次买点」标注与「四维[…]」动能明细。请结合四维动能(自身历史/与价格/与大盘/反向压力)"
            "为切入，将其中【所有】仍处于有效买点的标的【全部】纳入推荐，不要只取前10只、不要遗漏；"
            "按推荐优先级从好到坏排序，rank 从1开始连续编号。**排序优先级：四维共振(自身强势+动能领先价格+"
            "跑赢大盘+反向压力低)者靠前；出现顶背离(与价为负)或反向压力高者降级或剔除。** "
            "仅当某标的动能确已转弱(reduce/sell/falling)时才可剔除。价位以候选给出的动能买入价/止损价/目标价为基准。"
        )
    else:
        lines.append(
            f"【重要】今日全市场扫描后，没有任何标的处于明确动能买点。以上 {len(candidates)} 只"
            "仅是当前动能相对较强的【观察标的】，并非可立即进场的买点。"
            "请如实说明：在 market_summary 与 operation_strategy 中点明【今日无明确买点、建议以观察"
            "为主/轻仓试探】，并在每只的 reason 里说明它只是动能较强但尚未形成买点、需等待回踩或"
            "突破确认；checklist 第一条统一写明『等待动能转入明确买点后再考虑进场』。"
            "仍按动能强弱排序、rank 从1连续编号，但不要把它们包装成明确买点。"
        )
    return "\n".join(lines)


async def _call_ai_batch(candidates: list[dict], has_buy_point: bool = True,
                         strategy: str = _DEFAULT_STRATEGY) -> dict:
    """对**一批**候选调一次 AI，返回 ``{market_summary, operation_strategy, picks}``。

    map-reduce 中的「map」单元：每批独立成 prompt、独立解析，失败抛出由上层捕获
    （单批失败不连累其它批）。
    """
    from quantforge.api.ai_client import chat

    user_prompt = _build_user_prompt(candidates, has_buy_point=has_buy_point, strategy=strategy)

    raw = await chat(
        system=_system_prompt(strategy),
        user=user_prompt,
        max_tokens=16384,   # picks are no longer capped at 10 → allow a long list
        caller="ai_picks",
        timeout=300,        # slow reasoning models (MiniMax) need >90s for a long list
    )

    # 复用 research 里成熟的容错解析器：剥 markdown 围栏 + 修复中段缺陷 +
    # 回退到首个完整对象（专治思考型模型如 MiniMax 在 JSON 后又跟解释/二段 JSON
    # 导致裸 json.loads 报 "Extra data" 整段失败）。
    from quantforge.api.routes.research import _loads_lenient
    try:
        return _loads_lenient(raw)
    except Exception as e:
        logger.warning(f"ai_picks: 单批 JSON 解析失败({e})；原文前200: {raw.strip()[:200]!r}")
        raise


def _chunk(seq: list, n: int) -> list[list]:
    """把 ``seq`` 切成每块至多 ``n`` 个的若干块。"""
    return [seq[i:i + n] for i in range(0, len(seq), n)]


async def _call_ai(candidates: list[dict], has_buy_point: bool = True,
                   strategy: str = _DEFAULT_STRATEGY) -> dict:
    """Map-reduce 全量跑 AI：候选分批并发调用，汇总合并为单份结果。

    - **map**：把全部候选切成 ``_AI_BATCH_SIZE`` 一批，最多 ``_AI_BATCH_CONCURRENCY``
      批并发，各批独立产 picks；单批失败只丢这一批，不影响其它批。
    - **reduce**：合并所有批的 picks（按 code 去重），按 confidence→动能分排序，
      重新连续编号 rank。market_summary / operation_strategy 取首个成功批的，
      作为大盘环境与操作基调的代表。
    """
    batches = _chunk(candidates, _AI_BATCH_SIZE)
    logger.info(
        f"ai_picks: map-reduce 全量跑 AI —— {len(candidates)} 只候选切成 "
        f"{len(batches)} 批(每批≤{_AI_BATCH_SIZE})，并发 {_AI_BATCH_CONCURRENCY}"
    )

    sem = asyncio.Semaphore(_AI_BATCH_CONCURRENCY)

    async def _run_batch(idx: int, chunk: list[dict]) -> dict | None:
        async with sem:
            try:
                res = await _call_ai_batch(chunk, has_buy_point=has_buy_point, strategy=strategy)
                logger.info(
                    f"ai_picks: 批 {idx + 1}/{len(batches)} 完成 "
                    f"({len(chunk)} 候选 → {len(res.get('picks', []))} picks)"
                )
                return res
            except Exception as e:
                logger.warning(f"ai_picks: 批 {idx + 1}/{len(batches)} 失败，跳过：{e}")
                return None

    results = await asyncio.gather(
        *[_run_batch(i, c) for i, c in enumerate(batches)]
    )
    ok = [r for r in results if r]
    if not ok:
        raise RuntimeError("ai_picks: 所有批次均失败，无可用结果")

    # ── reduce：合并 picks（按 code 去重，保留先到的）+ 重排 + 重编号 ──
    merged: dict[str, dict] = {}
    for res in ok:
        for p in res.get("picks", []):
            code = str(p.get("code", "")).strip()
            if code and code not in merged:
                merged[code] = p

    picks = list(merged.values())

    def _rank_key(p: dict):
        conf = _safe_float(p.get("confidence")) or 0.0
        mscore = _safe_float((p.get("momentum") or {}).get("score")) or 0.0
        return (-conf, -mscore)

    picks.sort(key=_rank_key)
    for i, p in enumerate(picks, 1):
        p["rank"] = i

    head = ok[0]
    logger.info(
        f"ai_picks: reduce 合并 {len(ok)} 批 → {len(picks)} 只去重后 picks"
    )
    return {
        "market_summary": head.get("market_summary", ""),
        "operation_strategy": head.get("operation_strategy", ""),
        "picks": picks,
    }


# ── Generation pipeline ────────────────────────────────────────────────────────

async def _generate(strategy: str = _DEFAULT_STRATEGY) -> dict:
    strategy = _norm_strategy(strategy)
    if _RUNNING.get(strategy):
        raise HTTPException(status_code=409, detail="AI分析正在进行中，请稍后刷新")
    _RUNNING[strategy] = True
    try:
        # ── 超短量价：纯规则化、不走 AI（盘前竞价高频刷新，AI 不适用）──
        if strategy == "ultra":
            return await _generate_ultra()

        # ── 试盘线：纯规则化、不走 AI（近一个月内放量长上影+突破前期高点）──
        if strategy == "probe":
            return await _generate_probe()

        candidates, has_buy_point, funnel = await _collect_candidates(strategy)
        if not candidates:
            raise ValueError("no candidates from screener")

        candidates = await _enrich_candidates(candidates)

        ai_result = await _call_ai(candidates, has_buy_point=has_buy_point, strategy=strategy)

        # Merge actual price data back into picks
        # Build code map with multiple key variants (with/without leading zeros)
        code_map: dict[str, dict] = {}
        for c in candidates:
            code = c.get("code", "")
            if code:
                code_map[code] = c
                code_map[code.lstrip("0")] = c
                code_map[code.zfill(6)] = c
        for pick in ai_result.get("picks", []):
            pcode = pick.get("code", "")
            row = code_map.get(pcode) or code_map.get(pcode.lstrip("0")) or code_map.get(pcode.zfill(6))
            if row:
                # 用权威行业归属覆盖 AI 自填的 sector（AI 可能臆造行业名），供前端分板块筛选；
                # 映射不到行业的票仍保留 AI 文本作兜底。
                if row.get("sector"):
                    pick["sector"] = row["sector"]
                pick.setdefault("price", row.get("price"))
                pick.setdefault("change_pct", row.get("change_pct"))
                pick.setdefault("pe", row.get("pe"))
                pick.setdefault("pb", row.get("pb"))
                # carry the computed momentum snapshot (切入点依据)
                mom = row.get("momentum", {})
                pick["momentum"] = mom
                # seed executable levels from momentum when the model omits them
                if mom:
                    if not pick.get("buy_price") and mom.get("buy_price"):
                        pick["buy_price"] = mom["buy_price"]
                    if not pick.get("stop_price") and mom.get("stop_price"):
                        pick["stop_price"] = mom["stop_price"]
                    if not pick.get("target_price") and mom.get("target_price"):
                        pick["target_price"] = mom["target_price"]
                    if not pick.get("stop_pct") and mom.get("stop_pct"):
                        pick["stop_pct"] = mom["stop_pct"]
                    if not pick.get("target_pct") and mom.get("target_pct"):
                        pick["target_pct"] = mom["target_pct"]

        # Reconcile AI-generated price levels against the real-time price.
        # The model sometimes ignores the live price in the prompt and emits
        # buy/target/stop anchored to a remembered (stale) price level — off by
        # multiples. Pull authoritative quotes and rebuild levels when they
        # drift too far from the current price.
        _reconcile_price_levels(ai_result.get("picks", []))

        # 无明确买点兜底标记：当天扫描不到真买点时，picks 是「动能较强观察标的」，
        # 而非可立即进场的买点 —— 在 payload 与每个 pick 上打标，前端据此提示。
        picks = ai_result.get("picks", [])
        if not has_buy_point:
            for p in picks:
                p["no_buy_point"] = True

        # 不再截断产出：AI 选出多少全部保留（已按 confidence→动能分排序、rank 连续）。
        funnel["recommended"] = len(picks)   # AI 最终产出（漏斗末级）

        now = _dt.datetime.now()
        payload = {
            "generated_at": now.isoformat(),
            "date": _trade_date(now).isoformat(),
            "slot": _current_slot(now),
            "slot_label": _SLOT_CN.get(_current_slot(now), ""),
            "strategy": strategy,
            "strategy_label": _STRATEGIES.get(strategy, strategy),
            "no_buy_point": not has_buy_point,
            "market_summary": ai_result.get("market_summary", ""),
            "operation_strategy": ai_result.get("operation_strategy", ""),
            "picks": picks,
            "candidate_count": len(candidates),
            "funnel": funnel,   # 选股漏斗：全市场→过滤→可评分→买点→入选→产出
        }
        _save(payload, strategy=strategy)
        logger.info(f"ai_picks[{strategy}]: generated {len(payload['picks'])} picks")

        # Auto-record predictions for same-day verification
        try:
            from quantforge.prediction.tracker import PredictionTracker
            PredictionTracker.record_picks(payload["picks"], date=payload["date"],
                                           pick_strategy=strategy)
        except Exception as e:
            logger.warning(f"ai_picks: prediction recording failed: {e}")

        # Push notifications if ai_picks event is enabled
        try:
            from quantforge.notification.manager import NotificationManager, load_settings
            cfg = load_settings()
            if cfg.get("enabled") and cfg.get("events", {}).get("ai_picks", True):
                mgr = NotificationManager.from_settings()
                title, body = NotificationManager.format_ai_picks(payload)
                asyncio.create_task(mgr.notify(title, body))
        except Exception as e:
            logger.warning(f"ai_picks: notification failed: {e}")

        return payload
    finally:
        _RUNNING[strategy] = False


async def _generate_ultra() -> dict:
    """超短量价产出：缓存历史筛 → 实时今日涨幅校验 → 直接构建 picks（不走 AI）。

    调用方 ``_generate`` 已持有 ``_RUNNING['ultra']`` 标志并负责清理，这里不再管理。
    """
    cands, funnel = await _collect_ultra()
    cands = await _ultra_realtime_filter(cands)
    funnel["selected"] = len(cands)
    picks = _build_ultra_picks(cands)
    funnel["recommended"] = len(picks)
    has_buy_point = bool(picks)
    summary, op = _ultra_summary(picks)

    now = _dt.datetime.now()
    payload = {
        "generated_at": now.isoformat(),
        "date": _trade_date(now).isoformat(),
        "slot": _current_slot(now),
        "slot_label": _SLOT_CN.get(_current_slot(now), ""),
        "strategy": "ultra",
        "strategy_label": _STRATEGIES["ultra"],
        "no_buy_point": not has_buy_point,
        "market_summary": summary,
        "operation_strategy": op,
        "picks": picks,
        "candidate_count": funnel.get("buy_points", 0),
        "funnel": funnel,
    }
    _save(payload, strategy="ultra")
    logger.info(
        f"ai_picks[ultra]: 漏斗 创业/科创{funnel['market_total']} → 剔ST{funnel['after_filter']} "
        f"→ 可评分{funnel['scored']} → 量能上穿+10日达标{funnel['buy_points']} "
        f"→ 今日涨幅≥3%{funnel['selected']} → 产出{len(picks)}"
    )

    # 记录预测用于次日验证（与其它策略一致）
    try:
        from quantforge.prediction.tracker import PredictionTracker
        PredictionTracker.record_picks(payload["picks"], date=payload["date"],
                                       pick_strategy="ultra")
    except Exception as e:
        logger.warning(f"ai_picks ultra: prediction recording failed: {e}")

    return payload


async def ultra_scalp_scanner():
    """盘前集合竞价超短量价滚动扫描：交易日 09:20–09:25 每 30s 重扫并覆盖当日缓存。

    纯规则、不走 AI，开销小；窗口外长睡。默认开，``QF_NO_ULTRA=1`` 关闭。
    """
    logger.info("ultra scalp scanner started (trading days 09:20-09:25, every 30s)")
    while True:
        try:
            now = _dt.datetime.now()
            hm = now.hour * 60 + now.minute
            in_window = now.weekday() < 5 and _ULTRA_WIN_START <= hm <= _ULTRA_WIN_END
            if in_window and not _RUNNING.get("ultra"):
                try:
                    await _generate("ultra")
                except Exception as e:
                    logger.warning(f"ai_picks ultra scan failed: {e}")
                await asyncio.sleep(_ULTRA_SCAN_INTERVAL)
            else:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"ai_picks ultra scanner loop error: {e}")
            await asyncio.sleep(60)


# ── API endpoints ──────────────────────────────────────────────────────────────

def _load_current_slot(strategy: str = _DEFAULT_STRATEGY) -> dict | None:
    """精确加载「当前时段」该策略的缓存（用于判断本时段是否已生成）。"""
    f = _cache_path(_slot_key(strategy=strategy))
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


@router.get("/strategies")
async def list_strategies():
    """返回可用的荐股策略列表（前端 Tab 用）。"""
    return {"strategies": [{"key": k, "label": v} for k, v in _STRATEGIES.items()],
            "default": _DEFAULT_STRATEGY}


@router.get("/daily")
async def get_daily_picks(strategy: str = _DEFAULT_STRATEGY):
    """返回今天**最新一个时段**的荐股（缓存优先，一天两次：午盘/收盘后）。"""
    strategy = _norm_strategy(strategy)
    cached = _latest_today(strategy)
    if cached:
        cached["from_cache"] = True
        return await _enrich_classification(cached)

    # 今天还没有任何时段的荐股 —— 现场生成（同步，用户等待）
    return await _enrich_classification(await _generate(strategy))


@router.post("/refresh")
async def refresh_picks(background_tasks: BackgroundTasks, force: bool = False,
                        strategy: str = _DEFAULT_STRATEGY):
    """Force-regenerate today's picks in the background."""
    strategy = _norm_strategy(strategy)
    if _RUNNING.get(strategy):
        return {"status": "already_running", "message": "AI分析正在进行中"}

    if not force:
        # 只看「当前时段」是否已生成；跨到新时段(午盘→收盘后)应允许再生成一份
        cached = _load_current_slot(strategy)
        if cached:
            slot_cn = _SLOT_CN.get(_current_slot(), "本时段")
            return {"status": "fresh", "message": f"{slot_cn}推荐已是最新", "generated_at": cached.get("generated_at")}

    background_tasks.add_task(_generate, strategy)
    return {"status": "started", "message": "AI分析已在后台启动，约1分钟后刷新页面查看结果"}


@router.get("/status")
async def get_status(strategy: str = _DEFAULT_STRATEGY):
    """Return whether a generation is in progress and cache state."""
    strategy = _norm_strategy(strategy)
    cached = _latest_today(strategy)              # 当天最新一份（首页展示用）
    slot_cached = _load_current_slot(strategy)    # 当前时段是否已生成（决定能否再刷）
    # 全市场扫描覆盖度：已缓存 K 线的票数 / 快照全市场票数
    try:
        from quantforge.data.storage import db_cache as _db
        kline_codes = await asyncio.to_thread(_db.kline_code_count, "day", 40)
        market_codes = await asyncio.to_thread(_db.quote_count)
    except Exception:
        kline_codes = market_codes = 0
    return {
        "running": bool(_RUNNING.get(strategy)),
        "strategy": strategy,
        "has_today": cached is not None,
        "slot": _current_slot(),
        "slot_label": _SLOT_CN.get(_current_slot(), ""),
        "has_current_slot": slot_cached is not None,
        "generated_at": cached.get("generated_at") if cached else None,
        "pick_count": len(cached.get("picks", [])) if cached else 0,
        "kline_cached_codes": kline_codes,    # 全市场扫描可覆盖的票数
        "market_codes": market_codes,         # 快照全市场票数
    }


@router.post("/prewarm")
async def prewarm_market(background_tasks: BackgroundTasks, limit: int | None = None):
    """手动触发全市场 K 线预热（首轮灌库用，后台跑、立即返回）。

    可选 ``limit`` 限制只灌前 N 只（按快照顺序），用于快速验证。
    """
    from quantforge.api.routes.market import prewarm_market_klines

    async def _run():
        try:
            attempted, ok = await prewarm_market_klines(limit=limit)
            logger.info(f"ai_picks prewarm: warmed {ok}/{attempted} codes")
        except Exception as e:
            logger.warning(f"ai_picks prewarm failed: {e}")

    background_tasks.add_task(_run)
    return {"status": "started", "message": "全市场K线预热已在后台启动，进度见 /status 的 kline_cached_codes"}


@router.get("/history")
async def get_history(strategy: str | None = None):
    """List previously cached daily pick sets (可按 strategy 过滤)。"""
    return {"history": _list_history(strategy)}


@router.get("/history-date/{date_key}")
async def get_history_date(date_key: str):
    """返回指定时段或日期的缓存荐股。

    ``date_key`` 可为完整时段键(``2026-06-11_close``)或纯日期(``2026-06-11``，
    此时返回当天最新一个时段)。
    """
    from fastapi import HTTPException

    path = _cache_path(date_key)
    # 纯日期 → 取当天最新时段文件
    if not path.exists() and "_" not in date_key:
        candidates = sorted(
            _CACHE_DIR.glob(f"{date_key}_*.json"),
            key=lambda f: _SLOT_ORDER.get(_parse_key(f.stem)[1], 0),
        )
        if candidates:
            path = candidates[-1]
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No picks found for {date_key}")
    try:
        return await _enrich_classification(json.loads(path.read_text(encoding="utf-8")))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
