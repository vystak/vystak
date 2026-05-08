"""ThresholdCompactor — Layer 3 prefill-threshold summarize."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from _vystak.runtime.compaction.compactor import ThresholdCompactor
from langchain_core.messages import AIMessage, HumanMessage


class FakeStore:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def write(self, **row) -> None:
        self.rows.append(row)

    async def latest(self, thread_id: str) -> dict | None:
        rows = [r for r in self.rows if r["thread_id"] == thread_id]
        return max(rows, key=lambda r: r["generation"]) if rows else None


def _fake_summarizer(text: str = "summary text"):
    s = AsyncMock()
    s.ainvoke = AsyncMock(return_value=AIMessage(content=text))
    return s


def _make_agent(trigger_pct=0.5, keep_recent_pct=0.2, context_window=1000):
    class _C:
        mode = "conservative"
        prune_tool_output_bytes = 4096
    c = _C()
    c.trigger_pct = trigger_pct
    c.keep_recent_pct = keep_recent_pct
    c.target_tokens = None
    c.context_window = context_window

    class _A:
        name = "test"
        compaction = c
    return _A()


@pytest.mark.asyncio
async def test_below_threshold_returns_messages_unchanged():
    msgs = [HumanMessage(content="hi"), AIMessage(content="ok")]
    store = FakeStore()
    cmp = ThresholdCompactor(_make_agent(), store, _fake_summarizer())
    result = await cmp.maybe_compact("t1", msgs, prefill_token_estimate=100)
    assert result == msgs
    assert store.rows == []


@pytest.mark.asyncio
async def test_above_threshold_summarizes_older_slice():
    msgs = [HumanMessage(content=f"q{i}") for i in range(10)]
    store = FakeStore()
    cmp = ThresholdCompactor(
        _make_agent(context_window=1000), store, _fake_summarizer("summarized")
    )
    result = await cmp.maybe_compact("t1", msgs, prefill_token_estimate=600)
    assert len(result) < len(msgs)
    assert any("summarized" in getattr(m, "content", "") for m in result)
    assert len(store.rows) == 1


@pytest.mark.asyncio
async def test_idempotency_guard_blocks_summary_within_60s():
    msgs = [HumanMessage(content=f"q{i}") for i in range(10)]
    store = FakeStore()
    store.rows.append({
        "thread_id": "t1",
        "generation": 1,
        "summary": "prior",
        "created_at": datetime.now(UTC),
        "covered_message_count": 7,
    })
    cmp = ThresholdCompactor(_make_agent(context_window=1000), store, _fake_summarizer())
    await cmp.maybe_compact("t1", msgs, prefill_token_estimate=600)
    assert len(store.rows) == 1


@pytest.mark.asyncio
async def test_idempotency_guard_allows_after_60s():
    msgs = [HumanMessage(content=f"q{i}") for i in range(10)]
    store = FakeStore()
    store.rows.append({
        "thread_id": "t1",
        "generation": 1,
        "summary": "prior",
        "created_at": datetime.now(UTC) - timedelta(seconds=120),
        "covered_message_count": 1,  # < 70% coverage
    })
    cmp = ThresholdCompactor(_make_agent(context_window=1000), store, _fake_summarizer())
    await cmp.maybe_compact("t1", msgs, prefill_token_estimate=600)
    assert len(store.rows) == 2
