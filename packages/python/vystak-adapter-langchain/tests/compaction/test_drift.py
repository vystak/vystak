"""Run threshold compaction 5+ times; assert generations advance and
summaries stay bounded; first generation remains retrievable."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

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


def _make_summary(generation: int):
    async def _f(model, messages, *, instructions=None):
        return SummaryResult(
            text=f"summary gen {generation}: " + "x" * 50,
            model_id="x", usage={},
        )
    return _f


def _msgs(n: int, start_id: int = 1):
    out: list = []
    for i in range(n):
        out.append(HumanMessage(content=f"u{i}"))
        out.append(AIMessage(content=f"a{i}"))
    assign_vystak_msg_id(out, thread_id="t1", start=start_id)
    return out


def _age_out_last_compaction(store):
    rows = store._rows["t1"]
    rows[-1] = replace(
        rows[-1],
        created_at=datetime.now(UTC) - timedelta(seconds=300),
    )


@pytest.mark.asyncio
async def test_five_generations_advance_and_remain_retrievable():
    store = InMemoryCompactionStore()
    target_tokens = 100_000
    next_id = 1

    for gen in range(1, 6):
        # Create a growing message set simulating a conversation that keeps growing
        msgs = _msgs(20 + gen * 5, start_id=next_id)
        next_id += len(msgs)
        # Age out the previous compaction so Layer 3 will fire
        if gen > 1:
            _age_out_last_compaction(store)
        # Call maybe_compact with high token count to trigger compaction
        out, fallback = await maybe_compact(
            msgs, model=_Stub(),
            last_input_tokens=None,
            context_window=200_000, trigger_pct=0.75, keep_recent_pct=0.10,
            target_tokens=target_tokens,
            summarizer=_Stub(), summarize_fn=_make_summary(gen),
            compaction_store=store, thread_id="t1",
        )
        # Verify compaction fired
        assert fallback is None

    rows = await store.list("t1")
    assert len(rows) == 5
    assert [r.generation for r in rows] == [5, 4, 3, 2, 1]
    ids = [int(r.up_to_message_id.split(":")[1]) for r in reversed(rows)]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    for r in rows:
        assert len(r.summary_text) <= target_tokens * 4
    first = await store.get("t1", generation=1)
    assert first is not None
    assert "gen 1" in first.summary_text
