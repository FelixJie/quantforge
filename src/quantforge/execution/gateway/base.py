"""Abstract Gateway interface — broker/exchange connection."""

from abc import ABC, abstractmethod

from quantforge.core.datatypes import AccountData, OrderData, PositionData


class Gateway(ABC):
    """Abstract broker/exchange gateway."""

    name: str = ""

    @abstractmethod
    async def send_order(self, order: OrderData) -> str:
        """Send order to broker. Returns broker-assigned order ID."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> None:
        """Cancel an order."""
        ...
