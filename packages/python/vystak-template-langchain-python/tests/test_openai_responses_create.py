"""ResponsesHandler.create() non-streaming behavior."""

import pytest
from _vystak.runtime.openai.responses import ResponsesHandler


class FakeGraph:
    async def ainvoke(self, input, config):  # noqa: ANN001
        return {"messages": [{"role": "assistant", "content": "pong"}]}


def _fake_agent():
    class _A:
        name = "weather"
    return _A()


@pytest.fixture
def handler():
    return ResponsesHandler(agent=_fake_agent(), graph=FakeGraph(), store=None)


@pytest.mark.asyncio
async def test_create_non_streaming_returns_response_envelope(handler):
    body = {"model": "vystak/weather", "input": "ping", "store": True}
    resp = await handler.create(body)
    assert resp["object"] == "response"
    assert resp["model"] == "vystak/weather"
    assert resp["status"] == "completed"
    assert resp["output"][0]["content"][0]["text"] == "pong"
    assert resp["id"].startswith("resp_")


@pytest.mark.asyncio
async def test_create_with_store_true_persists_via_thread_id(handler):
    captured_configs = []

    class CapturingGraph:
        async def ainvoke(self, input, config):
            captured_configs.append(config)
            return {"messages": [{"role": "assistant", "content": "x"}]}

    h = ResponsesHandler(agent=_fake_agent(), graph=CapturingGraph(), store=None)
    resp = await h.create({"model": "vystak/weather", "input": "p", "store": True})
    assert "configurable" in captured_configs[0]
    assert captured_configs[0]["configurable"]["thread_id"] == resp["id"]


@pytest.mark.asyncio
async def test_create_with_previous_response_id_reuses_thread(handler):
    captured = []

    class CapturingGraph:
        async def ainvoke(self, input, config):
            captured.append(config)
            return {"messages": [{"role": "assistant", "content": "x"}]}

    h = ResponsesHandler(agent=_fake_agent(), graph=CapturingGraph(), store=None)
    await h.create({
        "model": "vystak/weather", "input": "p",
        "store": True, "previous_response_id": "resp_existing",
    })
    assert captured[0]["configurable"]["thread_id"] == "resp_existing"


@pytest.mark.asyncio
async def test_create_input_accepts_string_or_message_array(handler):
    r1 = await handler.create({"model": "vystak/weather", "input": "ping", "store": True})
    r2 = await handler.create({
        "model": "vystak/weather",
        "input": [{"role": "user", "content": "ping"}],
        "store": True,
    })
    assert r1["status"] == "completed"
    assert r2["status"] == "completed"
