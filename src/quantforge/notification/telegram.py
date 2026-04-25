"""Telegram Bot notification channel.

Config (env vars or notification settings):
  TELEGRAM_BOT_TOKEN — Bot API token from @BotFather
  TELEGRAM_CHAT_ID   — Target chat/channel ID
"""

from __future__ import annotations

import os

import aiohttp
from loguru import logger

from quantforge.notification.base import BaseNotifier, NotifyResult


class TelegramNotifier(BaseNotifier):
    channel_name = "telegram"

    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id   = chat_id   or os.getenv("TELEGRAM_CHAT_ID", "")

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send(self, title: str, body: str) -> NotifyResult:
        if not self.is_configured():
            return NotifyResult(self.channel_name, False, "Telegram not configured")
        text = f"*{title}*\n\n{body}"
        url  = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={
                    "chat_id":    self.chat_id,
                    "text":       text,
                    "parse_mode": "Markdown",
                }, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return NotifyResult(self.channel_name, True)
                    err = await resp.text()
                    logger.warning(f"Telegram notify failed ({resp.status}): {err}")
                    return NotifyResult(self.channel_name, False, err[:200])
        except Exception as e:
            logger.warning(f"Telegram notify error: {e}")
            return NotifyResult(self.channel_name, False, str(e))
