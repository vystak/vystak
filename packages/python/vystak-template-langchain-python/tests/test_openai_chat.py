"""ChatCompletionsHandler — stateless /v1/chat/completions parity."""

import pytest
from _vystak.runtime.openai.chat import ChatCompletionsHandler


class FakeGraph:
    async def ainvoke(self, input, config):  # noqa: ANN001
        return {"messages": [{"role": "assistant", "content": "pong"}]}


def _fake_agent():
    class _A:
        name = "weather"
    return _A()


@pytest.fixture
def handler():
    return ChatCompletionsHandler(agent=_fake_agent(), graph=FakeGraph())


@pytest.mark.asyncio
async def test_create_returns_chat_completion_envelope(handler):
    body = {
        "model": "vystak/weather",
        "messages": [{"role": "user", "content": "ping"}],
    }
    resp = await handler.create(body)
    assert resp["object"] == "chat.completion"
    assert resp["model"] == "vystak/weather"
    assert resp["choices"][0]["message"]["content"] == "pong"
    assert resp["choices"][0]["message"]["role"] == "assistant"
    assert resp["choices"][0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_create_includes_usage_block(handler):
    body = {"model": "vystak/weather", "messages": [{"role": "user", "content": "ping"}]}
    resp = await handler.create(body)
    assert "usage" in resp
    assert "prompt_tokens" in resp["usage"]
    assert "completion_tokens" in resp["usage"]


@pytest.mark.asyncio
async def test_create_no_thread_id_passed_to_graph():
    captured = {}

    class CapturingGraph:
        async def ainvoke(self, input, config):
            captured["config"] = config
            return {"messages": [{"role": "assistant", "content": "x"}]}

    handler = ChatCompletionsHandler(agent=_fake_agent(), graph=CapturingGraph())
    await handler.create(
        {"model": "vystak/weather", "messages": [{"role": "user", "content": "p"}]}
    )
    assert "thread_id" not in (captured["config"].get("configurable") or {})
