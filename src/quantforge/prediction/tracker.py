"""Prediction tracker — record AI picks and verify against actual results.

Verification logic:
  - entry_price  = prediction date's open price (date = next trading day)
  - actual_close = latest available daily close (last bar in history)
  - actual_change_pct = (actual_close - entry_price) / entry_price × 100

Timeline:
  Picks are generated after market close (15:00) or before next open.
  The prediction date is always set to the NEXT trading day (the day
  the user will actually buy), so entry_price = date's open price.

Storage: data/cache/predictions.json
"""

from __future__ import annotations

import asyncio
import json
import datetime as _dt
import math
from pathlib import Path

from loguru import logger

_PREDICTIONS_FILE = Path("data/cache/predictions.json")


# ── Data helpers ───────────────────────────────────────────────────────────────

def _load() -> dict:
    if _PREDICTIONS_FILE.exists():
        try:
            return json.loads(_PREDICTIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"predictions": []}


def _save(data: dict) -> None:
    try:
        _PREDICTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PREDICTIONS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"prediction tracker save failed: {e}")


def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    except Exception:
        return None


def _date_str(d: str | _dt.date) -> str:
    """Return YYYYMMDD string for efinance API."""
    if isinstance(d, str):
        return d.replace("-", "")
    return d.strftime("%Y%m%d")


# ── PredictionTracker ──────────────────────────────────────────────────────────

class PredictionTracker:
    """Record and verify AI stock predictions."""

    @staticmethod
    def record_picks(picks: list[dict], date: str | None = None) -> None:
        """Save today's AI picks as unverified predictions.

        Each pick should have: code, name, buy_price, stop_price, target_price,
        target_pct, confidence, risk_level, signals.
        """
        date_key = date or _dt.date.today().isoformat()
        data = _load()
        predictions: list[dict] = data["predictions"]

        # Remove any existing predictions for this date (idempotent refresh)
        predictions = [p for p in predictions if p.get("date") != date_key]

        for pick in picks:
            predictions.append({
                "id":           f"{date_key}_{pick.get('code', '')}",
                "date":         date_key,
                "code":         pick.get("code", ""),
                "name":         pick.get("name", ""),
                "predicted_at": _dt.datetime.now().isoformat(timespec="seconds"),
                # AI's suggested entry — kept for reference only
                "buy_price":    _safe_float(pick.get("buy_price") or pick.get("price")),
                "stop_price":   _safe_float(pick.get("stop_price")),
                "target_price": _safe_float(pick.get("target_price")),
                "target_pct":   _safe_float(pick.get("target_pct")),
                "stop_pct":     _safe_float(pick.get("stop_pct")),
                "confidence":   pick.get("confidence"),
                "risk_level":   pick.get("risk_level", "中"),
                "strategy_name": "; ".join(pick.get("signals", [])) or pick.get("strategy_name") or None,
                "hit_strategies": [s.get("name", s.get("key", "")) for s in pick.get("hit_strategies", [])],
                # Verification fields (filled later)
                "verified":          False,
                "entry_price":       None,   # date's open price — user buys here
                "actual_close":      None,   # latest close at verification time
                "actual_change_pct": None,   # (actual_close - entry_price) / entry_price %
                "outcome":           None,   # "hit_target"|"hit_stop"|"positive"|"negative"|"neutral"
                "verified_at":       None,
            })

        data["predictions"] = predictions
        _save(data)
        logger.info(f"prediction_tracker: recorded {len(picks)} predictions for {date_key}")

    @staticmethod
    async def verify_pending(
        date_from: str | None = None,
        date_to: str | None = None,
        force: bool = False,
    ) -> int:
        """Verify predictions using historical daily K-line data.

        For each pending prediction on date D:
          - entry_price  = open of the first trading day >= D (same day)
          - actual_close = close of the last available trading day
          - actual_change_pct = (actual_close - entry_price) / entry_price × 100

        If force=True, re-verify already verified predictions too.
        Returns the number of predictions successfully verified.
        """
        data = _load()
        predictions: list[dict] = data["predictions"]
        today = _dt.date.today().isoformat()
        upper = date_to or today

        pending = []
        for p in predictions:
            if p.get("verified") and not force:
                continue
            d = p.get("date", "")
            if d > upper:
                continue
            if date_from and d < date_from:
                continue
            pending.append(p)

        if not pending:
            return 0

        # Group by code so we fetch each stock's history once
        from collections import defaultdict
        by_code: dict[str, list[dict]] = defaultdict(list)
        for p in pending:
            code = p.get("code", "")
            if code:
                by_code[code].append(p)

        try:
            import efinance as ef
        except ImportError:
            logger.warning("prediction_tracker: efinance not installed")
            return 0

        verified_count = 0
        today_compact = _date_str(today)

        for code, preds in by_code.items():
            # Fetch daily K-line from the earliest prediction date to today
            earliest = min(p["date"] for p in preds)
            beg = _date_str(earliest)

            try:
                def _fetch_history(c=code, b=beg, e=today_compact):
                    return ef.stock.get_quote_history(c, beg=b, end=e, klt=101)

                df = await asyncio.to_thread(_fetch_history)
                if df is None or df.empty:
                    logger.warning(f"prediction_tracker: no history for {code}")
                    continue
            except Exception as exc:
                logger.warning(f"prediction_tracker: history fetch failed for {code}: {exc}")
                continue

            # Normalise column names (efinance returns Chinese headers)
            # Typical columns: 日期, 开盘, 收盘, 最高, 最低, 成交量, ...
            col_names = list(df.columns)
            # Find date, open, close columns by position if names vary
            try:
                date_col  = next(c for c in col_names if '日期' in c)
                open_col  = next(c for c in col_names if '开盘' in c)
                close_col = next(c for c in col_names if '收盘' in c)
            except StopIteration:
                # Fallback: use positional (日期=0, 开盘=1, 收盘=2 in most ef versions)
                date_col, open_col, close_col = col_names[0], col_names[1], col_names[2]

            # Build date→{open, close} lookup
            bars: dict[str, dict] = {}
            for _, row in df.iterrows():
                try:
                    bar_date = str(row[date_col]).strip()[:10]  # YYYY-MM-DD
                    o = _safe_float(row[open_col])
                    c = _safe_float(row[close_col])
                    if o and c:
                        bars[bar_date] = {"open": o, "close": c}
                except Exception:
                    continue

            if not bars:
                continue

            sorted_dates = sorted(bars.keys())

            for p in preds:
                pred_date = p["date"]

                # date is always the buying day → entry = that day's open
                next_day_dates = [d for d in sorted_dates if d >= pred_date]
                if not next_day_dates:
                    # Market hasn't opened yet after this prediction — skip
                    continue
                entry_date = next_day_dates[0]
                entry_price = bars[entry_date]["open"]

                if not entry_price or entry_price <= 0:
                    continue

                # actual_close = close of the most recent available trading day
                actual_close = bars[sorted_dates[-1]]["close"]

                if not actual_close or actual_close <= 0:
                    continue

                change_pct = round((actual_close - entry_price) / entry_price * 100, 2)

                target = p.get("target_price")
                stop   = p.get("stop_price")

                # Outcome: check if price ever reached target or stop during holding
                # (simplified: use final close vs levels — full bar-by-bar scan would be ideal)
                outcome = "neutral"
                if target and actual_close >= target:
                    outcome = "hit_target"
                elif stop and actual_close <= stop:
                    outcome = "hit_stop"
                elif change_pct > 0:
                    outcome = "positive"
                elif change_pct < 0:
                    outcome = "negative"

                p["verified"]          = True
                p["entry_price"]       = round(entry_price, 4)
                p["actual_close"]      = round(actual_close, 4)
                p["actual_change_pct"] = change_pct
                p["outcome"]           = outcome
                p["verified_at"]       = _dt.datetime.now().isoformat(timespec="seconds")
                verified_count += 1

        _save(data)
        logger.info(f"prediction_tracker: verified {verified_count} predictions")
        return verified_count

    @staticmethod
    def get_all() -> list[dict]:
        return _load()["predictions"]

    @staticmethod
    def get_stats(date_from: str | None = None, date_to: str | None = None) -> dict:
        """Return accuracy statistics over verified predictions."""
        all_preds = [p for p in _load()["predictions"] if p.get("verified")]
        preds = []
        for p in all_preds:
            d = p.get("date", "")
            if date_from and d < date_from:
                continue
            if date_to and d > date_to:
                continue
            preds.append(p)

        total = len(preds)
        if total == 0:
            return {"total": 0, "accuracy": None}

        hits  = sum(1 for p in preds if p.get("outcome") == "hit_target")
        stops = sum(1 for p in preds if p.get("outcome") == "hit_stop")
        pos   = sum(1 for p in preds if p.get("outcome") in ("hit_target", "positive"))
        neg   = sum(1 for p in preds if p.get("outcome") in ("hit_stop", "negative"))
        accuracy = round(pos / total * 100, 1)

        # avg_change uses entry_price-based pct
        changes = [p["actual_change_pct"] for p in preds if p.get("actual_change_pct") is not None]
        avg_change = round(sum(changes) / len(changes), 2) if changes else None

        pos_changes = [c for c in changes if c > 0]
        neg_changes = [c for c in changes if c < 0]
        avg_pos = round(sum(pos_changes) / len(pos_changes), 2) if pos_changes else None
        avg_neg = round(sum(neg_changes) / len(neg_changes), 2) if neg_changes else None

        return {
            "total":            total,
            "hit_target":       hits,
            "hit_stop":         stops,
            "positive":         pos,
            "negative":         neg,
            "accuracy_pct":     accuracy,
            "avg_change_pct":   avg_change,
            "avg_positive_pct": avg_pos,
            "avg_negative_pct": avg_neg,
        }

    @staticmethod
    def backfill_hit_strategies() -> int:
        """Backfill hit_strategies from screener cache for predictions missing it."""
        from quantforge.screener.cache import get_cached
        summary = get_cached()
        if not summary:
            return 0

        # Build code → strategy names mapping from screener results
        code_strategies: dict[str, list[str]] = {}
        for key, result in summary.get("results", {}).items():
            strat = result.get("strategy", {})
            for s in result.get("stocks", [])[:20]:
                code = s.get("code", "")
                if code:
                    code_strategies.setdefault(code, []).append(
                        strat.get("display_name", key)
                    )

        data = _load()
        count = 0
        for p in data["predictions"]:
            if p.get("hit_strategies"):
                continue
            code = p.get("code", "")
            strats = code_strategies.get(code, [])
            if strats:
                p["hit_strategies"] = strats
                count += 1

        if count:
            _save(data)
            logger.info(f"prediction_tracker: backfilled hit_strategies for {count} predictions")
        return count

    @staticmethod
    def delete(prediction_ids: list[str]) -> int:
        """Delete predictions by id. Returns number deleted."""
        data = _load()
        before = len(data["predictions"])
        data["predictions"] = [p for p in data["predictions"] if p.get("id") not in prediction_ids]
        _save(data)
        return before - len(data["predictions"])
