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
