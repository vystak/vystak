"""Layers 2 + 3 contention — simulate the autonomous middleware writing
a compaction, then immediately invoke Layer 3. Layer 3 must defer."""

from datetime import UTC

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from vystak_adapter_langchain.compaction.coverage import assign_vystak_msg_id
from vystak_adapter_langchain.compaction.errors import SummaryResult
from vystak_adapter_langchain.compaction.store import InMemoryCompactionStore
from vystak_adapter_langchain.compaction.threshold import maybe_compact


class _Stub:
    model_name = "x"
    async def aget_num_tokens_from_messages(self, messages):
        return 999_999


async def _summarize(model, messages, *, instructions=None):
    return SummaryResult(text="LAYER3 SUMMARY", model_id="x", usage={})


def _msgs():
    out = [HumanMessage(content="a"), AIMessage(content="b"),
           HumanMessage(content="c"), AIMessage(content="d")]
    assign_vystak_msg_id(out, thread_id="t1", start=1)
    return out


@pytest.mark.asyncio
async def test_recent_layer2_write_suppresses_layer3():
    store = InMemoryCompactionStore()
    msgs = _msgs()

    await store.write(
        thread_id="t1", summary_text="LAYER2 SUMMARY", up_to_message_id="t1:3",
        trigger="autonomous", summarizer_model="layer2-model", usage={},
    )

    out, fallback = await maybe_compact(
        msgs, model=_Stub(),
        last_input_tokens=None,
        context_window=200_000, trigger_pct=0.75, keep_recent_pct=0.10,
        target_tokens=100_000,
        summarizer=_Stub(), summarize_fn=_summarize,
        compaction_store=store, thread_id="t1",
    )

    rows = await store.list("t1")
    assert len(rows) == 1
    assert rows[0].trigger == "autonomous"


@pytest.mark.asyncio
async def test_old_layer2_write_does_not_suppress_layer3_when_uncovered():
    """If the prior compaction is old AND covers <70%, Layer 3 still fires."""
    store = InMemoryCompactionStore()
    msgs = _msgs()

    await store.write(
        thread_id="t1", summary_text="OLD", up_to_message_id="t1:1",
        trigger="autonomous", summarizer_model="x", usage={},
    )
    from dataclasses import replace
    from datetime import datetime, timedelta
    store._rows["t1"][0] = replace(
        store._rows["t1"][0],
        created_at=datetime.now(UTC) - timedelta(seconds=120),
    )

    out, fallback = await maybe_compact(
        msgs, model=_Stub(),
        last_input_tokens=None,
        context_window=200_000, trigger_pct=0.75, keep_recent_pct=0.5,
        target_tokens=100_000,
        summarizer=_Stub(), summarize_fn=_summarize,
        compaction_store=store, thread_id="t1",
    )

    rows = await store.list("t1")
    assert len(rows) == 2
    assert rows[0].trigger == "threshold"
