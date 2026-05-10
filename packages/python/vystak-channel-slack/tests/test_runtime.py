"""Tests for SlackChannelRuntime."""

import pytest
from vystak.schema.common import ChannelType
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.types import AgentReply, SkipEvent
from vystak_channel_slack.runtime import SlackChannelRuntime


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


def test_runtime_constructable():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    assert rt.channel_type == "slack"


def _bolt_event(text="hi <@U_BOT>", channel_type="channel", thread_ts=None, bot_id=None):
    return {
        "type": "message",
        "channel": "C1",
        "user": "U_USER",
        "text": text,
        "ts": "1.0",
        "team": "T1",
        "channel_type": channel_type,
        **({"thread_ts": thread_ts} if thread_ts else {}),
        **({"bot_id": bot_id} if bot_id else {}),
    }


def test_parse_event_app_mention():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "app_mention", "event": _bolt_event(), "say": None}
    ev = rt.parse_event(raw)
    assert ev.channel_type == ChannelType.SLACK
    assert ev.scope_id == "T1"
    assert ev.thread_id == "C1:1.0"
    assert ev.user_id == "U_USER"
    assert ev.is_dm is False
    assert ev.mentions_bot is True


def test_parse_event_dm():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": _bolt_event(text="hello", channel_type="im"), "say": None}
    ev = rt.parse_event(raw)
    assert ev.is_dm is True
    assert ev.mentions_bot is False


def test_parse_event_thread_reply_keeps_root_thread_id():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": _bolt_event(text="hello", thread_ts="1.0"), "say": None}
    ev = rt.parse_event(raw)
    assert ev.thread_id == "C1:1.0"


def test_parse_event_bot_marked_in_metadata():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": _bolt_event(text="hello", bot_id="B1"), "say": None}
    ev = rt.parse_event(raw)
    assert ev.metadata.get("is_bot") is True


def test_parse_event_skips_own_message():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": {**_bolt_event(), "user": "U_BOT"}, "say": None}
    with pytest.raises(SkipEvent):
        rt.parse_event(raw)


class _FakeSay:
    def __init__(self):
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)


@pytest.mark.asyncio
async def test_post_reply_uses_say_with_thread_ts():
    say = _FakeSay()
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "app_mention", "event": _bolt_event(thread_ts="1.0"), "say": say}
    ev = rt.parse_event(raw)
    await rt.post_reply(ev, "hero", AgentReply(text="hello back"))
    assert len(say.calls) == 1
    assert say.calls[0]["text"] == "hello back"
    assert say.calls[0]["thread_ts"] == "1.0"


@pytest.mark.asyncio
async def test_fetch_history_returns_empty_when_no_thread_ts(monkeypatch):
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": _bolt_event(channel_type="im"), "say": None}
    ev = rt.parse_event(raw)
    history = await rt.fetch_history(ev)
    assert history == []


def test_parse_event_skips_message_with_subtype():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": {**_bolt_event(), "subtype": "bot_message"}, "say": None}
    with pytest.raises(SkipEvent):
        rt.parse_event(raw)


def test_parse_event_skips_message_event_when_text_contains_bot_mention():
    """Slack fires both message AND app_mention for the same user @-mention.
    The message-side should drop to avoid double-replies."""
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": _bolt_event(text="hi <@U_BOT>"), "say": None}
    with pytest.raises(SkipEvent):
        rt.parse_event(raw)


@pytest.mark.asyncio
async def test_parse_event_message_without_mention_passes_parse_but_authorize_drops():
    """Plain message in a guild channel parses successfully, but authorize
    drops it when require_mention=True."""
    rt = SlackChannelRuntime(
        config=_config(require_mention=True),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": _bolt_event(text="hello world"), "say": None}
    ev = rt.parse_event(raw)
    assert ev.mentions_bot is False
    assert await rt.authorize(ev) is False


def test_parse_event_dm_scope_id_includes_user():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": _bolt_event(text="hello", channel_type="im"), "say": None}
    ev = rt.parse_event(raw)
    assert ev.is_dm is True
    assert ev.scope_id == "T1:U_USER"


def test_parse_event_guild_scope_id_is_team_only():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "app_mention", "event": _bolt_event(), "say": None}
    ev = rt.parse_event(raw)
    assert ev.is_dm is False
    assert ev.scope_id == "T1"


@pytest.mark.asyncio
async def test_slack_runtime_channel_binding_fallback():
    """When `/vystak route hero` pinned a channel, plain @mentions in that
    channel route to the pinned agent (no per-thread binding exists)."""
    store = MemoryChannelStore()
    await store.set_thread_binding("slack", "T1", "C1:", "channel-pinned")
    rt = SlackChannelRuntime(
        config=_config(default_agent=None),
        routes={
            "hero": {"address": "http://hero:8000"},
            "channel-pinned": {"address": "http://x:8000"},
        },
        store=store,
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "app_mention", "event": _bolt_event(), "say": None}
    ev = rt.parse_event(raw)
    assert await rt.resolve_route(ev) == "channel-pinned"


@pytest.mark.asyncio
async def test_deliver_message_calls_chat_postMessage():
    from unittest.mock import AsyncMock, MagicMock

    rt = SlackChannelRuntime(
        config=_config(canonical_name="x.channels.dev"),
        routes={},
        store=MemoryChannelStore(),
    )
    rt._app = MagicMock()
    rt._app.client.chat_postMessage = AsyncMock()
    await rt.deliver_message("C0AV6PJ4VHU", "digest", {})
    rt._app.client.chat_postMessage.assert_awaited_once_with(
        channel="C0AV6PJ4VHU", text="digest",
    )
