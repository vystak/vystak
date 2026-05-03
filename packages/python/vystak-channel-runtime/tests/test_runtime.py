"""Tests for ChannelRuntime base class."""

import pytest
from vystak.schema.common import ChannelType
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.types import (
    AgentReply,
    InboundEvent,
    SkipEvent,
)


class TrivialRuntime(ChannelRuntime):
    """Minimal ChannelRuntime subclass for unit tests."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.posted: list[tuple[InboundEvent, str, AgentReply]] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def parse_event(self, raw):
        if raw.get("skip"):
            raise SkipEvent("skip")
        return InboundEvent(
            channel_type=ChannelType.SLACK,
            scope_id=raw["scope_id"],
            thread_id=raw.get("thread_id"),
            user_id=raw["user_id"],
            text=raw["text"],
            is_dm=raw.get("is_dm", False),
            mentions_bot=raw.get("mentions_bot", True),
            metadata={},
            raw=raw,
        )

    async def post_reply(self, event, route, reply):
        self.posted.append((event, route, reply))


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


def _routes():
    return {"hero": {"canonical": "hero.agents.default", "address": "http://hero:8000"}}


@pytest.mark.asyncio
async def test_authorize_blocks_bots_when_allow_bots_false():
    rt = TrivialRuntime(
        config=_config(allow_bots=False),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="T1", thread_id=None,
        user_id="U_BOT", text="hi", is_dm=False, mentions_bot=True,
        metadata={"is_bot": True},
    )
    assert await rt.authorize(ev) is False


@pytest.mark.asyncio
async def test_authorize_allows_when_allow_bots_true():
    rt = TrivialRuntime(
        config=_config(allow_bots=True),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="T1", thread_id=None,
        user_id="U_BOT", text="hi", is_dm=False, mentions_bot=True,
        metadata={"is_bot": True},
    )
    assert await rt.authorize(ev) is True


@pytest.mark.asyncio
async def test_authorize_dm_disabled():
    rt = TrivialRuntime(
        config=_config(dm_policy="disabled"),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="T1", thread_id=None,
        user_id="U", text="hi", is_dm=True, mentions_bot=False,
    )
    assert await rt.authorize(ev) is False


@pytest.mark.asyncio
async def test_authorize_allowlist_blocks_unknown_user():
    rt = TrivialRuntime(
        config=_config(group_policy="allowlist", allow_from=["U_OK"]),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="T1", thread_id=None,
        user_id="U_NOPE", text="hi", is_dm=False, mentions_bot=True,
    )
    assert await rt.authorize(ev) is False


@pytest.mark.asyncio
async def test_authorize_allowlist_admits_known_user():
    rt = TrivialRuntime(
        config=_config(group_policy="allowlist", allow_from=["U_OK"]),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="T1", thread_id=None,
        user_id="U_OK", text="hi", is_dm=False, mentions_bot=True,
    )
    assert await rt.authorize(ev) is True
