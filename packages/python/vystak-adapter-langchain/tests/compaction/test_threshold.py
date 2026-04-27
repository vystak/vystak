
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from vystak_adapter_langchain.compaction.coverage import assign_vystak_msg_id
from vystak_adapter_langchain.compaction.errors import CompactionError, SummaryResult
from vystak_adapter_langchain.compaction.store import (
    InMemoryCompactionStore,
)
from vystak_adapter_langchain.compaction.threshold import maybe_compact


class _Stub:
    model_name = "claude-haiku-test"

    def __init__(self, tokens: int):
        self._tokens = tokens

    async def aget_num_tokens_from_messages(self, messages):
        return self._tokens


async def _ok_summarize(model, messages, *, instructions=None):
    return SummaryResult(
        text="SUMMARY",
        model_id="claude-haiku-test",
        usage={"input_tokens": 50, "output_tokens": 10},
    )


async def _failing_summarize(model, messages, *, instructions=None):
    raise CompactionError("rate limited")


def _msgs():
    out = [HumanMessage(content="a"), AIMessage(content="b"),
           HumanMessage(content="c"), AIMessage(content="d")]
    assign_vystak_msg_id(out, thread_id="t1", start=1)
    return out


@pytest.mark.asyncio
async def test_below_threshold_returns_messages_unchanged():
    store = InMemoryCompactionStore()
    msgs = _msgs()
    out, fallback = await maybe_compact(
        msgs, model=_Stub(tokens=10_000),
        last_input_tokens=None,
        context_window=200_000, trigger_pct=0.75, keep_recent_pct=0.10,
        target_tokens=100_000,
        summarizer=_Stub(tokens=0), summarize_fn=_ok_summarize,
        compaction_store=store, thread_id="t1",
    )
    assert out is msgs
    assert fallback is None
    assert await store.latest("t1") is None


@pytest.mark.asyncio
async def test_above_threshold_writes_compaction_and_returns_summary():
    store = InMemoryCompactionStore()
    msgs = _msgs()
    out, fallback = await maybe_compact(
        msgs, model=_Stub(tokens=170_000),
        last_input_tokens=None,
        context_window=200_000, trigger_pct=0.75, keep_recent_pct=0.5,
        target_tokens=100_000,
        summarizer=_Stub(tokens=0), summarize_fn=_ok_summarize,
        compaction_store=store, thread_id="t1",
    )
    assert fallback is None
    assert isinstance(out[0], SystemMessage) and "SUMMARY" in out[0].content
    row = await store.latest("t1")
    assert row.trigger == "threshold"


@pytest.mark.asyncio
async def test_idempotency_recent_compaction_suppresses_layer3():
    store = InMemoryCompactionStore()
    msgs = _msgs()
    await store.write(
        thread_id="t1", summary_text="prev", up_to_message_id="t1:3",
        trigger="autonomous", summarizer_model="x", usage={},
    )
    out, fallback = await maybe_compact(
        msgs, model=_Stub(tokens=170_000),
        last_input_tokens=None,
        context_window=200_000, trigger_pct=0.75, keep_recent_pct=0.10,
        target_tokens=100_000,
        summarizer=_Stub(tokens=0), summarize_fn=_ok_summarize,
        compaction_store=store, thread_id="t1",
    )
    rows = await store.list("t1")
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_summarizer_failure_returns_truncated_with_fallback_signal():
    store = InMemoryCompactionStore()
    msgs = _msgs()
    out, fallback = await maybe_compact(
        msgs, model=_Stub(tokens=170_000),
        last_input_tokens=None,
        context_window=200_000, trigger_pct=0.75, keep_recent_pct=0.10,
        target_tokens=100,
        summarizer=_Stub(tokens=0), summarize_fn=_failing_summarize,
        compaction_store=store, thread_id="t1",
    )
    assert fallback is not None
    assert "rate limited" in fallback
    assert await store.latest("t1") is None
    assert len(out) <= len(msgs)


@pytest.mark.asyncio
async def test_metrics_recorded_on_successful_write():
    from vystak_adapter_langchain.compaction.metrics import CompactionMetrics
    store = InMemoryCompactionStore()
    msgs = _msgs()
    metrics = CompactionMetrics()
    await maybe_compact(
        msgs, model=_Stub(tokens=170_000),
        last_input_tokens=None,
        context_window=200_000, trigger_pct=0.75, keep_recent_pct=0.5,
        target_tokens=100_000,
        summarizer=_Stub(tokens=0), summarize_fn=_ok_summarize,
        compaction_store=store, thread_id="t1",
        metrics=metrics,
    )
    assert metrics.total_count(layer="layer3", trigger="threshold", outcome="written") == 1


@pytest.mark.asyncio
async def test_metrics_recorded_on_suppression():
    from vystak_adapter_langchain.compaction.metrics import CompactionMetrics
    store = InMemoryCompactionStore()
    msgs = _msgs()
    await store.write(
        thread_id="t1", summary_text="prev", up_to_message_id="t1:3",
        trigger="autonomous", summarizer_model="x", usage={},
    )
    metrics = CompactionMetrics()
    await maybe_compact(
        msgs, model=_Stub(tokens=170_000),
        last_input_tokens=None,
        context_window=200_000, trigger_pct=0.75, keep_recent_pct=0.10,
        target_tokens=100_000,
        summarizer=_Stub(tokens=0), summarize_fn=_ok_summarize,
        compaction_store=store, thread_id="t1",
        metrics=metrics,
    )
    # Either "covered" or "recent" — at least one suppression
    total_supp = (metrics.suppressions(layer="layer3", reason="recent")
                  + metrics.suppressions(layer="layer3", reason="covered"))
    assert total_supp == 1


@pytest.mark.asyncio
async def test_metrics_recorded_on_fallback():
    from vystak_adapter_langchain.compaction.metrics import CompactionMetrics
    store = InMemoryCompactionStore()
    msgs = _msgs()
    metrics = CompactionMetrics()
    await maybe_compact(
        msgs, model=_Stub(tokens=170_000),
        last_input_tokens=None,
        context_window=200_000, trigger_pct=0.75, keep_recent_pct=0.10,
        target_tokens=100,
        summarizer=_Stub(tokens=0), summarize_fn=_failing_summarize,
        compaction_store=store, thread_id="t1",
        metrics=metrics,
    )
    assert metrics.total_count(layer="layer3", trigger="threshold", outcome="failed_fallback") == 1
