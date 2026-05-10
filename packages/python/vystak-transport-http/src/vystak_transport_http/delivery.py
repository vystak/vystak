"""HttpChannelDelivery — POST /deliver to the channel's HTTP delivery port."""

from __future__ import annotations

import httpx
from vystak_channel_runtime.delivery import ChannelDelivery, DeliveryRequest


class HttpChannelDelivery(ChannelDelivery):
    def __init__(self, channel_routes: dict[str, str]) -> None:
        # canonical_name → base URL like http://host:9999
        self._routes = dict(channel_routes)

    async def deliver(
        self,
        channel_canonical_name: str,
        request: DeliveryRequest,
        *,
        timeout: float = 30,
    ) -> None:
        url = self._routes[channel_canonical_name].rstrip("/") + "/deliver"
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(url, json=request.model_dump(mode="json"))
            r.raise_for_status()
