"""Tests for ChannelRuntime base class."""

import pytest
from vystak.schema.common import ChannelType
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.types import (
    AgentCallError,
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

    async def deliver_message(self, *args, **kwargs):
        pass


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


@pytest.mark.asyncio
async def test_authorize_respects_require_mention():
    rt = TrivialRuntime(
        config=_config(require_mention=True),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="T1", thread_id=None,
        user_id="U", text="hi", is_dm=False, mentions_bot=False,
    )
    assert await rt.authorize(ev) is False


@pytest.mark.asyncio
async def test_authorize_admits_mention_when_require_mention():
    rt = TrivialRuntime(
        config=_config(require_mention=True),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="T1", thread_id=None,
        user_id="U", text="hi", is_dm=False, mentions_bot=True,
    )
    assert await rt.authorize(ev) is True


@pytest.mark.asyncio
async def test_authorize_admits_dm_without_mention_when_require_mention():
    rt = TrivialRuntime(
        config=_config(require_mention=True),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="U", thread_id=None,
        user_id="U", text="hi", is_dm=True, mentions_bot=False,
    )
    assert await rt.authorize(ev) is True


@pytest.mark.asyncio
async def test_resolve_route_uses_channel_override():
    rt = TrivialRuntime(
        config=_config(channel_overrides={"C1": {"agent": "villain"}}),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="C1", thread_id=None,
        user_id="U", text="hi", is_dm=False, mentions_bot=True,
    )
    assert await rt.resolve_route(ev) == "villain"


@pytest.mark.asyncio
async def test_resolve_route_uses_thread_binding_when_no_override():
    store = MemoryChannelStore()
    await store.set_thread_binding("slack", "C1", "T:1.0", "villain")
    rt = TrivialRuntime(
        config=_config(),
        routes=_routes(),
        store=store,
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="C1", thread_id="T:1.0",
        user_id="U", text="hi", is_dm=False, mentions_bot=True,
    )
    assert await rt.resolve_route(ev) == "villain"


@pytest.mark.asyncio
async def test_resolve_route_uses_route_pref_for_dm():
    store = MemoryChannelStore()
    await store.set_route_pref("slack", "U", "villain")
    rt = TrivialRuntime(
        config=_config(),
        routes=_routes(),
        store=store,
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="U", thread_id=None,
        user_id="U", text="hi", is_dm=True, mentions_bot=False,
    )
    assert await rt.resolve_route(ev) == "villain"


@pytest.mark.asyncio
async def test_resolve_route_falls_back_to_default_agent():
    rt = TrivialRuntime(
        config=_config(default_agent="hero"),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="C1", thread_id=None,
        user_id="U", text="hi", is_dm=False, mentions_bot=True,
    )
    assert await rt.resolve_route(ev) == "hero"


@pytest.mark.asyncio
async def test_resolve_route_returns_none_when_no_default():
    rt = TrivialRuntime(
        config=_config(default_agent=None),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="C1", thread_id=None,
        user_id="U", text="hi", is_dm=False, mentions_bot=True,
    )
    assert await rt.resolve_route(ev) is None


# ---------------------------------------------------------------------------
# Task 1.10 — call_agent + handle_event pipeline
# ---------------------------------------------------------------------------


class FakeAgentClient:
    def __init__(self):
        self.calls = []

    async def send_turn(self, agent_url, text, thread_id, history=None, metadata=None):
        self.calls.append({"url": agent_url, "text": text, "thread_id": thread_id})
        return AgentReply(text=f"reply to: {text}")

    async def stream_turn(self, *args, **kwargs):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_handle_event_full_pipeline_happy_path():
    fc = FakeAgentClient()
    store = MemoryChannelStore()
    rt = TrivialRuntime(
        config=_config(),
        routes=_routes(),
        store=store,
        agent_client=fc,
    )
    await rt.handle_event({"scope_id": "C1", "thread_id": "T:1", "user_id": "U", "text": "hi"})
    assert len(rt.posted) == 1
    ev, route, reply = rt.posted[0]
    assert route == "hero"
    assert reply.text == "reply to: hi"
    assert fc.calls[0]["url"] == "http://hero:8000"
    # thread binding persisted in after_reply
    assert await store.get_thread_binding("slack", "C1", "T:1") == "hero"


@pytest.mark.asyncio
async def test_handle_event_skips_when_parse_event_raises_skip():
    rt = TrivialRuntime(
        config=_config(),
        routes=_routes(),
        store=MemoryChannelStore(),
        agent_client=FakeAgentClient(),
    )
    await rt.handle_event({"skip": True})
    assert rt.posted == []


@pytest.mark.asyncio
async def test_handle_event_drops_when_authorize_false():
    rt = TrivialRuntime(
        config=_config(group_policy="disabled"),
        routes=_routes(),
        store=MemoryChannelStore(),
        agent_client=FakeAgentClient(),
    )
    await rt.handle_event({"scope_id": "C1", "user_id": "U", "text": "hi"})
    assert rt.posted == []


@pytest.mark.asyncio
async def test_handle_event_no_route_calls_on_no_route():
    fc = FakeAgentClient()

    class NoRouteRuntime(TrivialRuntime):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.no_route_count = 0

        async def on_no_route(self, event):
            self.no_route_count += 1

    rt = NoRouteRuntime(
        config=_config(default_agent=None),
        routes=_routes(),
        store=MemoryChannelStore(),
        agent_client=fc,
    )
    await rt.handle_event({"scope_id": "C1", "user_id": "U", "text": "hi"})
    assert rt.no_route_count == 1
    assert rt.posted == []


@pytest.mark.asyncio
async def test_handle_event_agent_error_routes_to_handler():
    class FailingClient:
        async def send_turn(self, *a, **kw):
            raise AgentCallError("boom")

        async def stream_turn(self, *a, **kw):
            raise NotImplementedError

    class CapturingRuntime(TrivialRuntime):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.errors = []

        async def on_agent_error(self, event, route, exc):
            self.errors.append((route, str(exc)))

    rt = CapturingRuntime(
        config=_config(),
        routes=_routes(),
        store=MemoryChannelStore(),
        agent_client=FailingClient(),
    )
    await rt.handle_event({"scope_id": "C1", "user_id": "U", "text": "hi"})
    assert rt.errors == [("hero", "boom")]
    assert rt.posted == []


class _SlackishRuntime(TrivialRuntime):
    """Test helper that exposes a per-channel-scope binding fallback."""

    async def channel_binding_thread_id(self, event):
        chan = event.metadata.get("channel_id")
        return f"{chan}:" if chan else None


@pytest.mark.asyncio
async def test_resolve_route_falls_back_to_channel_binding():
    """When per-thread binding misses, look up the per-channel binding via the subclass hook."""
    store = MemoryChannelStore()
    await store.set_thread_binding("slack", "T1", "C1:", "channel-pinned")
    rt = _SlackishRuntime(
        config=_config(default_agent=None),
        routes=_routes(),
        store=store,
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="T1", thread_id="C1:1700.123",
        user_id="U", text="hi", is_dm=False, mentions_bot=True,
        metadata={"channel_id": "C1"},
    )
    assert await rt.resolve_route(ev) == "channel-pinned"


@pytest.mark.asyncio
async def test_resolve_route_thread_binding_takes_precedence_over_channel_binding():
    store = MemoryChannelStore()
    await store.set_thread_binding("slack", "T1", "C1:", "channel-pinned")
    await store.set_thread_binding("slack", "T1", "C1:1700.123", "thread-pinned")
    rt = _SlackishRuntime(
        config=_config(default_agent=None),
        routes=_routes(),
        store=store,
    )
    ev = InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="T1", thread_id="C1:1700.123",
        user_id="U", text="hi", is_dm=False, mentions_bot=True,
        metadata={"channel_id": "C1"},
    )
    assert await rt.resolve_route(ev) == "thread-pinned"


# ---------------------------------------------------------------------------
# _default_agent_client — transport-aware selection
# ---------------------------------------------------------------------------


def test_default_agent_client_http_when_transport_unset(monkeypatch):
    """No VYSTAK_TRANSPORT_TYPE → HTTP client (back-compat default)."""
    from vystak_channel_runtime.agent_client import A2AAgentClient

    monkeypatch.delenv("VYSTAK_TRANSPORT_TYPE", raising=False)
    monkeypatch.delenv("VYSTAK_NATS_URL", raising=False)
    rt = TrivialRuntime(
        config=_config(),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    assert isinstance(rt._agent_client, A2AAgentClient)


def test_default_agent_client_http_when_transport_http(monkeypatch):
    from vystak_channel_runtime.agent_client import A2AAgentClient

    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "http")
    rt = TrivialRuntime(
        config=_config(),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    assert isinstance(rt._agent_client, A2AAgentClient)


def test_default_agent_client_nats_when_transport_nats(monkeypatch):
    """VYSTAK_TRANSPORT_TYPE=nats + VYSTAK_NATS_URL → NatsAgentClient."""
    from vystak_channel_runtime.agent_client import NatsAgentClient

    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "nats")
    monkeypatch.setenv("VYSTAK_NATS_URL", "nats://vystak-nats:4222")
    rt = TrivialRuntime(
        config=_config(),
        routes=_routes(),
        store=MemoryChannelStore(),
    )
    assert isinstance(rt._agent_client, NatsAgentClient)


def test_default_agent_client_nats_without_url_raises(monkeypatch):
    """Misconfiguration: NATS transport declared but no broker URL provided."""
    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "nats")
    monkeypatch.delenv("VYSTAK_NATS_URL", raising=False)
    with pytest.raises(RuntimeError, match="VYSTAK_NATS_URL"):
        TrivialRuntime(
            config=_config(),
            routes=_routes(),
            store=MemoryChannelStore(),
        )


