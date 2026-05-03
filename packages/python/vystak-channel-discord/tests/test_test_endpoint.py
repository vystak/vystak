"""Synthetic /test/event smoke for DiscordChannelRuntime."""

from fastapi.testclient import TestClient
from vystak.schema.common import ChannelType
from vystak_channel_discord.runtime import DiscordChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.test_endpoint import build_test_app
from vystak_channel_runtime.types import AgentReply


class _FakeAgent:
    async def send_turn(self, *a, **kw):
        return AgentReply(text="sync ack")
    async def stream_turn(self, *a, **kw):
        raise NotImplementedError


def test_test_endpoint_dispatches_into_discord_runtime():
    rt = DiscordChannelRuntime(
        config={
            "channel_type": "discord",
            "agent_protocol": "a2a-turn",
            "default_agent": "hero",
            "group_policy": "open",
            "dm_policy": "open",
            "agents": ["hero"],
            "register_slash_commands": False,
        },
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
        agent_client=_FakeAgent(),
    )
    posted = []
    async def fake_post_reply(event, route, reply):
        posted.append((event.scope_id, route, reply.text))
    rt.post_reply = fake_post_reply  # type: ignore[assignment]

    # parse_event() expects metadata['raw_message']; bypass by overriding for the test.
    def fake_parse(raw):
        from vystak_channel_runtime.types import InboundEvent
        return InboundEvent(**raw)
    rt.parse_event = fake_parse  # type: ignore[assignment]

    app = build_test_app(rt)
    client = TestClient(app)
    resp = client.post(
        "/test/event",
        json={
            "channel_type": ChannelType.DISCORD.value,
            "scope_id": "100/200",
            "thread_id": "T:1",
            "user_id": "U1",
            "text": "hi",
            "is_dm": False,
            "mentions_bot": True,
            "metadata": {},
        },
    )
    assert resp.status_code == 200
    assert posted == [("100/200", "hero", "sync ack")]
