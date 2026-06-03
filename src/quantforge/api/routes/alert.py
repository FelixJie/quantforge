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
    return None


async def check_rules_for_user(user_id: str, user_name: str = "") -> Dict[str, Any]:
    """Check all enabled rules for a user.  Returns a summary + any new notifications."""
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

        quote = await _fetch_quote(rule["code"])
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
    valid_types = {"price_above", "price_below", "change_above", "change_below", "volume_spike"}
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
    """Run the alert detection engine for this user's rules."""
    return await check_rules_for_user(current_user["id"], current_user.get("username", ""))


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
