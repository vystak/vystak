"""NatsChannelDelivery test."""

from unittest.mock import AsyncMock

import pytest
from vystak_channel_runtime.delivery import DeliveryRequest
from vystak_transport_nats.delivery import NatsChannelDelivery


@pytest.mark.asyncio
async def test_publish_to_canonical_subject(monkeypatch):
    nc = AsyncMock()
    nc.publish = AsyncMock()
    d = NatsChannelDelivery("nats://x:4222")
    monkeypatch.setattr(d, "_connect", AsyncMock(return_value=nc))
    await d.deliver("x.channels.dev", DeliveryRequest(thread_id="t", text="x"))
    args, _ = nc.publish.call_args
    assert args[0] == "vystak.channel.x.channels.dev.deliver"
