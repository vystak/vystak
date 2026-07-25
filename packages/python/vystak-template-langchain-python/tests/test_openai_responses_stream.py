"""ResponsesHandler streaming — assert OpenAI Responses SSE event sequence."""

import json

import pytest
from _vystak.runtime.openai.responses import ResponsesHandler


class FakeStreamingGraph:
    def __init__(self, events: list[dict]) -> None:
        self._events = events

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        for ev in self._events:
            yield ev


def _parse_sse(frames: list[str]) -> list[dict]:
    out = []
    for f in frames:
        for line in f.splitlines():
            if line.startswith("data: ") and not line.endswith("[DONE]"):
                out.append(json.loads(line[len("data: "):]))
    return out


@pytest.mark.asyncio
async def test_streaming_emits_created_then_deltas_then_completed(fake_agent):
    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": {"content": "he"}}},
        {"event": "on_chat_model_stream", "data": {"chunk": {"content": "llo"}}},
    ]
    h = ResponsesHandler(agent=fake_agent, graph=FakeStreamingGraph(events), store=None)
    body = {"model": "vystak/weather", "input": "hi", "stream": True, "store": True}

    frames = []
    async for f in await h.create(body):
        frames.append(f)

    parsed = _parse_sse(frames)
    types = [p.get("type") for p in parsed]
    assert types[0] == "response.created"
    assert "response.output_text.delta" in types
    assert "response.completed" in types
    assert any(f.strip() == "data: [DONE]" for f in frames)


@pytest.mark.asyncio
async def test_streaming_delta_events_carry_text(fake_agent):
    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": {"content": "hi"}}},
    ]
    h = ResponsesHandler(agent=fake_agent, graph=FakeStreamingGraph(events), store=None)
    body = {"model": "vystak/weather", "input": "x", "stream": True, "store": True}

    frames = []
    async for f in await h.create(body):
        frames.append(f)
    parsed = _parse_sse(frames)
    deltas = [p for p in parsed if p.get("type") == "response.output_text.delta"]
    assert any(d.get("delta") == "hi" for d in deltas)


@pytest.mark.asyncio
async def test_streaming_thinking_block_content_flattens_to_string_delta(fake_agent):
    """Regression: Anthropic extended-thinking makes AIMessageChunk.content a
    list of typed blocks, e.g. [{"type": "thinking", ...}, {"type": "text",
    "text": "Sunny"}]. The delta emitted on the wire must still be a plain
    string (the OpenAI-compatible consumer rejects a list)."""
    events = [
        {
            "event": "on_chat_model_stream",
            "data": {
                "chunk": {
                    "content": [
                        {"type": "thinking", "thinking": "The user wants weather"},
                        {"type": "text", "text": "Sunny"},
                    ]
                }
            },
        },
    ]
    h = ResponsesHandler(agent=fake_agent, graph=FakeStreamingGraph(events), store=None)
    body = {"model": "vystak/weather", "input": "x", "stream": True, "store": True}

    frames = []
    async for f in await h.create(body):
        frames.append(f)
    parsed = _parse_sse(frames)

    deltas = [p for p in parsed if p.get("type") == "response.output_text.delta"]
    assert len(deltas) == 1
    assert deltas[0]["delta"] == "Sunny"
    assert isinstance(deltas[0]["delta"], str)

    done = [p for p in parsed if p.get("type") == "response.output_text.done"]
    assert len(done) == 1
    assert done[0]["text"] == "Sunny"
    assert isinstance(done[0]["text"], str)


@pytest.mark.asyncio
async def test_streaming_thinking_only_chunk_emits_no_delta(fake_agent):
    """Regression, exact reproduced shape: Anthropic streams thinking-only
    chunks (no text block at all) before any text chunk arrives —
    input_value=[{'thinking': 'The user', ..., 'type': 'thinking', 'index': 0}].
    Pre-fix, `if text:` saw a non-empty *list* and emitted a delta carrying
    the list (what a strict PanelStreamEvent consumer rejected). Post-fix,
    flatten_content() drops thinking-only content to "", which is falsy, so
    no delta is emitted for that chunk — matching the A2A path's `if delta:`
    behavior exactly. Only the later text-bearing chunk should produce a
    delta."""
    events = [
        {
            "event": "on_chat_model_stream",
            "data": {
                "chunk": {
                    "content": [
                        {"type": "thinking", "thinking": "The user", "index": 0}
                    ]
                }
            },
        },
        {
            "event": "on_chat_model_stream",
            "data": {"chunk": {"content": [{"type": "text", "text": "Sunny"}]}},
        },
    ]
    h = ResponsesHandler(agent=fake_agent, graph=FakeStreamingGraph(events), store=None)
    body = {"model": "vystak/weather", "input": "x", "stream": True, "store": True}

    frames = []
    async for f in await h.create(body):
        frames.append(f)
    parsed = _parse_sse(frames)

    deltas = [p for p in parsed if p.get("type") == "response.output_text.delta"]
    assert [d["delta"] for d in deltas] == ["Sunny"]

    done = [p for p in parsed if p.get("type") == "response.output_text.done"]
    assert done[0]["text"] == "Sunny"


@pytest.mark.asyncio
async def test_streaming_response_id_threaded_through_events(fake_agent):
    events = [{"event": "on_chat_model_stream", "data": {"chunk": {"content": "x"}}}]
    h = ResponsesHandler(agent=fake_agent, graph=FakeStreamingGraph(events), store=None)
    body = {"model": "vystak/weather", "input": "x", "stream": True, "store": True}

    frames = []
    async for f in await h.create(body):
        frames.append(f)
    parsed = _parse_sse(frames)
    response_ids = {p["response"]["id"] for p in parsed if p.get("type") == "response.created"}
    assert len(response_ids) == 1
    rid = response_ids.pop()
    assert rid.startswith("resp_")
