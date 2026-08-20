import pytest
from _vystak.runtime.store import CheckpointObserver, ObservedSaver


class _FakeSaver:
    def __init__(self):
        self.puts = []

    async def aput(self, config, checkpoint, metadata, new_versions):
        self.puts.append(checkpoint["id"])
        return {"ok": True}

    async def aget_tuple(self, config):
        return None

    def with_allowlist(self, extra_allowlist):
        return _FakeSaver()


@pytest.mark.asyncio
async def test_aput_delegates_and_records_id():
    inner = _FakeSaver()
    obs = CheckpointObserver()
    saver = ObservedSaver(inner, obs)
    cfg = {"configurable": {"thread_id": "t1"}}

    result = await saver.aput(cfg, {"id": "ck-1"}, {}, {})

    assert result == {"ok": True}
    assert inner.puts == ["ck-1"]
    assert obs.drain("t1") == ["ck-1"]


@pytest.mark.asyncio
async def test_drain_is_per_thread_and_empties():
    obs = CheckpointObserver()
    saver = ObservedSaver(_FakeSaver(), obs)
    await saver.aput({"configurable": {"thread_id": "a"}}, {"id": "ck-a"}, {}, {})
    await saver.aput({"configurable": {"thread_id": "b"}}, {"id": "ck-b"}, {}, {})

    assert obs.drain("a") == ["ck-a"]
    assert obs.drain("a") == []
    assert obs.drain("b") == ["ck-b"]


@pytest.mark.asyncio
async def test_unobserved_thread_drains_empty():
    assert CheckpointObserver().drain("never-seen") == []


@pytest.mark.asyncio
async def test_release_discards_thread_state():
    obs = CheckpointObserver()
    saver = ObservedSaver(_FakeSaver(), obs)
    await saver.aput({"configurable": {"thread_id": "t"}}, {"id": "ck"}, {}, {})
    obs.release("t")
    assert obs.drain("t") == []


@pytest.mark.asyncio
async def test_unknown_attributes_proxy_to_inner():
    inner = _FakeSaver()
    saver = ObservedSaver(inner, CheckpointObserver())
    assert await saver.aget_tuple({}) is None


def test_observed_saver_is_accepted_as_a_checkpointer():
    """Regression guard: LangGraph's `ensure_valid_checkpointer` rejects any
    checkpointer that isn't a `BaseCheckpointSaver` instance at
    `graph.compile()` time. An earlier draft of `ObservedSaver` was a plain
    object and broke every real deployment (caught by
    test_mcp.py::test_app_startup_attaches_mcp_tools, which is the only
    existing test that actually runs the FastAPI lifespan)."""
    from langgraph.checkpoint.base import BaseCheckpointSaver

    assert isinstance(ObservedSaver(_FakeSaver(), CheckpointObserver()), BaseCheckpointSaver)


@pytest.mark.asyncio
async def test_with_allowlist_stays_wrapped_and_keeps_observing():
    """Regression guard: `with_allowlist` must return a still-wrapped
    `ObservedSaver`, not the bare inner saver. LangGraph's
    `apply_checkpointer_allowlist` uses the return value as the checkpointer
    going forward (gated behind `LANGGRAPH_STRICT_MSGPACK`); an unwrapped
    return would silently stop notifying the observer while checkpoints keep
    committing — a stale-boundary durability lie."""
    obs = CheckpointObserver()
    saver = ObservedSaver(_FakeSaver(), obs)

    reallowlisted = saver.with_allowlist([("some", "path")])

    assert isinstance(reallowlisted, ObservedSaver)
    assert reallowlisted._observer is obs

    result = await reallowlisted.aput(
        {"configurable": {"thread_id": "t1"}}, {"id": "ck-1"}, {}, {}
    )

    assert result == {"ok": True}
    assert obs.drain("t1") == ["ck-1"]
