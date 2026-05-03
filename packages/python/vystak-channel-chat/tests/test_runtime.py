"""Tests for ChatChannelRuntime."""

from fastapi.testclient import TestClient
from vystak_channel_chat.runtime import ChatChannelRuntime, build_app
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.types import AgentReply


def _config():
    return {
        "channel_type": "chat",
        "agent_protocol": "a2a-turn",
        "agents": ["hero"],
        "default_agent": "hero",
        "group_policy": "open",
        "dm_policy": "open",
        "allow_from": [],
        "allow_bots": False,
        "channel_overrides": {},
    }


class _FakeAgent:
    async def send_turn(self, *a, **kw):
        return AgentReply(text="pong")

    async def stream_turn(self, *a, **kw):
        raise NotImplementedError


def test_chat_completions_returns_assistant_text():
    rt = ChatChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
        agent_client=_FakeAgent(),
    )
    app = build_app(rt)
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "vystak/hero",
            "messages": [{"role": "user", "content": "ping"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "pong"
