"""Email (SMTP) notification channel.

Config (env vars):
  EMAIL_SMTP_HOST     — SMTP server host (e.g. smtp.gmail.com)
  EMAIL_SMTP_PORT     — SMTP port (default 587)
  EMAIL_SMTP_USER     — Sender email address
  EMAIL_SMTP_PASSWORD — SMTP password or app password
  EMAIL_TO            — Recipient address(es), comma-separated
"""

from __future__ import annotations

import asyncio
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from loguru import logger

from quantforge.notification.base import BaseNotifier, NotifyResult


class EmailNotifier(BaseNotifier):
    channel_name = "email"

    def __init__(
        self,
        smtp_host: str = "",
        smtp_port: int = 0,
        smtp_user: str = "",
        smtp_password: str = "",
        to_addrs: str = "",
    ):
        self.smtp_host     = smtp_host     or os.getenv("EMAIL_SMTP_HOST", "")
        self.smtp_port     = smtp_port     or int(os.getenv("EMAIL_SMTP_PORT", "587"))
        self.smtp_user     = smtp_user     or os.getenv("EMAIL_SMTP_USER", "")
        self.smtp_password = smtp_password or os.getenv("EMAIL_SMTP_PASSWORD", "")
        self.to_addrs      = to_addrs      or os.getenv("EMAIL_TO", "")

    def is_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password and self.to_addrs)

    def _send_sync(self, title: str, body: str) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = title
        msg["From"]    = self.smtp_user
        msg["To"]      = self.to_addrs

        # Plain text part
        msg.attach(MIMEText(body, "plain", "utf-8"))
        # HTML part (simple formatting)
        html_body = body.replace("\n", "<br>")
        html = f"<html><body><h2>{title}</h2><p>{html_body}</p></body></html>"
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.sendmail(self.smtp_user, self.to_addrs.split(","), msg.as_string())

    async def send(self, title: str, body: str) -> NotifyResult:
        if not self.is_configured():
            return NotifyResult(self.channel_name, False, "Email not configured")
        try:
            await asyncio.to_thread(self._send_sync, title, body)
            return NotifyResult(self.channel_name, True)
        except Exception as e:
            logger.warning(f"Email notify error: {e}")
            return NotifyResult(self.channel_name, False, str(e))
