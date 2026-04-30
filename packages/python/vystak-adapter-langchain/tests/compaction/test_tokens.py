import pytest
from langchain_core.messages import AIMessage, HumanMessage
from vystak_adapter_langchain.compaction import tokens as _tokens_mod
from vystak_adapter_langchain.compaction.tokens import (
    EstimateResult,
    estimate_tokens,
)


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    """Tokenizer-probe cache is module-level; reset between tests so models
    with the same id() don't carry over a previous probe result."""
    _tokens_mod._TOKENIZER_PROBE_CACHE.clear()
    yield
    _tokens_mod._TOKENIZER_PROBE_CACHE.clear()


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
    # 4000 chars / 3.5 chars-per-token * 1.10 safety = ~1257 tokens.
    # Allow a 10% slack on either side of the calibration.
    assert 1100 <= r.tokens <= 1400


class _SyncOnlyModel:
    """Stub model exposing only the SYNC tokenizer (mirrors ChatAnthropic)."""

    def __init__(self, value: int):
        self._value = value
        self.calls = 0

    def get_num_tokens_from_messages(self, messages):
        self.calls += 1
        return self._value


@pytest.mark.asyncio
async def test_sync_only_model_uses_pre_flight_sync():
    model = _SyncOnlyModel(8500)
    r = await estimate_tokens(
        [HumanMessage(content="hi")],
        model=model,
        last_input_tokens=None,
        trigger_pct=0.75,
        context_window=200_000,
    )
    assert r.method == "pre_flight_sync"
    assert r.tokens == 8500
    assert model.calls == 1


class _NoTokenizerModel:
    """Stub model exposing neither tokenizer — must fall to chars/4."""


@pytest.mark.asyncio
async def test_no_tokenizer_falls_back_silently_after_first_log(caplog):
    """When neither tokenizer exists, fall back to chars/4 and log INFO once,
    not WARNING every turn (the prior behavior spammed every turn)."""
    import logging
    model = _NoTokenizerModel()
    msgs = [HumanMessage(content="x" * 4000)]
    caplog.set_level(logging.WARNING, logger="vystak_adapter_langchain.compaction.tokens")

    r1 = await estimate_tokens(
        msgs, model=model, last_input_tokens=None,
        trigger_pct=0.75, context_window=200_000,
    )
    r2 = await estimate_tokens(
        msgs, model=model, last_input_tokens=None,
        trigger_pct=0.75, context_window=200_000,
    )

    assert r1.method == "chars_div_4"
    assert r2.method == "chars_div_4"
    # No WARNING should be emitted on either call (the previous bug logged
    # WARNING every turn). INFO from the first probe is allowed and not
    # captured by caplog at WARNING level.
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == []
