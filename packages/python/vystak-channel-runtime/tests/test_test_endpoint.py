"""Tests for the /test/event synthetic dispatch endpoint."""

from fastapi.testclient import TestClient
from vystak.schema.common import ChannelType
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.test_endpoint import build_test_app
from vystak_channel_runtime.types import AgentReply, InboundEvent


class CapturingRuntime(ChannelRuntime):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.handled = []

    async def start(self): pass
    async def stop(self): pass

    def parse_event(self, raw):
        return InboundEvent(**raw)

    async def post_reply(self, e, r, reply):
        self.handled.append((e.scope_id, r, reply.text))


def test_test_endpoint_dispatches(monkeypatch):
    rt = CapturingRuntime(
        config={
            "channel_type": "slack",
            "agent_protocol": "a2a-turn",
            "default_agent": "hero",
            "group_policy": "open",
            "dm_policy": "open",
        },
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
    )

    class _FakeAgent:
        async def send_turn(self, *a, **kw):
            return AgentReply(text="ok")
        async def stream_turn(self, *a, **kw):
            raise NotImplementedError

    rt._agent_client = _FakeAgent()
    app = build_test_app(rt)
    client = TestClient(app)
    resp = client.post(
        "/test/event",
        json={
            "channel_type": ChannelType.SLACK.value,
            "scope_id": "C1",
            "thread_id": None,
            "user_id": "U",
            "text": "hi",
            "is_dm": False,
            "mentions_bot": True,
            "metadata": {},
        },
    )
    assert resp.status_code == 200
    assert rt.handled == [("C1", "hero", "ok")]
