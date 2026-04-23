"""NotificationManager — orchestrates multi-channel push notifications.

Usage:
    mgr = NotificationManager.from_settings()
    results = await mgr.notify("今日AI选股", "推荐：宁德时代(300750)...")

Settings are loaded from data/cache/notification_settings.json (persisted via API)
and can be overridden by environment variables.
"""

from __future__ import annotations

import asyncio
import json
import datetime as _dt
from pathlib import Path
from typing import Any

from loguru import logger

from quantforge.notification.base import BaseNotifier, NotifyResult
from quantforge.notification.email_sender import EmailNotifier
from quantforge.notification.feishu import FeishuNotifier
from quantforge.notification.telegram import TelegramNotifier
from quantforge.notification.wecom import WeComNotifier

_SETTINGS_FILE = Path("data/cache/notification_settings.json")

_DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "channels": {
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        "wecom":    {"enabled": False, "webhook_url": ""},
        "feishu":   {"enabled": False, "webhook_url": ""},
        "email":    {
            "enabled": False,
            "smtp_host": "", "smtp_port": 587,
            "smtp_user": "", "smtp_password": "", "to_addrs": "",
        },
    },
    "events": {
        "ai_picks":    True,
        "risk_alert":  True,
        "trade":       False,
    },
}


def load_settings() -> dict:
    if _SETTINGS_FILE.exists():
        try:
            saved = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            # Deep merge with defaults so new fields are always present
            merged = {**_DEFAULT_SETTINGS, **saved}
            merged["channels"] = {**_DEFAULT_SETTINGS["channels"], **saved.get("channels", {})}
            merged["events"]   = {**_DEFAULT_SETTINGS["events"],   **saved.get("events", {})}
            return merged
        except Exception:
            pass
    return dict(_DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    try:
        _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_FILE.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"notification settings save failed: {e}")


class NotificationManager:
    """Build and dispatch notifications across all configured channels."""

    def __init__(self, notifiers: list[BaseNotifier]):
        self._notifiers = notifiers

    @classmethod
    def from_settings(cls) -> "NotificationManager":
        """Construct from persisted settings file."""
        cfg = load_settings()
        if not cfg.get("enabled"):
            return cls([])

        notifiers: list[BaseNotifier] = []
        ch = cfg.get("channels", {})

        tg = ch.get("telegram", {})
        if tg.get("enabled"):
            notifiers.append(TelegramNotifier(
                bot_token=tg.get("bot_token", ""),
                chat_id=tg.get("chat_id", ""),
            ))

        wc = ch.get("wecom", {})
        if wc.get("enabled"):
            notifiers.append(WeComNotifier(webhook_url=wc.get("webhook_url", "")))

        fs = ch.get("feishu", {})
        if fs.get("enabled"):
            notifiers.append(FeishuNotifier(webhook_url=fs.get("webhook_url", "")))

        em = ch.get("email", {})
        if em.get("enabled"):
            notifiers.append(EmailNotifier(
                smtp_host=em.get("smtp_host", ""),
                smtp_port=int(em.get("smtp_port", 587)),
                smtp_user=em.get("smtp_user", ""),
                smtp_password=em.get("smtp_password", ""),
                to_addrs=em.get("to_addrs", ""),
            ))

        return cls(notifiers)

    async def notify(self, title: str, body: str) -> list[NotifyResult]:
        """Send to all configured channels concurrently."""
        if not self._notifiers:
            return []
        tasks = [n.send(title, body) for n in self._notifiers if n.is_configured()]
        if not tasks:
            return []
        results: list[NotifyResult] = await asyncio.gather(*tasks, return_exceptions=False)
        for r in results:
            if r.success:
                logger.info(f"notify [{r.channel}] OK")
            else:
                logger.warning(f"notify [{r.channel}] FAILED: {r.message}")
        return results

    @staticmethod
    def format_ai_picks(payload: dict) -> tuple[str, str]:
        """Format AI picks payload into notification title + body."""
        date      = payload.get("date", _dt.date.today().isoformat())
        summary   = payload.get("market_summary", "")
        strategy  = payload.get("operation_strategy", "")
        picks     = payload.get("picks", [])

        title = f"📈 QuantForge AI选股 {date}"
        lines = []
        if summary:
            lines.append(f"市场概况：{summary}")
        if strategy:
            lines.append(f"操作策略：{strategy}")
        lines.append("")

        for p in picks[:10]:
            rank   = p.get("rank", "")
            code   = p.get("code", "")
            name   = p.get("name", "")
            buy    = p.get("buy_price")
            stop   = p.get("stop_price")
            target = p.get("target_price")
            conf   = p.get("confidence", "")
            risk   = p.get("risk_level", "")
            reason = p.get("reason", "")

            line = f"{rank}. {name}({code})"
            if buy:
                line += f"  买入:{buy}"
            if stop:
                line += f"  止损:{stop}"
            if target:
                line += f"  目标:{target}"
            if conf:
                line += f"  置信:{conf}%"
            if risk:
                line += f"  风险:{risk}"
            lines.append(line)
            if reason:
                lines.append(f"   {reason}")

        return title, "\n".join(lines)

    @staticmethod
    def format_risk_alert(symbol: str, rule: str, message: str) -> tuple[str, str]:
        title = f"⚠️ 风险告警 {symbol}"
        body  = f"规则：{rule}\n详情：{message}\n时间：{_dt.datetime.now().strftime('%H:%M:%S')}"
        return title, body
