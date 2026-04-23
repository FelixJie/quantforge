"""Notification settings and test endpoints.

Endpoints:
  GET  /api/notification/settings   → get current settings
  PUT  /api/notification/settings   → update settings
  POST /api/notification/test       → send a test notification to all configured channels
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any

from quantforge.notification.manager import load_settings, save_settings, NotificationManager

router = APIRouter(prefix="/notification", tags=["notification"])


class SettingsUpdate(BaseModel):
    settings: dict[str, Any]


@router.get("/settings")
async def get_settings():
    """Get current notification settings (passwords masked)."""
    cfg = load_settings()
    # Mask sensitive fields
    masked = dict(cfg)
    ch = dict(masked.get("channels", {}))
    if "email" in ch:
        em = dict(ch["email"])
        if em.get("smtp_password"):
            em["smtp_password"] = "••••••••"
        ch["email"] = em
    masked["channels"] = ch
    return masked


@router.put("/settings")
async def update_settings(req: SettingsUpdate):
    """Update notification settings.

    Note: omitting smtp_password keeps the existing password.
    """
    existing = load_settings()
    new_cfg = req.settings

    # Preserve existing password if not provided in update
    existing_pw = existing.get("channels", {}).get("email", {}).get("smtp_password", "")
    new_email_pw = new_cfg.get("channels", {}).get("email", {}).get("smtp_password", "")
    if new_email_pw in ("", "••••••••") and existing_pw:
        if "channels" in new_cfg and "email" in new_cfg["channels"]:
            new_cfg["channels"]["email"]["smtp_password"] = existing_pw

    save_settings(new_cfg)
    return {"status": "ok", "message": "通知设置已保存"}


@router.post("/test")
async def test_notification():
    """Send a test notification to all configured channels."""
    mgr = NotificationManager.from_settings()
    if not mgr._notifiers:
        return {"status": "skipped", "message": "没有已启用的通知渠道，请先配置"}

    results = await mgr.notify(
        title="QuantForge 测试通知",
        body="这是一条测试消息，说明你的通知渠道配置正确。\n\n来自 QuantForge 量化交易系统",
    )
    return {
        "status": "done",
        "results": [
            {"channel": r.channel, "success": r.success, "message": r.message}
            for r in results
        ],
    }
