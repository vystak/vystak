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


@pytest.mark.asyncio
async def test_streaming_tool_call_emits_four_events_in_order(fake_agent):
    """on_tool_start/on_tool_end (the same events a2a_native/executor.py
    already watches) must surface as the four OpenAI Responses tool-call SSE
    shapes vystak-chat/client.py parses: output_item.added(function_call),
    function_call_arguments.delta, function_call_arguments.done,
    output_item.added(function_call_output) — all sharing one call_id keyed
    off the LangChain run_id."""
    events = [
        {
            "event": "on_tool_start",
            "run_id": "run-abc-123",
            "name": "get_weather",
            "data": {"input": {"city": "Tokyo"}},
        },
        {
            "event": "on_tool_end",
            "run_id": "run-abc-123",
            "name": "get_weather",
            "data": {"input": {"city": "Tokyo"}, "output": "22C, sunny"},
        },
    ]
    h = ResponsesHandler(agent=fake_agent, graph=FakeStreamingGraph(events), store=None)
    body = {"model": "vystak/weather", "input": "weather in tokyo", "stream": True, "store": True}

    frames = []
    async for f in await h.create(body):
        frames.append(f)
    parsed = _parse_sse(frames)

    tool_events = [
        p
        for p in parsed
        if p.get("type")
        in (
            "response.output_item.added",
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
        )
    ]
    assert [p["type"] for p in tool_events] == [
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.added",
    ]

    added_start, delta, done, added_end = tool_events

    assert added_start["item"] == {
        "type": "function_call",
        "id": "run-abc-123",
        "call_id": "run-abc-123",
        "name": "get_weather",
        "arguments": "",
    }
    assert delta["call_id"] == "run-abc-123"
    assert json.loads(delta["delta"]) == {"city": "Tokyo"}
    assert done["call_id"] == "run-abc-123"
    assert done["arguments"] == delta["delta"]
    assert added_end["item"] == {
        "type": "function_call_output",
        "call_id": "run-abc-123",
        "output": "22C, sunny",
    }


@pytest.mark.asyncio
async def test_streaming_tool_call_serializes_non_string_input_and_output(fake_agent):
    """Tool `input` (a dict of kwargs) and `output` (whatever the tool
    returns — here a LangChain-style list of content blocks) are never
    guaranteed to be strings. Must serialize without raising, the same class
    of bug (assuming `str`) that already broke this file once."""
    events = [
        {
            "event": "on_tool_start",
            "run_id": "run-xyz-9",
            "name": "search",
            "data": {"input": {"query": "weather", "limit": 5}},
        },
        {
            "event": "on_tool_end",
            "run_id": "run-xyz-9",
            "name": "search",
            "data": {"output": [{"type": "text", "text": "Sunny and warm"}]},
        },
    ]
    h = ResponsesHandler(agent=fake_agent, graph=FakeStreamingGraph(events), store=None)
    body = {"model": "vystak/weather", "input": "search weather", "stream": True, "store": True}

    frames = []
    async for f in await h.create(body):
        frames.append(f)
    parsed = _parse_sse(frames)

    delta = next(p for p in parsed if p["type"] == "response.function_call_arguments.delta")
    assert json.loads(delta["delta"]) == {"query": "weather", "limit": 5}

    output_item = next(
        p
        for p in parsed
        if p["type"] == "response.output_item.added"
        and p["item"].get("type") == "function_call_output"
    )
    assert output_item["item"]["output"] == "Sunny and warm"


@pytest.mark.asyncio
async def test_streaming_tool_error_emits_terminating_error_output(fake_agent):
    """LangChain emits on_tool_error (not on_tool_end) when a tool raises.
    Without handling it, the function_call start event has no terminating
    output event, so a consumer can never tell the call finished — the
    control-panel UI would render it as perpetually running. The error must
    still terminate the call: a function_call_output item, marked error=True,
    sharing the same run_id-derived call_id, with the exception serialized
    defensively (the raw value is an exception instance, not a string)."""
    events = [
        {
            "event": "on_tool_start",
            "run_id": "run-err-1",
            "name": "get_weather",
            "data": {"input": {"city": "Nowhere"}},
        },
        {
            "event": "on_tool_error",
            "run_id": "run-err-1",
            "name": "get_weather",
            "data": {"error": ValueError("boom"), "input": {"city": "Nowhere"}},
        },
    ]
    h = ResponsesHandler(agent=fake_agent, graph=FakeStreamingGraph(events), store=None)
    body = {"model": "vystak/weather", "input": "weather nowhere", "stream": True, "store": True}

    frames = []
    async for f in await h.create(body):
        frames.append(f)
    parsed = _parse_sse(frames)

    # The start events (function_call added + arguments delta/done) still fire.
    added_start = next(
        p
        for p in parsed
        if p["type"] == "response.output_item.added" and p["item"]["type"] == "function_call"
    )
    assert added_start["item"]["call_id"] == "run-err-1"

    # Exactly one terminating output event for this call, marked as an error.
    output_items = [
        p
        for p in parsed
        if p["type"] == "response.output_item.added"
        and p["item"].get("type") == "function_call_output"
    ]
    assert len(output_items) == 1
    error_item = output_items[0]["item"]
    assert error_item["call_id"] == "run-err-1"
    assert error_item["error"] is True
    # Plain text, not JSON-quoted: consumers like vystak-chat/chat.py render
    # `output` as raw text, so `'"boom"'` would show literal quote marks.
    assert error_item["output"] == "boom"

    # The stream still completes normally afterward.
    assert "response.completed" in [p["type"] for p in parsed]
    assert frames[-1].strip() == "data: [DONE]"


@pytest.mark.asyncio
async def test_streaming_without_tool_events_matches_baseline_shape(fake_agent):
    """Additive guarantee: a stream with no tool events must keep exactly
    the pre-existing event sequence and per-event key set (captured in
    scratchpad/baseline-agent-sse.txt before this feature) — response.created,
    response.output_text.delta*, response.output_text.done,
    response.completed, [DONE]. call_id/tool fields must never leak into
    these events."""
    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": {"content": "**Current weather"}}},
        {"event": "on_chat_model_stream", "data": {"chunk": {"content": " in Kyiv:**"}}},
    ]
    h = ResponsesHandler(agent=fake_agent, graph=FakeStreamingGraph(events), store=None)
    body = {"model": "vystak/weather", "input": "weather in kyiv", "stream": True, "store": True}

    frames = []
    async for f in await h.create(body):
        frames.append(f)

    parsed = _parse_sse(frames)
    types = [p.get("type") for p in parsed]
    assert types == [
        "response.created",
        "response.output_text.delta",
        "response.output_text.delta",
        "response.output_text.done",
        "response.completed",
    ]
    assert frames[-1].strip() == "data: [DONE]"

    key_sets = {
        "response.created": {"type", "response"},
        "response.output_text.delta": {"type", "item_id", "output_index", "content_index", "delta"},
        "response.output_text.done": {"type", "item_id", "output_index", "content_index", "text"},
        "response.completed": {"type", "response"},
    }
    for p in parsed:
        assert set(p.keys()) == key_sets[p["type"]]

    created = next(p for p in parsed if p["type"] == "response.created")
    assert set(created["response"].keys()) == {"id", "object", "created_at", "model", "status"}
    completed = next(p for p in parsed if p["type"] == "response.completed")
    assert set(completed["response"].keys()) == {
        "id",
        "object",
        "created_at",
        "model",
        "status",
        "output",
    }
