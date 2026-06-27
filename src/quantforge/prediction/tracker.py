"""Prediction tracker — record AI picks and verify against actual results.

Single source of truth = the path-based settlement engine ``settle()``. The
exit rule branches on the pick strategy:

  **动能(momentum)** — exit on the strategy's own signal, not on price levels:
  hold from the buy day open until the momentum model emits its first **sell
  signal**; since a signal is only confirmed after that bar closes, the actual
  exit is the **next trading day's open**. Return = (exit_open − entry) / entry.
  No stop/target. If no sell signal yet (or the signal is on the latest bar and
  next-day open isn't available) → outcome "open", re-checked daily.

  **其它(pring / ultra / 历史口径)** — price-level + fixed window:
  - entry_price  = open of the first trading day >= prediction date
  - holding window = fixed N trading days (QF_VERIFY_WINDOW, default 20)
  - each bar inside the window is scanned in order; **stop is checked before
    target** (conservative — when both fall inside one daily range we cannot
    know intraday order, so assume the adverse one). The first trigger LOCKS
    the outcome & return; later bars are "after lock" and don't change it.
  - if neither triggers within the window → settle by the window's final close
    (positive / negative / neutral).
  - if the window has not fully elapsed and nothing triggered → outcome "open".

Both the list view (``verify_pending`` → DB) and the detail view
(``get_detail`` → per-day path) run the *same* engine, so they can never
disagree.

Storage: ``predictions`` table in ``data/cache.db`` (see db_cache). Legacy
``data/cache/predictions.json`` is imported once on first use.
"""

from __future__ import annotations

import asyncio
import json
import os
import datetime as _dt
import math
from pathlib import Path

from loguru import logger

from quantforge.data.storage import db_cache as _db

_LEGACY_FILE = Path("data/cache/predictions.json")

# 固定持仓窗口（交易日）。结算只在 entry 之后的 window 根 K 线内扫描止盈/止损。
VERIFY_WINDOW = int(os.getenv("QF_VERIFY_WINDOW", "20"))

# 基准指数（沪深300，腾讯前复权）。用于「超额收益」对比，取不到时优雅降级为 None。
_BENCH_CODE = "SH000300"


# ── helpers ─────────────────────────────────────────────────────────────────

def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    except Exception:
        return None


def _date_str(d: str | _dt.date) -> str:
    if isinstance(d, str):
        return d.replace("-", "")
    return d.strftime("%Y%m%d")


def _migrate_legacy_once() -> None:
    """Import the old JSON file into the DB once (if table is empty)."""
    try:
        if _db.predictions_count() > 0 or not _LEGACY_FILE.exists():
            return
        data = json.loads(_LEGACY_FILE.read_text(encoding="utf-8"))
        rows = data.get("predictions", []) if isinstance(data, dict) else []
        if rows:
            _db.predictions_upsert_many(rows)
            logger.info(f"prediction_tracker: migrated {len(rows)} predictions from JSON → DB")
    except Exception as exc:
        logger.warning(f"prediction_tracker: legacy migration skipped: {exc}")


# ── settlement engine (single source of truth) ──────────────────────────────

def _momentum_sell_signals(bars: list[dict]) -> list[dict]:
    """动能模型在 ``bars`` 上的**卖点交易日**（逐根 state 为 ``sell`` 的那些 K 线）。

    用逐根 state（score≤卖出阈值）而非「状态转换信号」——持有期内只要动能转入 sell
    就是卖点，不要求先翻回 buy 再转 sell（否则买在趋势中段、其后再没翻 buy 的票会永远
    等不到「新卖点」而一直挂 open）。返回升序 ``[{date, type:"sell"}]``。动能验证据此
    退出：买入后首个卖点日，信号当根收盘才确认，故**次日开盘**实际卖出。
    """
    try:
        from quantforge.analysis.momentum import compute_momentum, MomentumConfig
        res = compute_momentum(bars, MomentumConfig())
        state = res.get("state") or []
        # state 与输入 bars 按位置一一对齐（_to_frame 不丢行）
        return [{"date": str(b["date"]), "type": "sell"}
                for i, b in enumerate(bars)
                if i < len(state) and state[i] == "sell" and b.get("date")]
    except Exception as exc:
        logger.debug(f"prediction_tracker: momentum sell-signal calc failed: {exc}")
        return []


def _path_row(asc: list[dict], i: int, entry_idx: int, vs_buy: float,
              status: str, is_trigger: bool, is_after_lock: bool) -> dict:
    b = asc[i]
    c = _safe_float(b.get("close"))
    prev_close = _safe_float(asc[i - 1].get("close")) if i > entry_idx else None
    day_chg = ((c - prev_close) / prev_close * 100) if (prev_close and c) else 0.0
    return {
        "date": b["date"], "open": _safe_float(b.get("open")),
        "high": _safe_float(b.get("high")), "low": _safe_float(b.get("low")),
        "close": c, "volume": _safe_float(b.get("volume")),
        "vs_buy": round(vs_buy, 2), "day_chg": round(day_chg, 2),
        "status": status, "is_trigger": is_trigger, "is_after_lock": is_after_lock,
    }


def _settle_momentum_core(asc, entry_idx, entry_price, sell_signals):
    """动能策略结算：持有到**首个卖点信号**，按信号**次日开盘价**退出计算收益。

    卖点信号在当根 K 线收盘后才能确认，故实际只能在下一交易日开盘卖出。若卖点信号
    出现在最新一根 K 线（次日 open 尚不可得）或尚无卖点 → outcome="open"、未结算，
    每日结算器后续复算。胜负按收益正负判（positive/negative/neutral）。
    """
    entry_date = asc[entry_idx]["date"]
    sig = next((s for s in sell_signals if s.get("date") and s["date"] > entry_date), None)
    sig_date = sig["date"] if sig else None
    sig_idx = next((i for i, b in enumerate(asc) if b["date"] == sig_date), None) if sig_date else None

    exit_idx = None
    if sig_idx is not None and sig_idx + 1 < len(asc):
        exit_idx = sig_idx + 1   # 次日开盘退出

    path: list[dict] = []
    if exit_idx is not None:
        exit_open = _safe_float(asc[exit_idx].get("open")) or _safe_float(asc[exit_idx].get("close"))
        locked_return = (exit_open - entry_price) / entry_price * 100
        for i in range(entry_idx, exit_idx + 1):
            if i == exit_idx:
                path.append(_path_row(asc, i, entry_idx, locked_return, "sell", False, True))
            elif i == sig_idx:
                vs = (_safe_float(asc[i].get("close")) - entry_price) / entry_price * 100 \
                    if _safe_float(asc[i].get("close")) else 0.0
                path.append(_path_row(asc, i, entry_idx, vs, "sell", True, False))
            else:
                c = _safe_float(asc[i].get("close"))
                vs = (c - entry_price) / entry_price * 100 if c else 0.0
                path.append(_path_row(asc, i, entry_idx, vs, "open", False, False))
        outcome = "positive" if locked_return > 0 else "negative" if locked_return < 0 else "neutral"
        return (path, True, outcome, locked_return, exit_open,
                sig_date, exit_idx - entry_idx + 1, asc[exit_idx]["date"])

    # 尚未触发卖点（或卖点在最新一根、次日 open 未出）→ 持有中
    end_idx = len(asc) - 1
    for i in range(entry_idx, end_idx + 1):
        c = _safe_float(asc[i].get("close"))
        vs = (c - entry_price) / entry_price * 100 if c else 0.0
        is_sig = (sig_idx is not None and i == sig_idx)
        path.append(_path_row(asc, i, entry_idx, vs, "sell" if is_sig else "open", is_sig, False))
    last_close = _safe_float(asc[end_idx].get("close")) or entry_price
    final_return = (last_close - entry_price) / entry_price * 100
    settle_date = asc[end_idx]["date"]
    return (path, False, "open", final_return, last_close, None,
            end_idx - entry_idx + 1, settle_date)


def _settle_levels_core(asc, entry_idx, entry_price, win_bars, window, target, stop, entry_bar):
    """价位结算（普林格/超短及历史口径）：逐根先判止损再判止盈，未触发按窗口末收盘。"""
    path: list[dict] = []
    triggered = False
    outcome: str | None = None
    trigger_date: str | None = None
    locked_return: float | None = None
    locked_close: float | None = None
    trig_i = -1

    for i, b in enumerate(win_bars):
        o = _safe_float(b.get("open"))
        h = _safe_float(b.get("high"))
        lo = _safe_float(b.get("low"))
        c = _safe_float(b.get("close"))
        is_trigger_day = False

        if not triggered:
            if stop and lo is not None and lo <= stop:
                triggered = True
                outcome = "hit_stop"
                trigger_date = b["date"]
                locked_return = (stop - entry_price) / entry_price * 100
                locked_close = stop
                is_trigger_day = True
                trig_i = i
            elif target and h is not None and h >= target:
                triggered = True
                outcome = "hit_target"
                trigger_date = b["date"]
                locked_return = (target - entry_price) / entry_price * 100
                locked_close = target
                is_trigger_day = True
                trig_i = i

        vs_buy = locked_return if triggered else ((c - entry_price) / entry_price * 100 if c else 0.0)
        prev_close = _safe_float(win_bars[i - 1].get("close")) if i > 0 else None
        day_chg = ((c - prev_close) / prev_close * 100) if (prev_close and c) else 0.0

        path.append({
            "date": b["date"], "open": o, "high": h, "low": lo, "close": c,
            "volume": _safe_float(b.get("volume")),
            "vs_buy": round(vs_buy, 2),
            "day_chg": round(day_chg, 2),
            "status": "target" if (triggered and outcome == "hit_target") and i >= trig_i else
                      "stop" if (triggered and outcome == "hit_stop") and i >= trig_i else "open",
            "is_trigger": is_trigger_day,
            "is_after_lock": triggered and not is_trigger_day,
        })

    has_full_window = len(win_bars) >= window

    if triggered:
        settled = True
        final_return = locked_return
        actual_close = locked_close
        hold_days = trig_i + 1
    elif has_full_window:
        settled = True
        last_close = _safe_float(win_bars[-1].get("close")) or entry_price
        final_return = (last_close - entry_price) / entry_price * 100
        outcome = "positive" if final_return > 0 else "negative" if final_return < 0 else "neutral"
        actual_close = last_close
        trigger_date = None
        hold_days = len(win_bars)
    else:
        settled = False
        last_close = _safe_float(win_bars[-1].get("close")) or entry_price if win_bars else entry_price
        final_return = (last_close - entry_price) / entry_price * 100
        outcome = "open"
        actual_close = last_close
        trigger_date = None
        hold_days = len(win_bars)

    settle_date = trigger_date or (path[-1]["date"] if path else entry_bar["date"])
    return (path, settled, outcome, final_return, actual_close, trigger_date, hold_days, settle_date)


def settle(pred: dict, bars: list[dict], window: int = VERIFY_WINDOW,
           momentum_signals: list[dict] | None = None) -> dict | None:
    """Path-based settlement of one prediction against ascending daily OHLC bars.

    ``bars`` — ascending list of {date, open, high, low, close, volume}.
    Returns a dict with the settlement summary + per-day ``path``, or ``None``
    if the market hasn't opened on/after the prediction date yet.

    退出口径按荐股策略分流：
      · **动能(momentum)** —— 持有到动能模型首个**卖点信号**，按信号**次日开盘价**退出
        计算收益（不挂止盈止损）。卖点信号可由 ``momentum_signals`` 预传（同一只股票
        批量结算时只算一次），未传则内部用 ``_momentum_sell_signals`` 现算。
      · **其它(pring/ultra/历史)** —— 逐根先判止损再判止盈，未触发按固定窗口末收盘。
    无论哪种，窗口反事实指标(window_return/mfe/mae/horizon_returns)口径不变。
    """
    pred_date = str(pred.get("date") or "")
    target = _safe_float(pred.get("target_price"))
    stop = _safe_float(pred.get("stop_price"))

    asc = [b for b in bars if b.get("date")]
    entry_idx = next((i for i, b in enumerate(asc) if b["date"] >= pred_date), None)
    if entry_idx is None:
        return None

    entry_bar = asc[entry_idx]
    entry_price = _safe_float(entry_bar.get("open")) or _safe_float(entry_bar.get("close"))
    if not entry_price or entry_price <= 0:
        return None

    win_bars = asc[entry_idx: entry_idx + window]

    is_momentum = (pred.get("pick_strategy") or "momentum") == "momentum"
    if is_momentum:
        sigs = momentum_signals if momentum_signals is not None else _momentum_sell_signals(asc)
        (path, settled, outcome, final_return, actual_close,
         trigger_date, hold_days, settle_date) = _settle_momentum_core(
            asc, entry_idx, entry_price, sigs)
    else:
        (path, settled, outcome, final_return, actual_close,
         trigger_date, hold_days, settle_date) = _settle_levels_core(
            asc, entry_idx, entry_price, win_bars, window, target, stop, entry_bar)

    # ── 反事实/窗口敏感性（不受止盈止损规则影响，纯买入持有）──────────────
    # window_return: 硬扛到窗口末的收益（回答「止损/止盈是否拖累」）
    # mfe/mae: 持仓窗口内最大有利/不利波动（回答「卖飞了没 / 差点被埋多深」）
    win_highs = [v for v in (_safe_float(b.get("high")) for b in win_bars) if v is not None]
    win_lows = [v for v in (_safe_float(b.get("low")) for b in win_bars) if v is not None]
    last_win_close = (_safe_float(win_bars[-1].get("close")) or entry_price) if win_bars else entry_price
    window_return = round((last_win_close - entry_price) / entry_price * 100, 2)
    mfe_pct = round((max(win_highs) - entry_price) / entry_price * 100, 2) if win_highs else None
    mae_pct = round((min(win_lows) - entry_price) / entry_price * 100, 2) if win_lows else None

    # 各持仓窗口收益：买入价开仓，持有 h 个交易日后按当日收盘退出（无止盈止损）。
    # 窗口口径=回测维度：1日(昨日)/3日/5日/7日/30日。h=1 即买入当日 open→close。
    horizon_returns: dict[str, float | None] = {}
    for h in (1, 3, 5, 7, 30):
        j = entry_idx + h - 1
        c = _safe_float(asc[j].get("close")) if j < len(asc) else None
        horizon_returns[str(h)] = round((c - entry_price) / entry_price * 100, 2) if c else None

    return {
        "entry_date": entry_bar["date"],
        "entry_price": round(entry_price, 4),
        "outcome": outcome,
        "final_return": round(final_return, 2),
        "actual_close": round(actual_close, 4) if actual_close else None,
        "trigger_date": trigger_date,
        "settle_date": settle_date,
        "hold_days": hold_days,
        "settled": settled,
        "window": window,
        "window_return": window_return,
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "horizon_returns": horizon_returns,
        "path": path,
    }


# ── bar loading (reuse the canonical fallback chain) ────────────────────────

def _load_bars(code: str, days: int) -> list[dict]:
    """Daily OHLCV via the canonical loader (stock_kline DB → parquet → efinance).

    Replaces the old direct efinance call so the tracker shares the same source
    (and the same proxy-resilient fallback) as the technical endpoint.
    """
    try:
        from quantforge.api.routes.stock_analysis import _load_bars as _lb
        return _lb(code, days) or []
    except Exception as exc:
        logger.warning(f"prediction_tracker: bar load failed for {code}: {exc}")
        return []


def _bench_close_map(earliest: str, count: int) -> dict[str, float]:
    """date→close for 沪深300 over [earliest, today]. Empty dict if unavailable."""
    try:
        from quantforge.api.routes.market import _kline_fetch
        bars = _db.kline_load(_BENCH_CODE, "day")
        if not bars or bars[-1]["date"] < _dt.date.today().isoformat():
            fetched = _kline_fetch(_BENCH_CODE, "day", max(count, 320))
            if fetched:
                _db.kline_upsert(_BENCH_CODE, "day", fetched)
                bars = _db.kline_load(_BENCH_CODE, "day")
        return {b["date"]: b["close"] for b in bars if b.get("date") and b.get("close")}
    except Exception as exc:
        logger.debug(f"prediction_tracker: benchmark unavailable: {exc}")
        return {}


def _bench_return(bench: dict[str, float], entry_date: str, settle_date: str | None) -> float | None:
    """沪深300 return over the same holding span; None if data missing."""
    if not bench or not entry_date:
        return None
    dates = sorted(bench.keys())
    start = next((d for d in dates if d >= entry_date), None)
    end_target = settle_date or (dates[-1] if dates else None)
    end = None
    for d in reversed(dates):
        if end_target and d <= end_target:
            end = d
            break
    if not start or not end or bench.get(start) in (None, 0):
        return None
    return round((bench[end] - bench[start]) / bench[start] * 100, 2)


# ── PredictionTracker ───────────────────────────────────────────────────────

class PredictionTracker:
    """Record and verify AI stock predictions (DB-backed)."""

    @staticmethod
    def record_picks(picks: list[dict], date: str | None = None,
                     pick_strategy: str = "momentum") -> None:
        """Persist a strategy's picks as predictions.

        ``pick_strategy`` 标明这批荐股来自哪种 AI 策略(momentum|pring)，让验证页能
        区分并分别统计胜率。主键防覆盖：momentum 沿用 ``{date}_{code}`` 兼容历史；
        其它策略加策略前缀 ``{date}_{strategy}_{code}``，使同日同股的不同策略荐股
        各成一行、互不覆盖。
        """
        date_key = date or _dt.date.today().isoformat()
        pick_strategy = pick_strategy or "momentum"
        prefix = "" if pick_strategy == "momentum" else f"{pick_strategy}_"
        rows = []
        for pick in picks:
            code = pick.get("code", "")
            rows.append({
                "id":            f"{date_key}_{prefix}{code}",
                "date":          date_key,
                "code":          code,
                "name":          pick.get("name", ""),
                "predicted_at":  _dt.datetime.now().isoformat(timespec="seconds"),
                "buy_price":     _safe_float(pick.get("buy_price") or pick.get("price")),
                "stop_price":    _safe_float(pick.get("stop_price")),
                "target_price":  _safe_float(pick.get("target_price")),
                "target_pct":    _safe_float(pick.get("target_pct")),
                "stop_pct":      _safe_float(pick.get("stop_pct")),
                "confidence":    _safe_float(pick.get("confidence")),
                "risk_level":    pick.get("risk_level", "中"),
                "sector":        pick.get("sector") or pick.get("industry") or None,
                "strategy_name": "; ".join(pick.get("signals", [])) or pick.get("strategy_name") or None,
                "pick_strategy": pick_strategy,
                "hit_strategies": [s.get("name", s.get("key", "")) for s in pick.get("hit_strategies", [])],
            })
        _db.predictions_upsert_many(rows)
        logger.info(f"prediction_tracker: recorded {len(rows)} {pick_strategy} predictions for {date_key}")

    @staticmethod
    async def verify_pending(
        date_from: str | None = None,
        date_to: str | None = None,
        force: bool = False,
        progress_cb=None,
    ) -> int:
        """Re-settle predictions in range via the path-based engine.

        Re-verifies anything not yet ``verified`` (still in window), plus
        already-verified rows when ``force=True``. Returns count touched.
        """
        _migrate_legacy_once()
        all_preds = _db.predictions_all()
        today = _dt.date.today().isoformat()
        upper = date_to or today

        pending = []
        for p in all_preds:
            if p.get("verified") and not force:
                continue
            d = p.get("date", "")
            if d > upper:
                continue
            if date_from and d < date_from:
                continue
            pending.append(p)

        if not pending:
            if progress_cb:
                progress_cb(0, 0)
            return 0

        from collections import defaultdict
        by_code: dict[str, list[dict]] = defaultdict(list)
        for p in pending:
            if p.get("code"):
                by_code[p["code"]].append(p)

        earliest = min(p["date"] for p in pending)
        span_days = (_dt.date.today() - _dt.date.fromisoformat(earliest)).days + VERIFY_WINDOW + 10
        bench = _bench_close_map(earliest, span_days)

        verified_count = 0
        total_codes = len(by_code)
        for idx, (code, preds) in enumerate(by_code.items()):
            grp_earliest = min(p["date"] for p in preds)
            # 多加载一段进场前的历史：动能卖点信号计算需要 warmup，否则进场后头几根
            # 动能值不可靠、易产生假卖点。_load_bars 取最近 N 天 → N 越大回溯越早。
            need_days = (_dt.date.today() - _dt.date.fromisoformat(grp_earliest)).days + VERIFY_WINDOW + 10
            bars = await asyncio.to_thread(_load_bars, code, max(need_days + 120, 180))
            if not bars:
                logger.warning(f"prediction_tracker: no bars for {code}")
                if progress_cb:
                    progress_cb(idx + 1, total_codes)
                continue

            # 动能卖点信号只依赖 bars，同一只股票批量结算时只算一次复用
            momo_sigs = None
            if any((p.get("pick_strategy") or "momentum") == "momentum" for p in preds):
                momo_sigs = await asyncio.to_thread(_momentum_sell_signals, bars)

            for p in preds:
                res = settle(p, bars, momentum_signals=momo_sigs)
                if res is None:
                    continue
                bench_ret = _bench_return(bench, res["entry_date"], res["settle_date"])
                _db.predictions_update_settlement(p["id"], {
                    "verified":          res["settled"],
                    "entry_price":       res["entry_price"],
                    "actual_close":      res["actual_close"],
                    "actual_change_pct": res["final_return"],
                    "outcome":           res["outcome"],
                    "trigger_date":      res["trigger_date"],
                    "hold_days":         res["hold_days"],
                    "bench_change_pct":  bench_ret,
                    "window_return":     res["window_return"],
                    "mfe_pct":           res["mfe_pct"],
                    "mae_pct":           res["mae_pct"],
                    "horizon_returns":   res["horizon_returns"],
                    "verified_at":       _dt.datetime.now().isoformat(timespec="seconds"),
                })
                verified_count += 1

            if progress_cb:
                progress_cb(idx + 1, total_codes)

        logger.info(f"prediction_tracker: settled {verified_count} predictions across {total_codes} codes")
        return verified_count

    @staticmethod
    def get_all() -> list[dict]:
        _migrate_legacy_once()
        return _db.predictions_all()

    @staticmethod
    def get_detail(pred_id: str, context_days: int = 180) -> dict | None:
        """Full settlement detail for one prediction (drives the detail page).

        Runs the SAME ``settle()`` engine as the list, so列表与详情永不矛盾.
        Returns prediction + settlement summary + per-day path + context bars.
        """
        _migrate_legacy_once()
        pred = _db.predictions_get(pred_id)
        if not pred:
            return None
        bars = _load_bars(pred["code"], context_days)
        res = settle(pred, bars) if bars else None
        bench = _bench_close_map(pred["date"], context_days) if res else {}
        bench_ret = _bench_return(bench, res["entry_date"], res["settle_date"]) if res else None
        return {
            "prediction": pred,
            "settlement": {k: res[k] for k in
                           ("entry_date", "entry_price", "outcome", "final_return",
                            "actual_close", "trigger_date", "settle_date", "hold_days",
                            "settled", "window", "window_return", "mfe_pct", "mae_pct",
                            "horizon_returns")}
                          if res else None,
            "bench_change_pct": bench_ret,
            "path": res["path"] if res else [],
            "context_bars": bars,
        }

    @staticmethod
    def get_stats(date_from: str | None = None, date_to: str | None = None,
                  pick_strategy: str | None = None) -> dict:
        """Accuracy stats + grouped breakdowns (荐股策略 / 命中策略 / 置信度 / 风险) +
        benchmark excess. Win rate excludes neutral (持平) from the denominator.

        ``pick_strategy`` 给定时只统计该 AI 荐股策略(momentum|pring)的样本。
        """
        _migrate_legacy_once()
        preds = [p for p in _db.predictions_all() if p.get("verified")]
        preds = [p for p in preds
                 if not (date_from and p.get("date", "") < date_from)
                 and not (date_to and p.get("date", "") > date_to)]
        if pick_strategy:
            preds = [p for p in preds if (p.get("pick_strategy") or "momentum") == pick_strategy]

        total = len(preds)
        if total == 0:
            return {"total": 0, "accuracy_pct": None, "by_pick_strategy": [],
                    "by_strategy": [], "by_confidence": [], "by_risk": [],
                    "by_sector": [], "by_horizon": [], "efficacy": None}

        def _outcome_counts(rows):
            wins = sum(1 for p in rows if p.get("outcome") in ("hit_target", "positive"))
            losses = sum(1 for p in rows if p.get("outcome") in ("hit_stop", "negative"))
            neutral = sum(1 for p in rows if p.get("outcome") == "neutral")
            decisive = wins + losses
            wr = round(wins / decisive * 100, 1) if decisive else None
            changes = [p["actual_change_pct"] for p in rows if p.get("actual_change_pct") is not None]
            avg = round(sum(changes) / len(changes), 2) if changes else None
            return {"total": len(rows), "win": wins, "loss": losses, "neutral": neutral,
                    "win_rate": wr, "avg_change": avg}

        overall = _outcome_counts(preds)
        hits = sum(1 for p in preds if p.get("outcome") == "hit_target")
        stops = sum(1 for p in preds if p.get("outcome") == "hit_stop")

        changes = [p["actual_change_pct"] for p in preds if p.get("actual_change_pct") is not None]
        pos_changes = [c for c in changes if c > 0]
        neg_changes = [c for c in changes if c < 0]

        # 基准/超额：仅在有 benchmark 的样本上算
        paired = [(p["actual_change_pct"], p["bench_change_pct"]) for p in preds
                  if p.get("actual_change_pct") is not None and p.get("bench_change_pct") is not None]
        bench_avg = round(sum(b for _, b in paired) / len(paired), 2) if paired else None
        excess_avg = round(sum(a - b for a, b in paired) / len(paired), 2) if paired else None
        beat_bench = sum(1 for a, b in paired if a > b)
        beat_rate = round(beat_bench / len(paired) * 100, 1) if paired else None

        # 按 AI 荐股策略（momentum / pring）—— 区分「哪种荐股」的胜率对比
        from collections import defaultdict
        _PICK_STRAT_CN = {"momentum": "动能买点", "pring": "普林格KST周期"}
        ps_groups: dict[str, list] = defaultdict(list)
        for p in preds:
            ps_groups[p.get("pick_strategy") or "momentum"].append(p)
        by_pick_strategy = sorted(
            [{"key": k, "label": _PICK_STRAT_CN.get(k, k), **_outcome_counts(v)}
             for k, v in ps_groups.items()],
            key=lambda x: -x["total"],
        )

        # 按命中策略（hit_strategies 展开，fallback strategy_name）
        strat_groups: dict[str, list] = defaultdict(list)
        for p in preds:
            names = p.get("hit_strategies") or ([p["strategy_name"]] if p.get("strategy_name") else [])
            for n in (names or ["未标注"]):
                strat_groups[n].append(p)
        by_strategy = sorted(
            [{"strategy": k, **_outcome_counts(v)} for k, v in strat_groups.items()],
            key=lambda x: (-(x["win_rate"] or -1), -x["total"]),
        )

        # 按置信度分桶
        def _conf_bucket(c):
            if c is None:
                return "未知"
            return "≥80" if c >= 80 else "60–79" if c >= 60 else "<60"
        conf_groups: dict[str, list] = defaultdict(list)
        for p in preds:
            conf_groups[_conf_bucket(p.get("confidence"))].append(p)
        conf_order = {"≥80": 0, "60–79": 1, "<60": 2, "未知": 3}
        by_confidence = sorted(
            [{"bucket": k, **_outcome_counts(v)} for k, v in conf_groups.items()],
            key=lambda x: conf_order.get(x["bucket"], 9),
        )

        # 按风险
        risk_groups: dict[str, list] = defaultdict(list)
        for p in preds:
            risk_groups[p.get("risk_level") or "中"].append(p)
        risk_order = {"低": 0, "中": 1, "高": 2}
        by_risk = sorted(
            [{"risk": k, **_outcome_counts(v)} for k, v in risk_groups.items()],
            key=lambda x: risk_order.get(x["risk"], 9),
        )

        # 按行业（来自 AI 荐股 sector；老数据无该字段归入「未知」）
        sector_groups: dict[str, list] = defaultdict(list)
        for p in preds:
            sector_groups[p.get("sector") or "未知"].append(p)
        by_sector = sorted(
            [{"sector": k, **_outcome_counts(v)} for k, v in sector_groups.items()
             if k != "未知" or len(v) == total],   # 全部未知时仍展示一行
            key=lambda x: (-(x["win_rate"] if x["win_rate"] is not None else -1), -x["total"]),
        )

        # 止盈止损有效性：对比「按规则结算」与「硬扛到窗口末」
        def _avg(xs):
            xs = [x for x in xs if x is not None]
            return round(sum(xs) / len(xs), 2) if xs else None

        stop_rows = [p for p in preds if p.get("outcome") == "hit_stop"]
        tgt_rows = [p for p in preds if p.get("outcome") == "hit_target"]
        # 止损救命：若一直持有反而更差(window_return < 锁定止损收益)；误杀：持有反而更好
        stop_saved = sum(1 for p in stop_rows
                         if p.get("window_return") is not None and p.get("actual_change_pct") is not None
                         and p["window_return"] < p["actual_change_pct"])
        stop_mistaken = sum(1 for p in stop_rows
                            if p.get("window_return") is not None and p.get("actual_change_pct") is not None
                            and p["window_return"] > p["actual_change_pct"])
        # 卖飞：达目标后窗口内最高(mfe)仍显著高于锁定目标收益
        tgt_left = _avg([p["mfe_pct"] - p["actual_change_pct"] for p in tgt_rows
                         if p.get("mfe_pct") is not None and p.get("actual_change_pct") is not None])
        efficacy = {
            "ruled_avg": _avg([p.get("actual_change_pct") for p in preds]),
            "held_avg":  _avg([p.get("window_return") for p in preds]),
            "stop": {
                "n": len(stop_rows),
                "avg_locked":  _avg([p.get("actual_change_pct") for p in stop_rows]),
                "avg_if_held": _avg([p.get("window_return") for p in stop_rows]),
                "saved": stop_saved, "mistaken": stop_mistaken,
            },
            "target": {
                "n": len(tgt_rows),
                "avg_locked": _avg([p.get("actual_change_pct") for p in tgt_rows]),
                "avg_mfe":    _avg([p.get("mfe_pct") for p in tgt_rows]),
                "left_on_table": tgt_left,
            },
        }

        # 多窗口回测：各窗口的买入持有 N 日收益（无止盈止损）→ 1日(昨日)/3日/5日/30日
        by_horizon = []
        for h in ("1", "3", "5", "30"):
            rs = [hr.get(h) for p in preds
                  if (hr := (p.get("horizon_returns") or {})).get(h) is not None]
            if rs:
                wins = sum(1 for v in rs if v > 0)
                loss = sum(1 for v in rs if v < 0)
                dec = wins + loss
                by_horizon.append({
                    "horizon": int(h), "total": len(rs),
                    "win_rate": round(wins / dec * 100, 1) if dec else None,
                    "avg_change": round(sum(rs) / len(rs), 2),
                })

        return {
            "total":            total,
            "hit_target":       hits,
            "hit_stop":         stops,
            "win":              overall["win"],
            "loss":             overall["loss"],
            "neutral":          overall["neutral"],
            "accuracy_pct":     overall["win_rate"],   # = win/(win+loss), neutral 不计入
            "avg_change_pct":   overall["avg_change"],
            "avg_positive_pct": round(sum(pos_changes) / len(pos_changes), 2) if pos_changes else None,
            "avg_negative_pct": round(sum(neg_changes) / len(neg_changes), 2) if neg_changes else None,
            "benchmark_avg_pct": bench_avg,
            "excess_avg_pct":   excess_avg,
            "beat_benchmark":   beat_bench,
            "beat_benchmark_pct": beat_rate,
            "by_pick_strategy": by_pick_strategy,
            "by_strategy":      by_strategy,
            "by_confidence":    by_confidence,
            "by_risk":          by_risk,
            "by_sector":        by_sector,
            "by_horizon":       by_horizon,
            "efficacy":         efficacy,
        }

    @staticmethod
    def get_recent_winrate(pick_strategy: str | None = None, days: int = 1) -> dict:
        """昨日(默认)或最近 N 个交易日推荐股票的胜率 + 平均收益。

        首页「昨日策略命中率」卡用它：不是全量历史胜率，而是最近一批推荐到现在的
        表现。这批推荐通常尚未到结算窗口(verified=0)，但每日结算器会对未到期的也跑
        ``settle()`` 并把当前 ``actual_change_pct``(买入价→最新收盘)写库，故这里直接
        读库即可。胜=收益>0，负=收益<0，持平不计入分母。

        ``days``：统计窗口。``1``(默认)=最近一个过去推荐日(即「昨日」)；``N>1``=
        过去 N 个自然日内(< 今天)的全部推荐合并统计，供首页周期切换(近3/7/30日)。
        """
        _migrate_legacy_once()
        today = _dt.date.today()
        today_s = today.isoformat()
        preds = _db.predictions_all()
        if pick_strategy:
            preds = [p for p in preds if (p.get("pick_strategy") or "momentum") == pick_strategy]

        # days=0: 实时模式——今日推荐 vs 当前股价(stock_quote 快照)
        if days == 0:
            today_picks = [p for p in preds if p.get("date", "") == today_s]
            if not today_picks:
                return {"date": today_s, "days": 0, "total": 0, "evaluated": 0,
                        "win": 0, "loss": 0, "neutral": 0,
                        "win_rate": None, "avg_change": None, "is_realtime": True}
            codes = [p["code"] for p in today_picks if p.get("code")]
            quote_map = _db.quote_get_many(codes) if codes else {}
            changes = []
            for p in today_picks:
                q = quote_map.get(p.get("code", ""), {})
                chg = q.get("change_pct")
                if chg is not None:
                    changes.append(chg)
            wins = sum(1 for c in changes if c > 0)
            losses = sum(1 for c in changes if c < 0)
            decisive = wins + losses
            return {
                "date": today_s, "days": 0,
                "total": len(today_picks), "evaluated": len(changes),
                "win": wins, "loss": losses, "neutral": len(changes) - decisive,
                "win_rate": round(wins / decisive * 100, 1) if decisive else None,
                "avg_change": round(sum(changes) / len(changes), 2) if changes else None,
                "is_realtime": True,
            }

        past = [p for p in preds if p.get("date", "") < today_s]
        if not past:
            return {"date": None, "days": days, "total": 0, "evaluated": 0,
                    "win": 0, "loss": 0, "neutral": 0,
                    "win_rate": None, "avg_change": None}

        if days and days > 1:
            # 近 N 自然日：[今天-N, 今天) 区间内的全部推荐合并。
            since = (today - _dt.timedelta(days=days)).isoformat()
            rows = [p for p in past if p.get("date", "") >= since]
            window_dates = sorted({p.get("date", "") for p in rows})
            label = f"{window_dates[0]}~{window_dates[-1]}" if window_dates else None
        else:
            # 昨日：最近一个「过去」的推荐日那一批。
            recent = max(p.get("date", "") for p in past)
            rows = [p for p in past if p.get("date") == recent]
            label = recent

        scored = [p for p in rows if p.get("actual_change_pct") is not None]
        wins = sum(1 for p in scored if p["actual_change_pct"] > 0)
        losses = sum(1 for p in scored if p["actual_change_pct"] < 0)
        neutral = sum(1 for p in scored if p["actual_change_pct"] == 0)
        decisive = wins + losses
        changes = [p["actual_change_pct"] for p in scored]
        return {
            "date": label,
            "days": days,
            "total": len(rows),
            "evaluated": len(scored),
            "win": wins,
            "loss": losses,
            "neutral": neutral,
            "win_rate": round(wins / decisive * 100, 1) if decisive else None,
            "avg_change": round(sum(changes) / len(changes), 2) if changes else None,
        }

    @staticmethod
    def get_strategy_winrate(pick_strategy: str | None = None) -> dict:
        """某策略「今日胜率」多周期面板：实时 + 持有 3/7/30 个交易日。

        - **实时**：今日该策略的推荐，按「今日**开盘价**买入 → 当前**现价**」算收益，
          胜=收益>0。开盘价/现价取自 stock_quote 快照(open/price)；今日尚未给出
          open 的票不计入。
        - **3/7/30 日**：对该策略**所有已结算**推荐，复用 ``settle()`` 落库的
          ``horizon_returns``（进场日开盘价买入、持有 N 个交易日后按当日收盘退出、
          无止盈止损）聚合胜率 + 平均收益。今日票尚未满 N 日、缺该窗口，自然不计入。

        ``pick_strategy`` 为 None 时合并所有策略（首页「策略命中率」卡用）。
        """
        _migrate_legacy_once()
        today_s = _dt.date.today().isoformat()
        preds = _db.predictions_all()
        if pick_strategy:
            preds = [p for p in preds if (p.get("pick_strategy") or "momentum") == pick_strategy]

        horizons: list[dict] = []

        # ── 实时：今日推荐 开盘价→现价 ──────────────────────────────────
        today_picks = [p for p in preds if p.get("date", "") == today_s]
        rt = {"key": "realtime", "label": "实时", "is_realtime": True,
              "total": len(today_picks), "evaluated": 0, "win": 0, "loss": 0,
              "neutral": 0, "win_rate": None, "avg_change": None}
        if today_picks:
            codes = [p["code"] for p in today_picks if p.get("code")]
            qmap = _db.quote_get_many(codes) if codes else {}
            rts = []
            for p in today_picks:
                q = qmap.get(p.get("code", "")) or {}
                op = _safe_float(q.get("open"))
                cur = _safe_float(q.get("price"))
                if op and op > 0 and cur is not None:
                    rts.append((cur - op) / op * 100)
            wins = sum(1 for c in rts if c > 0)
            loss = sum(1 for c in rts if c < 0)
            dec = wins + loss
            rt.update(evaluated=len(rts), win=wins, loss=loss, neutral=len(rts) - dec,
                      win_rate=round(wins / dec * 100, 1) if dec else None,
                      avg_change=round(sum(rts) / len(rts), 2) if rts else None)
        horizons.append(rt)

        # ── 持有 N 个交易日聚合（已结算样本，复用 horizon_returns）────────
        verified = [p for p in preds if p.get("verified")]
        _LBL = {"3": "3日", "7": "7日", "30": "30日"}
        for h in ("3", "7", "30"):
            rs = [v for p in verified
                  if (v := (p.get("horizon_returns") or {}).get(h)) is not None]
            wins = sum(1 for v in rs if v > 0)
            loss = sum(1 for v in rs if v < 0)
            dec = wins + loss
            horizons.append({
                "key": h, "label": _LBL[h], "is_realtime": False,
                "total": len(rs), "evaluated": len(rs),
                "win": wins, "loss": loss, "neutral": len(rs) - dec,
                "win_rate": round(wins / dec * 100, 1) if dec else None,
                "avg_change": round(sum(rs) / len(rs), 2) if rs else None,
            })

        return {"pick_strategy": pick_strategy or "all", "date": today_s,
                "horizons": horizons}

    @staticmethod
    def backfill_hit_strategies() -> int:
        from quantforge.screener.cache import get_cached
        summary = get_cached()
        if not summary:
            return 0
        code_strategies: dict[str, list[str]] = {}
        for key, result in summary.get("results", {}).items():
            strat = result.get("strategy", {})
            for s in result.get("stocks", [])[:20]:
                code = s.get("code", "")
                if code:
                    code_strategies.setdefault(code, []).append(strat.get("display_name", key))

        count = 0
        rows = []
        for p in _db.predictions_all():
            if p.get("hit_strategies"):
                continue
            strats = code_strategies.get(p.get("code", ""), [])
            if strats:
                # 传完整行（含原 pick 字段），仅替换 hit_strategies，避免 upsert 把
                # name/价位等覆盖成 NULL；结算字段不在 UPDATE 子句内，天然保留。
                rows.append({**p, "hit_strategies": strats})
                count += 1
        if rows:
            _db.predictions_upsert_many(rows)
            logger.info(f"prediction_tracker: backfilled hit_strategies for {count} predictions")
        return count

    @staticmethod
    def delete(prediction_ids: list[str]) -> int:
        return _db.predictions_delete(prediction_ids)
