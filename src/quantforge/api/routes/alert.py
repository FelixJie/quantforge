"""Price / change / volume alert engine — per-user price monitors with push notifications.

How it works
============
Each user defines rules like "600519 突破 1800 元" or "000001 跌幅超过 -3%".
Rules are persisted to `data/alerts/{user_id}.json`.

Two detection flows:

1. **On-demand check** — `POST /api/alerts/check` (manual or UI-driven).
   Fetches latest quotes via `efinance`, compares each rule's condition, and
   records newly triggered events in the user's notification list.
2. **Background polling** — a lightweight async task inside `app.lifespan`
   can periodically call `check_all()` when enabled.

Rule types supported
====================
- `price_above`    : price > target
- `price_below`    : price < target
- `change_above`   : percent change > +target%
- `change_below`   : percent change < -target%
- `volume_spike`   : current volume > (avg_20d * target_multiple)

Endpoints
=========
  GET    /api/alerts/             → list user's rules
  POST   /api/alerts/             → create a new rule
  DELETE /api/alerts/{rule_id}    → remove a rule
  PUT    /api/alerts/{rule_id}/enable → toggle enabled flag
  POST   /api/alerts/check        → run the detection engine once
  GET    /api/alerts/notifications  → list recent notifications
  POST   /api/alerts/notifications/read → mark notifications as read
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from quantforge.api.routes.auth import get_current_user

router = APIRouter(prefix="/alerts", tags=["alerts"])

_DATA_DIR = Path(__file__).parent.parent.parent.parent.parent / "data"
_ALERTS_DIR = _DATA_DIR / "alerts"
_NOTIF_DIR = _DATA_DIR / "notifications"
_ALERTS_DIR.mkdir(parents=True, exist_ok=True)
_NOTIF_DIR.mkdir(parents=True, exist_ok=True)


# ── Schemas ────────────────────────────────────────────────────────────────

class AlertRule(BaseModel):
    id: str
    code: str
    name: Optional[str] = ""
    type: str  # price_above | price_below | change_above | change_below | volume_spike
    target: float
    enabled: bool = True
    created_at: str
    last_triggered_at: Optional[str] = None
    notes: Optional[str] = ""


class AlertCreateRequest(BaseModel):
    code: str
    name: Optional[str] = ""
    type: str
    target: float
    notes: Optional[str] = ""


class AlertNotification(BaseModel):
    id: str
    rule_id: str
    code: str
    name: str
    type: str
    target: float
    triggered_at: str
    price: Optional[float] = None
    change_pct: Optional[float] = None
    message: str
    read: bool = False


# ── File helpers ────────────────────────────────────────────────────────────

def _alerts_path(user_id: str) -> Path:
    return _ALERTS_DIR / f"{user_id}.json"


def _notif_path(user_id: str) -> Path:
    return _NOTIF_DIR / f"{user_id}.json"


def _load_alerts(user_id: str) -> Dict[str, Any]:
    p = _alerts_path(user_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"rules": []}


def _save_alerts(user_id: str, data: Dict[str, Any]) -> None:
    _alerts_path(user_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_notifications(user_id: str) -> Dict[str, Any]:
    p = _notif_path(user_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"notifications": []}


def _save_notifications(user_id: str, data: Dict[str, Any]) -> None:
    _notif_path(user_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _append_notification(user_id: str, notif: Dict[str, Any]) -> None:
    data = _load_notifications(user_id)
    notifs = data.get("notifications", [])
    notifs.insert(0, notif)
    # Keep only the latest 200 notifications per user
    data["notifications"] = notifs[:200]
    _save_notifications(user_id, data)


# ── Quote fetching (thin wrapper around efinance) ──────────────────────────

async def _fetch_quote(code: str) -> Optional[Dict[str, Any]]:
    """Fetch latest quote for a single code.  Returns None on failure."""
    import asyncio

    def _sync():
        try:
            import efinance as ef

            df = ef.stock.get_latest_quote(code)
            if df is None or df.empty:
                return None
            row = df.iloc[0]
            code_val = str(row.iloc[0]).strip()
            name_val = str(row.iloc[1]).strip() if len(row) > 1 else code_val
            try:
                price = float(row.iloc[3]) if len(row) > 3 else None
            except (ValueError, TypeError):
                price = None
            try:
                change_pct = float(row.iloc[2]) if len(row) > 2 else None
            except (ValueError, TypeError):
                change_pct = None
            try:
                volume = float(row.iloc[6]) if len(row) > 6 else None
            except (ValueError, TypeError):
                volume = None
            try:
                pre_close = float(row.iloc[13]) if len(row) > 13 else None
            except (ValueError, TypeError):
                pre_close = None
            return {
                "code": code_val,
                "name": name_val,
                "price": price,
                "change_pct": change_pct,
                "volume": volume,
                "pre_close": pre_close,
            }
        except Exception:
            return None

    try:
        return await asyncio.to_thread(_sync)
    except Exception:
        return None


async def _fetch_quotes_batch(codes) -> Dict[str, Dict[str, Any]]:
    """Batch-fetch quotes via the shared datasource (腾讯/iFinD, works behind proxy).

    One network round-trip for the whole code set — far cheaper than per-rule
    efinance calls.  ``volume`` is not provided here, so volume_spike rules are
    only evaluated on the manual ``/check`` path (which uses efinance per rule).
    """
    import asyncio

    codes = list({c for c in codes if c})
    if not codes:
        return {}

    def _sync():
        try:
            from quantforge.data.feed import datasource
            raw = datasource.quotes(codes)
            out: Dict[str, Dict[str, Any]] = {}
            for c, q in (raw or {}).items():
                out[c] = {
                    "code": c,
                    "name": q.get("name"),
                    "price": q.get("price"),
                    "change_pct": q.get("change_pct"),
                    "volume": None,
                    "pre_close": q.get("last_close"),
                    # 智能盯盘要用的富字段(腾讯门面已提供)
                    "vol_ratio": q.get("vol_ratio"),
                    "high": q.get("high"),
                    "low": q.get("low"),
                    "open": q.get("open"),
                    "limit_up": q.get("limit_up"),
                    "limit_down": q.get("limit_down"),
                }
            return out
        except Exception:
            return {}

    try:
        return await asyncio.to_thread(_sync)
    except Exception:
        return {}


# ── 智能盯盘辅助：价格滚动历史 + 日线(只读本地，无网络) ─────────────────────────
import time as _time

# code -> [(epoch, price), ...]，仅保留最近 ~15min，供快速拉升/跳水 & 均线穿越判定
_PRICE_HIST: Dict[str, list] = {}
_HIST_WINDOW = 900          # 15 分钟
_RAPID_WINDOW = 300         # 快速拉升/跳水观察窗口 5 分钟


def _record_prices(quote_map: Dict[str, Dict[str, Any]]) -> None:
    """把本轮行情写入滚动价格历史(每轮全局调用一次即可)。"""
    now = _time.time()
    for code, q in (quote_map or {}).items():
        p = q.get("price")
        if p is None:
            continue
        hist = _PRICE_HIST.setdefault(code, [])
        if hist and now - hist[-1][0] < 20:   # 同一轮多用户重复，20s 内去重
            continue
        hist.append((now, float(p)))
        cutoff = now - _HIST_WINDOW
        while hist and hist[0][0] < cutoff:
            hist.pop(0)


def _price_ago(code: str, seconds: int) -> Optional[float]:
    """返回 ~seconds 秒前的价格(取窗口内最早一笔)，不足则 None。"""
    hist = _PRICE_HIST.get(code) or []
    if not hist:
        return None
    now = _time.time()
    older = [p for t, p in hist if now - t >= seconds]
    if older:
        return older[-1]
    if hist and now - hist[0][0] >= seconds * 0.6:
        return hist[0][1]
    return None


_bars_cache: Dict[str, tuple] = {}    # code -> (ts, bars)


def _daily_bars(code: str) -> list:
    """本地日线(只读 db_cache，自选已后台预热)，60s 进程缓存。"""
    now = _time.time()
    ts, bars = _bars_cache.get(code, (0, None))
    if bars is not None and now - ts < 60:
        return bars
    try:
        from quantforge.data.storage import db_cache
        bars = db_cache.kline_load(code, "day", 90) or []
    except Exception:
        bars = []
    _bars_cache[code] = (now, bars)
    return bars


def _today_str() -> str:
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _closed_bars(code: str, n: int) -> list:
    """最近 n 根**已收盘**日线(剔除当日那根)，oldest→newest。"""
    bars = _daily_bars(code)
    today = _today_str()
    closed = [b for b in bars if str(b.get("date") or "")[:10] != today]
    return closed[-n:] if n > 0 else closed


# ── Detection engine ────────────────────────────────────────────────────────

def _should_trigger(rule: Dict[str, Any], quote: Dict[str, Any]) -> Optional[str]:
    """Return a human-readable message if the rule fires; else None."""
    rule_type = rule.get("type", "")
    target = float(rule.get("target", 0))
    code = rule.get("code", "")
    name = rule.get("name", "") or code

    price = quote.get("price")
    change_pct = quote.get("change_pct")
    volume = quote.get("volume")

    if rule_type == "price_above" and price is not None and price > target:
        return f"{name}({code}) 当前价格 {price:.2f} 突破了您的预警线 {target:.2f}"
    if rule_type == "price_below" and price is not None and price < target:
        return f"{name}({code}) 当前价格 {price:.2f} 跌破了您的预警线 {target:.2f}"
    if rule_type == "change_above" and change_pct is not None and change_pct > target:
        return f"{name}({code}) 当前涨幅 {change_pct:.2f}% 超过了您的预警阈值 {target:.2f}%"
    if rule_type == "change_below" and change_pct is not None and change_pct < -target:
        return f"{name}({code}) 当前跌幅 {change_pct:.2f}% 超过了您的预警阈值 -{target:.2f}%"
    if rule_type == "volume_spike" and volume is not None and volume > target:
        return f"{name}({code}) 当前成交量 {volume:,.0f} 超过了您的预警阈值 {target:,.0f}"

    # ── 智能盯盘类 ─────────────────────────────────────────────────────────
    # 快速拉升/跳水：5 分钟内涨/跌幅达到 target%
    if rule_type in ("rapid_rise", "rapid_fall") and price is not None:
        ref = _price_ago(code, _RAPID_WINDOW)
        if ref and ref > 0:
            move = (price - ref) / ref * 100
            if rule_type == "rapid_rise" and move >= target:
                return f"{name}({code}) 5分钟内快速拉升 {move:+.2f}%（现价 {price:.2f}）"
            if rule_type == "rapid_fall" and move <= -target:
                return f"{name}({code}) 5分钟内快速跳水 {move:.2f}%（现价 {price:.2f}）"

    # 封涨停 / 触及跌停（现价贴近涨/跌停价）
    if rule_type == "limit_up" and price is not None and quote.get("limit_up"):
        if price >= float(quote["limit_up"]) * 0.999:
            return f"{name}({code}) 封涨停 {price:.2f}（涨停价 {float(quote['limit_up']):.2f}）"
    if rule_type == "limit_down" and price is not None and quote.get("limit_down"):
        if price <= float(quote["limit_down"]) * 1.001:
            return f"{name}({code}) 触及跌停 {price:.2f}（跌停价 {float(quote['limit_down']):.2f}）"

    # 量比放大
    if rule_type == "vol_ratio_above":
        vr = quote.get("vol_ratio")
        if vr is not None and float(vr) >= target:
            return f"{name}({code}) 量比放大至 {float(vr):.2f}（阈值 {target:.2f}）"

    # 创 N 日新高 / 新低（target=N 天，缺省 20）
    if rule_type in ("new_high", "new_low") and price is not None:
        n = int(target) if target and target >= 2 else 20
        closed = _closed_bars(code, n)
        if len(closed) >= max(2, n // 2):
            if rule_type == "new_high":
                highs = [float(b["high"]) for b in closed if b.get("high") is not None]
                if highs and price > max(highs):
                    return f"{name}({code}) 创 {n} 日新高 {price:.2f}（前高 {max(highs):.2f}）"
            else:
                lows = [float(b["low"]) for b in closed if b.get("low") is not None]
                if lows and price < min(lows):
                    return f"{name}({code}) 创 {n} 日新低 {price:.2f}（前低 {min(lows):.2f}）"

    # 均线上穿 / 下破（target=均线周期，如 5/10/20）
    if rule_type in ("ma_above", "ma_below") and price is not None:
        n = int(target) if target and target >= 2 else 20
        closed = _closed_bars(code, n)
        if len(closed) >= max(2, n - 1):
            closes = [float(b["close"]) for b in closed if b.get("close") is not None]
            if closes:
                ma = sum(closes) / len(closes)
                prev = _price_ago(code, _RAPID_WINDOW)   # 用 5min 前价判断"穿越"
                if rule_type == "ma_above" and price >= ma and (prev is None or prev < ma):
                    return f"{name}({code}) 上穿 MA{n} {ma:.2f}（现价 {price:.2f}）"
                if rule_type == "ma_below" and price <= ma and (prev is None or prev > ma):
                    return f"{name}({code}) 跌破 MA{n} {ma:.2f}（现价 {price:.2f}）"
    return None


async def check_rules_for_user(
    user_id: str, user_name: str = "",
    quote_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Check all enabled rules for a user.  Returns a summary + any new notifications.

    ``quote_map`` (code → quote) lets a caller pre-batch quotes (background
    poller); any code missing from it falls back to a per-code efinance fetch.
    """
    data = _load_alerts(user_id)
    rules = data.get("rules", [])
    if not rules:
        return {"checked": 0, "triggered": 0, "rules": []}

    # Cooldown guard: do not re-trigger within 10 minutes of the last trigger
    now = datetime.utcnow()
    triggered: List[Dict[str, Any]] = []

    for rule in rules:
        if not rule.get("enabled", True):
            continue

        last = rule.get("last_triggered_at")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if (now - last_dt).total_seconds() < 600:  # 10 min cooldown
                    continue
            except Exception:
                pass

        quote = (quote_map or {}).get(rule["code"]) or await _fetch_quote(rule["code"])
        if not quote:
            continue
        msg = _should_trigger(rule, quote)
        if not msg:
            continue

        # Record the event
        notif = {
            "id": str(uuid.uuid4()),
            "rule_id": rule["id"],
            "code": rule["code"],
            "name": rule.get("name", "") or rule["code"],
            "type": rule["type"],
            "target": rule["target"],
            "triggered_at": now.isoformat(timespec="seconds"),
            "price": quote.get("price"),
            "change_pct": quote.get("change_pct"),
            "message": msg,
            "read": False,
        }
        _append_notification(user_id, notif)
        rule["last_triggered_at"] = notif["triggered_at"]
        triggered.append(notif)

    # Persist updated `last_triggered_at` fields
    _save_alerts(user_id, data)

    # Push notifications to configured channels if any
    if triggered:
        try:
            from quantforge.notification.manager import (
                NotificationManager, load_settings,
            )
            cfg = load_settings()
            if cfg and cfg.get("channels"):
                mgr = NotificationManager.from_settings()
                lines = [f"{t['message']}" for t in triggered[:5]]
                body = "\n".join(lines)
                title = f"QuantForge: {len(triggered)} 条股票预警已触发"
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(mgr.notify(title=title, body=body))
                    else:
                        loop.run_until_complete(mgr.notify(title=title, body=body))
                except Exception:
                    pass
        except Exception:
            pass

    return {"checked": len(rules), "triggered": len(triggered), "events": triggered}


# ── Background polling (all users, market hours) ─────────────────────────────

def _list_alert_user_ids() -> List[str]:
    """User ids that have an alerts file on disk."""
    try:
        return [p.stem for p in _ALERTS_DIR.glob("*.json")]
    except Exception:
        return []


async def check_all_users() -> Dict[str, Any]:
    """Run the detection engine for every user with rules (batched quotes)."""
    users = 0
    triggered = 0
    for uid in _list_alert_user_ids():
        data = _load_alerts(uid)
        codes = {r["code"] for r in data.get("rules", []) if r.get("enabled", True)}
        if not codes:
            continue
        qmap = await _fetch_quotes_batch(codes)
        _record_prices(qmap)                 # 滚动价格历史(快速拉升/均线穿越用)
        res = await check_rules_for_user(uid, quote_map=qmap)
        users += 1
        triggered += res.get("triggered", 0)
    return {"users": users, "triggered": triggered}


def _in_market_hours() -> bool:
    """True during A-share continuous trading (Beijing time, Mon-Fri)."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=8)))
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    # 9:25 (集合竞价收尾) ~ 15:02，覆盖早/午盘，避开非交易时段空转
    return (9 * 60 + 25) <= hm <= (15 * 60 + 2)


async def alert_poll_loop(interval: int = 60) -> None:
    """Background scheduler: poll all users' alert rules during market hours."""
    import asyncio
    from loguru import logger

    logger.info("alert poll loop started (interval=%ss)" % interval)
    while True:
        try:
            if _in_market_hours():
                res = await check_all_users()
                if res.get("triggered"):
                    logger.info(f"alert poll: {res['triggered']} 条预警触发 "
                                f"(across {res['users']} 用户)")
        except Exception as exc:
            from loguru import logger as _lg
            _lg.debug(f"alert poll loop error: {exc}")
        await asyncio.sleep(interval)


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[AlertRule])
async def list_alerts(current_user: dict = Depends(get_current_user)):
    """Return the user's alert rules."""
    data = _load_alerts(current_user["id"])
    return data.get("rules", [])


@router.post("/", status_code=201)
async def create_alert(
    req: AlertCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a new alert rule for the current user."""
    valid_types = {
        "price_above", "price_below", "change_above", "change_below", "volume_spike",
        # 智能盯盘
        "rapid_rise", "rapid_fall", "limit_up", "limit_down", "vol_ratio_above",
        "new_high", "new_low", "ma_above", "ma_below",
    }
    if req.type not in valid_types:
        raise HTTPException(status_code=400, detail=f"无效的预警类型，支持: {', '.join(valid_types)}")

    code = req.code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="股票代码不能为空")

    data = _load_alerts(current_user["id"])
    rules = data.get("rules", [])

    # Prevent duplicate identical rules
    for r in rules:
        if r["code"] == code and r["type"] == req.type and float(r["target"]) == float(req.target):
            return {"status": "exists", "rule": r}

    rule = {
        "id": str(uuid.uuid4()),
        "code": code,
        "name": req.name or code,
        "type": req.type,
        "target": float(req.target),
        "enabled": True,
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
        "last_triggered_at": None,
        "notes": req.notes or "",
    }
    rules.append(rule)
    data["rules"] = rules
    _save_alerts(current_user["id"], data)
    return {"status": "created", "rule": rule, "count": len(rules)}


@router.delete("/{rule_id}")
async def delete_alert(
    rule_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete an alert rule by id."""
    data = _load_alerts(current_user["id"])
    rules = data.get("rules", [])
    new_rules = [r for r in rules if r["id"] != rule_id]
    if len(new_rules) == len(rules):
        raise HTTPException(status_code=404, detail="未找到该预警规则")
    data["rules"] = new_rules
    _save_alerts(current_user["id"], data)
    return {"status": "removed", "rule_id": rule_id, "count": len(new_rules)}


@router.put("/{rule_id}/enable")
async def toggle_alert(
    rule_id: str,
    enabled: bool = Query(True, description="Whether to enable or disable the rule"),
    current_user: dict = Depends(get_current_user),
):
    """Toggle an alert rule's enabled flag."""
    data = _load_alerts(current_user["id"])
    rules = data.get("rules", [])
    for r in rules:
        if r["id"] == rule_id:
            r["enabled"] = bool(enabled)
            _save_alerts(current_user["id"], data)
            return {"status": "updated", "rule_id": rule_id, "enabled": r["enabled"]}
    raise HTTPException(status_code=404, detail="未找到该预警规则")


@router.post("/check")
async def check_alerts(current_user: dict = Depends(get_current_user)):
    """Run the alert detection engine for this user's rules (批量行情，富字段可用)。"""
    data = _load_alerts(current_user["id"])
    codes = {r["code"] for r in data.get("rules", []) if r.get("enabled", True)}
    qmap = await _fetch_quotes_batch(codes) if codes else {}
    _record_prices(qmap)
    return await check_rules_for_user(
        current_user["id"], current_user.get("username", ""), quote_map=qmap or None
    )


@router.get("/notifications")
async def list_notifications(
    limit: int = Query(50, ge=1, le=500),
    unread_only: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    """Return the user's recent alert notifications (newest first)."""
    data = _load_notifications(current_user["id"])
    notifs = data.get("notifications", [])
    if unread_only:
        notifs = [n for n in notifs if not n.get("read", False)]
    return {"notifications": notifs[:limit], "count": len(notifs[:limit]), "unread": sum(1 for n in notifs[:limit] if not n.get("read", False))}


@router.post("/notifications/read")
async def mark_notifications_read(
    notification_ids: Optional[List[str]] = None,
    current_user: dict = Depends(get_current_user),
):
    """Mark one or more notifications as read.  Omitting `notification_ids` marks all as read."""
    data = _load_notifications(current_user["id"])
    notifs = data.get("notifications", [])
    if not notification_ids:
        for n in notifs:
            n["read"] = True
    else:
        ids = set(notification_ids)
        for n in notifs:
            if n.get("id") in ids:
                n["read"] = True
    data["notifications"] = notifs
    _save_notifications(current_user["id"], data)
    return {"status": "ok"}
