"""Tests for vystak_channel_runtime.agent_client."""

import httpx
import pytest
from vystak_channel_runtime.agent_client import A2AAgentClient, AgentClient
from vystak_channel_runtime.types import AgentCallError


@pytest.mark.asyncio
async def test_a2a_agent_client_implements_protocol():
    client = A2AAgentClient()
    assert isinstance(client, AgentClient)


@pytest.mark.asyncio
async def test_send_turn_returns_text(monkeypatch):
    captured = {}

    async def fake_post(self, url, *, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": json["id"],
                "result": {"messages": [{"role": "assistant", "content": "pong"}]},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = A2AAgentClient()
    reply = await client.send_turn(
        "http://hero:8000",
        text="ping",
        thread_id="t1",
    )
    assert reply.text == "pong"
    assert captured["url"] == "http://hero:8000/a2a"
    assert captured["json"]["method"] == "tasks/send"


@pytest.mark.asyncio
async def test_send_turn_retries_then_fails(monkeypatch):
    calls = {"n": 0}

    async def flaky_post(self, url, *, json, timeout):
        calls["n"] += 1
        return httpx.Response(503, text="upstream down")

    monkeypatch.setattr(httpx.AsyncClient, "post", flaky_post)
    client = A2AAgentClient(max_retries=3, base_backoff=0.01)
    with pytest.raises(AgentCallError):
        await client.send_turn("http://hero:8000", text="ping", thread_id="t1")
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_send_turn_succeeds_after_retry(monkeypatch):
    calls = {"n": 0}

    async def flaky_post(self, url, *, json, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(503, text="upstream down")
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": json["id"],
                "result": {"messages": [{"role": "assistant", "content": "ok"}]},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", flaky_post)
    client = A2AAgentClient(max_retries=3, base_backoff=0.01)
    reply = await client.send_turn("http://hero:8000", text="ping", thread_id="t1")
    assert reply.text == "ok"
    assert calls["n"] == 2
