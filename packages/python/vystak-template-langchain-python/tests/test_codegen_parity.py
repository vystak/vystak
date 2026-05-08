"""Golden-file parity: new ResponsesHandler emits documented OpenAI Responses SSE shapes.

This test is the gate that lets us delete the codegen path in Phase 9 with
confidence. If it ever fails, the new template diverged from documented
OpenAI Responses semantics; investigate before merging.
"""

import json
from pathlib import Path

import pytest
from _vystak.runtime.openai.responses import ResponsesHandler

GOLDEN = Path(__file__).parent / "golden" / "recorded_stream.json"


class ReplayGraph:
    def __init__(self, events: list[dict]) -> None:
        self._events = events

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        for ev in self._events:
            yield ev


def _normalize(payload: dict) -> dict:
    """Strip volatile fields (timestamps, random IDs) before comparison."""
    if "created_at" in payload:
        payload["created_at"] = 0
    if "response" in payload and isinstance(payload["response"], dict):
        if "created_at" in payload["response"]:
            payload["response"]["created_at"] = 0
        if "id" in payload["response"]:
            payload["response"]["id"] = "resp_NORMALIZED"
    if "item_id" in payload:
        payload["item_id"] = "msg_NORMALIZED"
    return payload


@pytest.mark.asyncio
async def test_response_stream_matches_documented_event_sequence(fake_agent):
    events = json.loads(GOLDEN.read_text())
    h = ResponsesHandler(agent=fake_agent, graph=ReplayGraph(events), store=None)

    frames = []
    async for f in await h.create({
        "model": "vystak/weather",
        "input": "x",
        "stream": True,
        "store": True,
    }):
        frames.append(f)

    parsed = []
    for f in frames:
        for line in f.splitlines():
            if line.startswith("data: "):
                payload = line[len("data: "):].strip()
                if payload == "[DONE]":
                    parsed.append({"type": "[DONE]"})
                else:
                    parsed.append(_normalize(json.loads(payload)))

    types = [p.get("type") for p in parsed]
    # Required event sequence per OpenAI Responses spec.
    assert types[0] == "response.created"
    assert "response.output_text.delta" in types
    assert "response.output_text.done" in types
    assert "response.completed" in types
    assert types[-1] == "[DONE]"

    # Concatenated delta text must equal the final completed text.
    deltas = "".join(
        p.get("delta", "") for p in parsed if p.get("type") == "response.output_text.delta"
    )
    final = next(p for p in parsed if p.get("type") == "response.output_text.done")["text"]
    assert deltas == final
