"""HttpChannelDelivery test."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from vystak_channel_runtime.delivery import DeliveryRequest
from vystak_transport_http.delivery import HttpChannelDelivery


@pytest.mark.asyncio
async def test_post_to_channel_url():
    routes = {"x.channels.dev": "http://vystak-channel-x:9999"}
    d = HttpChannelDelivery(routes)
    with patch("vystak_transport_http.delivery.httpx.AsyncClient") as ac:
        client = AsyncMock()
        ac.return_value.__aenter__.return_value = client
        response = MagicMock()
        response.raise_for_status = MagicMock()
        client.post = AsyncMock(return_value=response)
        await d.deliver("x.channels.dev", DeliveryRequest(thread_id="t", text="x"))
        client.post.assert_awaited_once()
        url = client.post.call_args.args[0]
        assert url == "http://vystak-channel-x:9999/deliver"


@pytest.mark.asyncio
async def test_unknown_channel_raises():
    d = HttpChannelDelivery({})
    with pytest.raises(KeyError):
        await d.deliver("ghost.channels.dev", DeliveryRequest(thread_id="t", text="x"))
