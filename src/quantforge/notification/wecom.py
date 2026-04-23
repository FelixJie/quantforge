"""企业微信 (WeCom/WeChat Work) Webhook notification channel.

Config:
  WECOM_WEBHOOK_URL — Full webhook URL from WeCom group bot settings
"""

from __future__ import annotations

import os

import aiohttp
from loguru import logger

from quantforge.notification.base import BaseNotifier, NotifyResult


class WeComNotifier(BaseNotifier):
    channel_name = "wecom"

    def __init__(self, webhook_url: str = ""):
        self.webhook_url = webhook_url or os.getenv("WECOM_WEBHOOK_URL", "")

    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    async def send(self, title: str, body: str) -> NotifyResult:
        if not self.is_configured():
            return NotifyResult(self.channel_name, False, "WeCom webhook not configured")
        content = f"**{title}**\n{body}"
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    if data.get("errcode") == 0:
                        return NotifyResult(self.channel_name, True)
                    err = str(data)
                    logger.warning(f"WeCom notify failed: {err}")
                    return NotifyResult(self.channel_name, False, err[:200])
        except Exception as e:
            logger.warning(f"WeCom notify error: {e}")
            return NotifyResult(self.channel_name, False, str(e))
