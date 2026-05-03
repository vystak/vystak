"""Tests for SlackChannelRuntime."""

import pytest
from vystak.schema.common import ChannelType
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.types import AgentReply, SkipEvent
from vystak_channel_slack.runtime import SlackChannelRuntime


def _config():
    return {
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
    raw = {"type": "message", "event": _bolt_event(thread_ts="1.0"), "say": None}
    ev = rt.parse_event(raw)
    assert ev.thread_id == "C1:1.0"


def test_parse_event_bot_marked_in_metadata():
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "message", "event": _bolt_event(bot_id="B1"), "say": None}
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
