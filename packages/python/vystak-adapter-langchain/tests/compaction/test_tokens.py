import pytest
from langchain_core.messages import AIMessage, HumanMessage
from vystak_adapter_langchain.compaction.tokens import (
    EstimateResult,
    estimate_tokens,
)


class _ModelTokenizer:
    """Stub model that exposes aget_num_tokens_from_messages."""

    def __init__(self, value: int, *, raises: Exception | None = None):
        self._value = value
        self._raises = raises
        self.calls = 0

    async def aget_num_tokens_from_messages(self, messages):
        self.calls += 1
        if self._raises:
            raise self._raises
        return self._value


@pytest.mark.asyncio
async def test_early_out_uses_last_input_tokens_when_clearly_below():
    model = _ModelTokenizer(99999)  # would be wrong if called
    messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
    r = await estimate_tokens(
        messages,
        model=model,
        last_input_tokens=1000,
        trigger_pct=0.75,
        context_window=200_000,
    )
    assert isinstance(r, EstimateResult)
    assert r.method == "early_out"
    assert r.tokens > 0
    assert model.calls == 0


@pytest.mark.asyncio
async def test_falls_through_to_pre_flight_near_threshold():
    model = _ModelTokenizer(170_000)
    messages = [HumanMessage(content="x" * 10_000)]
    r = await estimate_tokens(
        messages,
        model=model,
        last_input_tokens=140_000,  # already near 200_000 * 0.75 = 150_000
        trigger_pct=0.75,
        context_window=200_000,
    )
    assert r.method == "pre_flight"
    assert r.tokens == 170_000
    assert model.calls == 1


@pytest.mark.asyncio
async def test_first_turn_no_last_input_tokens_uses_pre_flight():
    model = _ModelTokenizer(8_500)
    r = await estimate_tokens(
        [HumanMessage(content="hi")],
        model=model,
        last_input_tokens=None,
        trigger_pct=0.75,
        context_window=200_000,
    )
    assert r.method == "pre_flight"
    assert model.calls == 1


@pytest.mark.asyncio
async def test_pre_flight_failure_falls_back_to_chars_div_4():
    model = _ModelTokenizer(0, raises=RuntimeError("boom"))
    messages = [HumanMessage(content="x" * 4000)]
    r = await estimate_tokens(
        messages,
        model=model,
        last_input_tokens=None,
        trigger_pct=0.75,
        context_window=200_000,
    )
    assert r.method == "chars_div_4"
    assert 900 <= r.tokens <= 1100
