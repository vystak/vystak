import aiosqlite
import pytest
from vystak_adapter_langchain.compaction.store import SqliteCompactionStore


@pytest.fixture
async def store(tmp_path):
    path = tmp_path / "compactions.db"
    db = await aiosqlite.connect(str(path))
    s = SqliteCompactionStore(db)
    await s.setup()
    yield s
    await db.close()


@pytest.mark.asyncio
async def test_write_and_latest_round_trip(store):
    gen = await store.write(
        thread_id="t1",
        summary_text="hello",
        up_to_message_id="m5",
        trigger="threshold",
        summarizer_model="claude",
        usage={"input_tokens": 100, "output_tokens": 30},
    )
    assert gen == 1
    row = await store.latest("t1")
    assert row.summary_text == "hello"
    assert row.input_tokens == 100


@pytest.mark.asyncio
async def test_generations_increment_per_thread(store):
    await store.write(
        thread_id="A",
        summary_text="a1",
        up_to_message_id="m",
        trigger="threshold",
        summarizer_model="m",
        usage={},
    )
    await store.write(
        thread_id="A",
        summary_text="a2",
        up_to_message_id="m",
        trigger="threshold",
        summarizer_model="m",
        usage={},
    )
    b1 = await store.write(
        thread_id="B",
        summary_text="b1",
        up_to_message_id="m",
        trigger="threshold",
        summarizer_model="m",
        usage={},
    )
    assert b1 == 1
    assert (await store.latest("A")).generation == 2


@pytest.mark.asyncio
async def test_list_returns_descending(store):
    for i in range(3):
        await store.write(
            thread_id="A",
            summary_text=f"s{i}",
            up_to_message_id="m",
            trigger="threshold",
            summarizer_model="m",
            usage={},
        )
    rows = await store.list("A")
    assert [r.generation for r in rows] == [3, 2, 1]


@pytest.mark.asyncio
async def test_get_specific_generation(store):
    await store.write(
        thread_id="A",
        summary_text="first",
        up_to_message_id="m",
        trigger="threshold",
        summarizer_model="m",
        usage={},
    )
    row = await store.get("A", generation=1)
    assert row.summary_text == "first"
    assert await store.get("A", generation=99) is None


@pytest.mark.asyncio
async def test_setup_is_idempotent(store):
    await store.setup()  # second call must not error
    await store.setup()
