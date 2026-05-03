"""Tests for DiscordChannelRuntime."""

from dataclasses import dataclass, field

import pytest
from vystak_channel_discord.runtime import DiscordChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.types import AgentReply, SkipEvent


def _config():
    return {
        "channel_type": "discord",
        "agent_protocol": "a2a-turn",
        "agents": ["hero"],
        "default_agent": "hero",
        "group_policy": "open",
        "dm_policy": "open",
        "allow_from": [],
        "allow_bots": False,
        "channel_overrides": {},
        "register_slash_commands": False,
    }


def test_runtime_constructable():
    rt = DiscordChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    assert rt.channel_type == "discord"


@dataclass
class _FakeUser:
    id: int
    bot: bool = False


@dataclass
class _FakeChannel:
    id: int
    type_str: str = "text"  # "text" | "dm" | "thread" | "forum"

    @property
    def type(self):
        # Mimic discord.ChannelType enum lookup we use in parse_event.
        return self.type_str


@dataclass
class _FakeGuild:
    id: int


@dataclass
class _FakeThread:
    id: int


@dataclass
class _FakeMessage:
    id: int
    author: _FakeUser
    channel: _FakeChannel
    guild: _FakeGuild | None
    content: str
    mentions: list[_FakeUser] = field(default_factory=list)
    thread: _FakeThread | None = None
    reference: object | None = None


def _bot_user():
    return _FakeUser(id=999, bot=True)


def _make_runtime():
    rt = DiscordChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    bot = _bot_user()
    rt._bot_user = bot  # type: ignore[attr-defined]
    return rt


def test_parse_event_guild_message_with_mention():
    rt = _make_runtime()
    msg = _FakeMessage(
        id=10,
        author=_FakeUser(id=1),
        channel=_FakeChannel(id=200, type_str="text"),
        guild=_FakeGuild(id=100),
        content=f"hi <@{rt._bot_user.id}>",
        mentions=[rt._bot_user],
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    assert ev.scope_id == "100/200"
    assert ev.thread_id == "10"
    assert ev.user_id == "1"
    assert ev.is_dm is False
    assert ev.mentions_bot is True


def test_parse_event_dm_uses_dm_scope():
    rt = _make_runtime()
    msg = _FakeMessage(
        id=11,
        author=_FakeUser(id=2),
        channel=_FakeChannel(id=300, type_str="dm"),
        guild=None,
        content="hello",
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    assert ev.scope_id == "dm/2"
    assert ev.is_dm is True
    assert ev.mentions_bot is False


def test_parse_event_in_thread_uses_thread_id():
    rt = _make_runtime()
    msg = _FakeMessage(
        id=12,
        author=_FakeUser(id=3),
        channel=_FakeChannel(id=400, type_str="thread"),
        guild=_FakeGuild(id=100),
        content="hi",
        thread=_FakeThread(id=999),
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    assert ev.thread_id == "999"


def test_parse_event_skips_own_messages():
    rt = _make_runtime()
    msg = _FakeMessage(
        id=13,
        author=_FakeUser(id=rt._bot_user.id),
        channel=_FakeChannel(id=500, type_str="text"),
        guild=_FakeGuild(id=100),
        content="self",
    )
    with pytest.raises(SkipEvent):
        rt.parse_event({"kind": "message", "message": msg})


def test_parse_event_skips_other_bots_when_disallowed():
    rt = _make_runtime()
    msg = _FakeMessage(
        id=14,
        author=_FakeUser(id=42, bot=True),
        channel=_FakeChannel(id=600, type_str="text"),
        guild=_FakeGuild(id=100),
        content="hi",
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    assert ev.metadata["is_bot"] is True


@dataclass
class _FakeChannelWithSend(_FakeChannel):
    sent: list = field(default_factory=list)

    async def send(self, content: str):
        self.sent.append(content)


@pytest.mark.asyncio
async def test_post_reply_sends_to_channel():
    rt = _make_runtime()
    chan = _FakeChannelWithSend(id=200, type_str="text")
    msg = _FakeMessage(
        id=10,
        author=_FakeUser(id=1),
        channel=chan,
        guild=_FakeGuild(id=100),
        content="hi",
        mentions=[rt._bot_user],
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    await rt.post_reply(ev, "hero", AgentReply(text="hello back"))
    assert chan.sent == ["hello back"]


@pytest.mark.asyncio
async def test_post_reply_splits_long_messages():
    rt = _make_runtime()
    chan = _FakeChannelWithSend(id=200, type_str="text")
    msg = _FakeMessage(
        id=10,
        author=_FakeUser(id=1),
        channel=chan,
        guild=_FakeGuild(id=100),
        content="hi",
        mentions=[rt._bot_user],
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    long = "x" * 4500
    await rt.post_reply(ev, "hero", AgentReply(text=long))
    assert len(chan.sent) == 3
    assert all(len(s) <= 2000 for s in chan.sent)
    assert "".join(chan.sent) == long


@dataclass
class _FakeHistMsg:
    author: _FakeUser
    content: str


@dataclass
class _FakeChannelWithHistory(_FakeChannelWithSend):
    history_msgs: list = field(default_factory=list)

    def history(self, limit: int):
        msgs = self.history_msgs[:limit]

        async def _aiter():
            for m in msgs:
                yield m

        return _aiter()


@pytest.mark.asyncio
async def test_fetch_history_returns_messages_for_thread():
    rt = _make_runtime()
    chan = _FakeChannelWithHistory(id=400, type_str="thread")
    chan.history_msgs = [
        _FakeHistMsg(author=_FakeUser(id=1), content="user-msg"),
        _FakeHistMsg(author=rt._bot_user, content="bot-msg"),
    ]
    msg = _FakeMessage(
        id=12,
        author=_FakeUser(id=3),
        channel=chan,
        guild=_FakeGuild(id=100),
        content="hi",
        thread=_FakeThread(id=999),
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    history = await rt.fetch_history(ev)
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[1].role == "assistant"


@pytest.mark.asyncio
async def test_fetch_history_empty_for_top_level_message():
    rt = _make_runtime()
    chan = _FakeChannelWithHistory(id=200, type_str="text")
    msg = _FakeMessage(
        id=10,
        author=_FakeUser(id=1),
        channel=chan,
        guild=_FakeGuild(id=100),
        content="hi",
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    history = await rt.fetch_history(ev)
    assert history == []


@pytest.mark.asyncio
async def test_after_reply_persists_thread_binding():
    rt = _make_runtime()
    chan = _FakeChannelWithSend(id=200, type_str="thread")
    msg = _FakeMessage(
        id=12,
        author=_FakeUser(id=3),
        channel=chan,
        guild=_FakeGuild(id=100),
        content="hi",
        thread=_FakeThread(id=999),
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    await rt.after_reply(ev, "hero", AgentReply(text="ok"))
    bound = await rt.store.get_thread_binding("discord", ev.scope_id, ev.thread_id)
    assert bound == "hero"


@pytest.mark.asyncio
async def test_on_no_route_posts_message_when_configured():
    rt = DiscordChannelRuntime(
        config={**_config(), "no_route_message": "no agent here"},
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )
    rt._bot_user = _bot_user()
    chan = _FakeChannelWithSend(id=200, type_str="text")
    msg = _FakeMessage(
        id=10,
        author=_FakeUser(id=1),
        channel=chan,
        guild=_FakeGuild(id=100),
        content="hi",
        mentions=[rt._bot_user],
    )
    ev = rt.parse_event({"kind": "message", "message": msg})
    await rt.on_no_route(ev)
    assert chan.sent == ["no agent here"]
