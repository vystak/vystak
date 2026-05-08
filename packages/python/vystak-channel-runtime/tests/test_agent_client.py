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
    # A2A v0.3 spec method (post-Phase-10 SDK migration). The legacy
    # `tasks/send` is no longer supported by a2a-sdk's JSON-RPC dispatcher.
    assert captured["json"]["method"] == "message/send"
    # Message body must include kind="message" + messageId — required by
    # the SDK's v0.3 compat layer for wire validation.
    msg = captured["json"]["params"]["message"]
    assert msg["kind"] == "message"
    assert "messageId" in msg
    assert msg["role"] == "user"
    assert msg["parts"][0]["text"] == "ping"


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


@pytest.mark.asyncio
async def test_stream_turn_retries_on_5xx(monkeypatch):
    """Retry the connect/initial-response phase on 5xx; succeed on 2nd try."""
    calls = {"n": 0}

    class _FakeStreamResponse:
        def __init__(self, status_code: int, lines: list[str] | None = None):
            self.status_code = status_code
            self._lines = lines or []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aiter_lines(self):
            for line in self._lines:
                yield line

    def fake_stream(self, method, url, *, json, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            return _FakeStreamResponse(503)
        # Real agent SSE shape: token chunk has artifact.parts[].text.
        ok_line = (
            'data: {"jsonrpc":"2.0","id":"x","result":'
            '{"id":"t","artifact":{"parts":[{"text":"hi"}],"index":0,"append":true}}}'
        )
        return _FakeStreamResponse(200, lines=[ok_line])

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)
    client = A2AAgentClient(max_retries=3, base_backoff=0.01)
    chunks = []
    async for c in client.stream_turn(
        "http://hero:8000", text="ping", thread_id="t1",
    ):
        chunks.append(c)
    assert calls["n"] == 2
    assert any(c.delta == "hi" for c in chunks)


@pytest.mark.asyncio
async def test_chunk_from_sse_parses_token_artifact():
    """Token shape: result.artifact.parts[].text (real agent emission)."""
    chunk = A2AAgentClient._chunk_from_sse(
        '{"jsonrpc":"2.0","id":"x","result":'
        '{"id":"t","artifact":{"parts":[{"text":"hello "},{"text":"world"}]}}}'
    )
    assert chunk is not None
    assert chunk.type == "token"
    assert chunk.delta == "hello world"


@pytest.mark.asyncio
async def test_chunk_from_sse_parses_tool_call_event():
    """Bare A2AEvent dump for tool_call_start."""
    chunk = A2AAgentClient._chunk_from_sse(
        '{"type":"tool_call_start","data":{"tool_name":"get_weather"},"final":false}'
    )
    assert chunk is not None
    assert chunk.type == "tool_call"
    assert chunk.tool_name == "get_weather"


@pytest.mark.asyncio
async def test_chunk_from_sse_parses_tool_result_event():
    chunk = A2AAgentClient._chunk_from_sse(
        '{"type":"tool_call_end","data":{"tool_name":"get_weather","duration_ms":120}}'
    )
    assert chunk is not None
    assert chunk.type == "tool_result"
    assert chunk.tool_name == "get_weather"
    assert chunk.data == {"tool_name": "get_weather", "duration_ms": 120}


@pytest.mark.asyncio
async def test_chunk_from_sse_parses_status_final():
    """Status with state=completed becomes final chunk."""
    chunk = A2AAgentClient._chunk_from_sse(
        '{"jsonrpc":"2.0","id":"x","result":'
        '{"id":"t","status":{"state":"completed"},"final":true}}'
    )
    assert chunk is not None
    assert chunk.type == "final"
    assert chunk.final is True
