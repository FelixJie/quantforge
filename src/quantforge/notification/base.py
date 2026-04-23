"""Base notification channel interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class NotifyResult:
    channel: str
    success: bool
    message: str = ""


class BaseNotifier(ABC):
    """Abstract base for all notification channels."""

    channel_name: str = ""

    @abstractmethod
    async def send(self, title: str, body: str) -> NotifyResult:
        """Send a notification. Returns NotifyResult."""
        ...

    def is_configured(self) -> bool:
        """Return True if this channel has required credentials."""
        return True
