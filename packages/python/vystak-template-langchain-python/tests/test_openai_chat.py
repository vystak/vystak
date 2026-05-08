"""ChatCompletionsHandler — stateless /v1/chat/completions parity."""

import pytest
from _vystak.runtime.openai.chat import ChatCompletionsHandler


class FakeGraph:
    async def ainvoke(self, input, config):  # noqa: ANN001
        return {"messages": [{"role": "assistant", "content": "pong"}]}


@pytest.fixture
def handler(fake_agent):
    return ChatCompletionsHandler(agent=fake_agent, graph=FakeGraph())


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
async def test_create_uses_ephemeral_thread_id_per_call(fake_agent):
    """Stateless: each call gets a fresh thread_id so no state survives."""
    captured = []

    class CapturingGraph:
        async def ainvoke(self, input, config):
            captured.append(config)
            return {"messages": [{"role": "assistant", "content": "x"}]}

    handler = ChatCompletionsHandler(agent=fake_agent, graph=CapturingGraph())
    await handler.create(
        {"model": "vystak/weather", "messages": [{"role": "user", "content": "p"}]}
    )
    await handler.create(
        {"model": "vystak/weather", "messages": [{"role": "user", "content": "q"}]}
    )

    t1 = captured[0]["configurable"]["thread_id"]
    t2 = captured[1]["configurable"]["thread_id"]
    assert t1.startswith("chat-")
    assert t2.startswith("chat-")
    assert t1 != t2
