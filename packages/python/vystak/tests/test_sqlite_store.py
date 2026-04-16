import asyncio

import pytest
from vystak.stores.sqlite import AsyncSqliteStore


@pytest.fixture()
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
def store_and_run(tmp_path, event_loop):
    db_path = str(tmp_path / "test.db")
    store = None

    async def setup():
        nonlocal store
        db = await __import__("aiosqlite").connect(db_path)
        store = AsyncSqliteStore(db)
        await store.setup()
        return store

    event_loop.run_until_complete(setup())

    def run(coro):
        return event_loop.run_until_complete(coro)

    yield store, run

    event_loop.run_until_complete(store._db.close())


class TestAsyncSqliteStore:
    def test_put_and_get(self, store_and_run):
        store, run = store_and_run
        run(store.aput(("user", "u1", "memories"), "key1", {"data": "likes coffee"}))
        item = run(store.aget(("user", "u1", "memories"), "key1"))
        assert item is not None
        assert item.value == {"data": "likes coffee"}
        assert item.key == "key1"
        assert item.namespace == ("user", "u1", "memories")

    def test_get_missing(self, store_and_run):
        store, run = store_and_run
        item = run(store.aget(("user", "u1", "memories"), "nonexistent"))
        assert item is None

    def test_search(self, store_and_run):
        store, run = store_and_run
        run(store.aput(("user", "u1", "memories"), "k1", {"data": "fact one"}))
        run(store.aput(("user", "u1", "memories"), "k2", {"data": "fact two"}))
        run(store.aput(("user", "u2", "memories"), "k3", {"data": "other user"}))
        results = run(store.asearch(("user", "u1", "memories")))
        assert len(results) == 2
        keys = {r.key for r in results}
        assert keys == {"k1", "k2"}

    def test_search_limit(self, store_and_run):
        store, run = store_and_run
        for i in range(5):
            run(store.aput(("ns",), f"k{i}", {"data": f"item {i}"}))
        results = run(store.asearch(("ns",), limit=3))
        assert len(results) == 3

    def test_search_different_namespace(self, store_and_run):
        store, run = store_and_run
        run(store.aput(("ns1",), "k1", {"data": "in ns1"}))
        run(store.aput(("ns2",), "k2", {"data": "in ns2"}))
        results = run(store.asearch(("ns1",)))
        assert len(results) == 1
        assert results[0].key == "k1"

    def test_delete(self, store_and_run):
        store, run = store_and_run
        run(store.aput(("ns",), "k1", {"data": "to delete"}))
        run(store.adelete(("ns",), "k1"))
        item = run(store.aget(("ns",), "k1"))
        assert item is None

    def test_upsert(self, store_and_run):
        store, run = store_and_run
        run(store.aput(("ns",), "k1", {"data": "original"}))
        run(store.aput(("ns",), "k1", {"data": "updated"}))
        item = run(store.aget(("ns",), "k1"))
        assert item.value == {"data": "updated"}

    def test_setup_idempotent(self, store_and_run):
        store, run = store_and_run
        run(store.setup())
        run(store.setup())
        run(store.aput(("ns",), "k1", {"data": "works"}))
        item = run(store.aget(("ns",), "k1"))
        assert item is not None


class TestContextManager:
    def test_from_conn_string(self, tmp_path):
        db_path = str(tmp_path / "cm_test.db")
        loop = asyncio.new_event_loop()

        async def _test():
            async with AsyncSqliteStore.from_conn_string(db_path) as store:
                await store.aput(("ns",), "k1", {"data": "test"})
                item = await store.aget(("ns",), "k1")
                assert item.value == {"data": "test"}

        loop.run_until_complete(_test())
        loop.close()
