"""飞书 (Feishu/Lark) Webhook notification channel.

Config:
  FEISHU_WEBHOOK_URL — Full webhook URL from Feishu group bot settings
"""

from __future__ import annotations

import os

import aiohttp
from loguru import logger

from quantforge.notification.base import BaseNotifier, NotifyResult


class FeishuNotifier(BaseNotifier):
    channel_name = "feishu"

    def __init__(self, webhook_url: str = ""):
        self.webhook_url = webhook_url or os.getenv("FEISHU_WEBHOOK_URL", "")

    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    async def send(self, title: str, body: str) -> NotifyResult:
        if not self.is_configured():
            return NotifyResult(self.channel_name, False, "Feishu webhook not configured")
        content = f"**{title}**\n{body}"
        payload = {
            "msg_type": "interactive",
            "card": {
                "elements": [
                    {
                        "tag": "div",
                        "text": {"content": content, "tag": "lark_md"},
                    }
                ],
                "header": {
                    "title": {"content": title, "tag": "plain_text"},
                    "template": "blue",
                },
            },
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    if data.get("code") == 0 or data.get("StatusCode") == 0:
                        return NotifyResult(self.channel_name, True)
                    err = str(data)
                    logger.warning(f"Feishu notify failed: {err}")
                    return NotifyResult(self.channel_name, False, err[:200])
        except Exception as e:
            logger.warning(f"Feishu notify error: {e}")
            return NotifyResult(self.channel_name, False, str(e))
