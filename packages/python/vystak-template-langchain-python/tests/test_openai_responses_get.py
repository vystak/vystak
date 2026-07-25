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


@pytest.mark.asyncio
async def test_get_returns_stored_response(fake_agent):
    graph = FakeGraph()
    h = ResponsesHandler(agent=fake_agent, graph=graph, store=None)
    resp = await h.get("resp_abc")
    assert resp["id"] == "resp_abc"
    assert resp["status"] == "completed"
    assert resp["output"][0]["content"][0]["text"] == "stored"


@pytest.mark.asyncio
async def test_get_flattens_list_shaped_content(fake_agent):
    """Regression: a stored assistant message's .content can be a list of
    typed blocks (Anthropic extended-thinking) rather than a plain string."""

    class ThinkingGraph:
        async def aget_state(self, config):
            class _Snapshot:
                values = {
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {"type": "thinking", "thinking": "hmm"},
                                {"type": "text", "text": "stored"},
                            ],
                        }
                    ]
                }

            return _Snapshot()

    h = ResponsesHandler(agent=fake_agent, graph=ThinkingGraph(), store=None)
    resp = await h.get("resp_abc")
    text = resp["output"][0]["content"][0]["text"]
    assert text == "stored"
    assert isinstance(text, str)


@pytest.mark.asyncio
async def test_get_unknown_response_raises(fake_agent):
    class EmptyGraph:
        async def aget_state(self, config):
            class _S:
                values = {}
            return _S()

    h = ResponsesHandler(agent=fake_agent, graph=EmptyGraph(), store=None)
    with pytest.raises(KeyError):
        await h.get("resp_missing")
