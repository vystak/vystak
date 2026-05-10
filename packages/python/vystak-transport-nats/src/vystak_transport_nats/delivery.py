"""NatsChannelDelivery — publish to vystak.channel.<canonical>.deliver."""

from __future__ import annotations

import nats
from nats.aio.client import Client as NATSClient
from vystak_channel_runtime.delivery import ChannelDelivery, DeliveryRequest


class NatsChannelDelivery(ChannelDelivery):
    SUBJECT_FMT = "vystak.channel.{canonical_name}.deliver"

    def __init__(self, url: str) -> None:
        self._url = url
        self._nc: NATSClient | None = None

    async def _connect(self) -> NATSClient:
        if self._nc is None:
            self._nc = await nats.connect(self._url)
        return self._nc

    async def deliver(
        self,
        channel_canonical_name: str,
        request: DeliveryRequest,
        *,
        timeout: float = 30,
    ) -> None:
        nc = await self._connect()
        await nc.publish(
            self.SUBJECT_FMT.format(canonical_name=channel_canonical_name),
            request.model_dump_json().encode(),
        )
