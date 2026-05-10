"""Tests for ChannelRuntime._on_inbound_delivery."""

import pytest
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.types import SkipEvent


class _Receiver(ChannelRuntime):
    """Minimal ChannelRuntime subclass for delivery-receiver tests."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.delivered: list[tuple[str, str, dict]] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def parse_event(self, raw):
        raise SkipEvent("not used in delivery tests")

    async def post_reply(self, event, route, reply):
        pass

    async def deliver_message(self, thread_id: str, text: str, metadata: dict) -> None:
        self.delivered.append((thread_id, text, metadata))


def _config(**overrides):
    base = {
        "channel_type": "slack",
        "agent_protocol": "a2a-turn",
        "agents": ["hero"],
        "default_agent": "hero",
        "group_policy": "open",
        "dm_policy": "open",
        "allow_from": [],
        "allow_bots": False,
        "channel_overrides": {},
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_valid_body_dispatches_to_deliver_message():
    """A well-formed body is validated and forwarded to deliver_message."""
    rt = _Receiver(
        config=_config(),
        routes={},
        store=MemoryChannelStore(),
    )
    body = {"thread_id": "C123", "text": "hello", "metadata": {"k": "v"}}
    await rt._on_inbound_delivery(body)
    assert rt.delivered == [("C123", "hello", {"k": "v"})]


@pytest.mark.asyncio
async def test_invalid_body_drops_silently():
    """A body missing required fields is logged and dropped — no exception."""
    rt = _Receiver(
        config=_config(),
        routes={},
        store=MemoryChannelStore(),
    )
    # Missing required 'text' field — DeliveryRequest.model_validate should fail.
    body = {"thread_id": "C123"}
    await rt._on_inbound_delivery(body)
    assert rt.delivered == []


@pytest.mark.asyncio
async def test_subclass_exception_is_swallowed():
    """Exceptions raised by deliver_message are caught — the call must not raise."""

    class _BrokenReceiver(_Receiver):
        async def deliver_message(self, thread_id, text, metadata):
            raise RuntimeError("intentional failure")

    rt = _BrokenReceiver(
        config=_config(),
        routes={},
        store=MemoryChannelStore(),
    )
    body = {"thread_id": "C123", "text": "hello"}
    # Must not propagate the RuntimeError.
    await rt._on_inbound_delivery(body)
