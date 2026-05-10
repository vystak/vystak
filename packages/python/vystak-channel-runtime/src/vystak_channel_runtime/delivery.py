"""ChannelDelivery interface — heartbeat-service-side push to channels.

The receiver-side scaffolding lives in `runtime.py` and dispatches
inbound HTTP/NATS payloads to the channel's `deliver_message` hook.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class DeliveryRequest(BaseModel):
    thread_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChannelDelivery(ABC):
    """Sender-side push to a channel runtime. Used by vystak-heartbeat."""

    @abstractmethod
    async def deliver(
        self,
        channel_canonical_name: str,
        request: DeliveryRequest,
        *,
        timeout: float = 30,
    ) -> None: ...
