import json

import pytest
from _vystak.runtime.openai.responses import ResponsesHandler
from _vystak.runtime.store import CheckpointObserver


class _Agent:
    name = "probe"
    sessions = None


class _Graph:
    """Yields two chat-model chunks; a checkpoint commits between them."""

    def __init__(self, observer, thread_id):
        self._observer = observer
        self._thread_id = thread_id

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        yield {"event": "on_chat_model_stream", "data": {"chunk": {"content": "one"}}}
        self._observer.record(self._thread_id, "ck-mid")
        yield {"event": "on_chat_model_stream", "data": {"chunk": {"content": "two"}}}


def _payloads(chunks):
    out = []
    for c in chunks:
        line = c.strip()
        if line.startswith("data:") and not line.endswith("[DONE]"):
            out.append(json.loads(line[len("data:"):].strip()))
    return out


@pytest.mark.asyncio
async def test_marker_emitted_after_commit_and_before_next_event():
    observer = CheckpointObserver()
    thread_id = "resp_fixed"
    handler = ResponsesHandler(
        agent=_Agent(), graph=_Graph(observer, thread_id), observer=observer
    )
    body = {"previous_response_id": thread_id, "input": "hi", "stream": True}

    chunks = [c async for c in handler._stream_iterator(body)]
    types = [p.get("type") for p in _payloads(chunks)]

    first_delta = types.index("response.output_text.delta")
    marker = types.index("vystak.checkpoint")
    second_delta = types.index("response.output_text.delta", first_delta + 1)
    assert first_delta < marker < second_delta


@pytest.mark.asyncio
async def test_marker_carries_checkpoint_id():
    observer = CheckpointObserver()
    handler = ResponsesHandler(
        agent=_Agent(), graph=_Graph(observer, "resp_fixed"), observer=observer
    )
    payloads = _payloads(
        [c async for c in handler._stream_iterator(
            {"previous_response_id": "resp_fixed", "input": "hi"}
        )]
    )
    markers = [p for p in payloads if p.get("type") == "vystak.checkpoint"]
    assert [m["checkpoint_id"] for m in markers] == ["ck-mid"]


@pytest.mark.asyncio
async def test_no_observer_emits_no_markers():
    observer = CheckpointObserver()
    handler = ResponsesHandler(agent=_Agent(), graph=_Graph(observer, "resp_fixed"))
    payloads = _payloads(
        [c async for c in handler._stream_iterator(
            {"previous_response_id": "resp_fixed", "input": "hi"}
        )]
    )
    assert not [p for p in payloads if p.get("type") == "vystak.checkpoint"]
