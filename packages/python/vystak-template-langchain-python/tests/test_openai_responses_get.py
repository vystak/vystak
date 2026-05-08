"""ResponsesHandler.get(response_id) — retrieve stored response."""

import pytest
from _vystak.runtime.openai.responses import ResponsesHandler


class FakeGraph:
    def __init__(self) -> None:
        self.checkpoint_seen = None

    async def aget_state(self, config):  # noqa: ANN001
        self.checkpoint_seen = config

        class _Snapshot:
            values = {"messages": [{"role": "assistant", "content": "stored"}]}
            config = {"configurable": {"thread_id": "resp_abc"}}
        return _Snapshot()


def _fake_agent():
    class _A:
        name = "weather"
    return _A()


@pytest.mark.asyncio
async def test_get_returns_stored_response():
    graph = FakeGraph()
    h = ResponsesHandler(agent=_fake_agent(), graph=graph, store=None)
    resp = await h.get("resp_abc")
    assert resp["id"] == "resp_abc"
    assert resp["status"] == "completed"
    assert resp["output"][0]["content"][0]["text"] == "stored"


@pytest.mark.asyncio
async def test_get_unknown_response_raises():
    class EmptyGraph:
        async def aget_state(self, config):
            class _S:
                values = {}
            return _S()

    h = ResponsesHandler(agent=_fake_agent(), graph=EmptyGraph(), store=None)
    with pytest.raises(KeyError):
        await h.get("resp_missing")
