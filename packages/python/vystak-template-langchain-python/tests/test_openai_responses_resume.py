import pytest
from _vystak.runtime.openai.responses import ResponsesHandler


class _Agent:
    name = "probe"
    sessions = None


class _RecordingGraph:
    def __init__(self):
        self.inputs = []

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        self.inputs.append(input)
        yield {"event": "on_chat_model_stream", "data": {"chunk": {"content": "resumed"}}}


@pytest.mark.asyncio
async def test_resume_passes_none_as_graph_input():
    graph = _RecordingGraph()
    handler = ResponsesHandler(agent=_Agent(), graph=graph)
    _ = [c async for c in handler.resume_stream("thread-1", None)]
    assert graph.inputs == [None]


@pytest.mark.asyncio
async def test_resume_with_value_passes_command():
    graph = _RecordingGraph()
    handler = ResponsesHandler(agent=_Agent(), graph=graph)
    _ = [c async for c in handler.resume_stream("thread-1", {"approved": True})]
    sent = graph.inputs[0]
    assert type(sent).__name__ == "Command"
    assert sent.resume == {"approved": True}


@pytest.mark.asyncio
async def test_resume_uses_given_thread_id():
    graph = _RecordingGraph()
    handler = ResponsesHandler(agent=_Agent(), graph=graph)
    chunks = [c async for c in handler.resume_stream("thread-xyz", None)]
    assert any("thread-xyz" in c for c in chunks)
