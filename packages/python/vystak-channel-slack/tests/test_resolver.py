"""Slack routing tests — now exercised via ChannelRuntime.resolve_route()."""

import pytest
from vystak.schema.common import ChannelType
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.types import InboundEvent


class _TrivSlack(ChannelRuntime):
    async def start(self): pass
    async def stop(self): pass
    def parse_event(self, raw): raise NotImplementedError
    async def post_reply(self, e, r, reply): pass


def _ev(scope_id="T1", thread_id=None, user_id="U", is_dm=False):
    return InboundEvent(
        channel_type=ChannelType.SLACK, scope_id=scope_id, thread_id=thread_id,
        user_id=user_id, text="hi", is_dm=is_dm, mentions_bot=True,
    )


def _cfg(**overrides):
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
async def test_resolve_uses_channel_override():
    rt = _TrivSlack(
        config=_cfg(channel_overrides={"T1": {"agent": "villain"}}),
        routes={}, store=MemoryChannelStore(),
    )
    assert await rt.resolve_route(_ev()) == "villain"


@pytest.mark.asyncio
async def test_resolve_falls_back_to_default():
    rt = _TrivSlack(
        config=_cfg(),
        routes={}, store=MemoryChannelStore(),
    )
    assert await rt.resolve_route(_ev()) == "hero"
