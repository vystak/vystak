import pytest
from vystak_adapter_langchain.compaction.store import CompactionRow, InMemoryCompactionStore


@pytest.mark.asyncio
async def test_first_write_returns_generation_one():
    store = InMemoryCompactionStore()
    gen = await store.write(
        thread_id="t1",
        summary_text="hello",
        up_to_message_id="m5",
        trigger="threshold",
        summarizer_model="claude",
        usage={"input_tokens": 100, "output_tokens": 30},
    )
    assert gen == 1


@pytest.mark.asyncio
async def test_subsequent_writes_increment_per_thread():
    store = InMemoryCompactionStore()
    a1 = await store.write(
        thread_id="A",
        summary_text="…",
        up_to_message_id="m1",
        trigger="threshold",
        summarizer_model="m",
        usage={},
    )
    a2 = await store.write(
        thread_id="A",
        summary_text="…",
        up_to_message_id="m2",
        trigger="threshold",
        summarizer_model="m",
        usage={},
    )
    b1 = await store.write(
        thread_id="B",
        summary_text="…",
        up_to_message_id="m1",
        trigger="threshold",
        summarizer_model="m",
        usage={},
    )
    assert (a1, a2, b1) == (1, 2, 1)


@pytest.mark.asyncio
async def test_latest_returns_highest_generation():
    store = InMemoryCompactionStore()
    await store.write(
        thread_id="A",
        summary_text="first",
        up_to_message_id="m1",
        trigger="threshold",
        summarizer_model="m",
        usage={},
    )
    await store.write(
        thread_id="A",
        summary_text="second",
        up_to_message_id="m2",
        trigger="threshold",
        summarizer_model="m",
        usage={},
    )
    latest = await store.latest("A")
    assert isinstance(latest, CompactionRow)
    assert latest.generation == 2
    assert latest.summary_text == "second"


@pytest.mark.asyncio
async def test_latest_none_for_unknown_thread():
    store = InMemoryCompactionStore()
    assert await store.latest("nope") is None


@pytest.mark.asyncio
async def test_list_returns_descending_generations():
    store = InMemoryCompactionStore()
    for _ in range(3):
        await store.write(
            thread_id="A",
            summary_text="x",
            up_to_message_id="m",
            trigger="threshold",
            summarizer_model="m",
            usage={},
        )
    rows = await store.list("A")
    assert [r.generation for r in rows] == [3, 2, 1]


@pytest.mark.asyncio
async def test_get_by_generation():
    store = InMemoryCompactionStore()
    await store.write(
        thread_id="A",
        summary_text="first",
        up_to_message_id="m1",
        trigger="threshold",
        summarizer_model="m",
        usage={},
    )
    row = await store.get("A", generation=1)
    assert row.summary_text == "first"
    assert await store.get("A", generation=99) is None
