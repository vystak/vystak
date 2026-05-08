"""MemoryManager — recall + save/forget sentinel parsing."""

import pytest
from _vystak.runtime.memory import MemoryManager


class FakeStore:
    def __init__(self) -> None:
        self.entries: dict[tuple, list[dict]] = {}

    async def aput(self, namespace: tuple, key: str, value: dict) -> None:
        self.entries.setdefault(namespace, []).append({"key": key, "value": value})

    async def asearch(self, namespace: tuple, query: str) -> list:
        results = []
        for e in self.entries.get(namespace, []):
            if query.lower() in str(e["value"]).lower():
                class _R:
                    def __init__(self, key, value):
                        self.key = key
                        self.value = value
                results.append(_R(e["key"], e["value"]))
        return results

    async def adelete(self, namespace: tuple, key: str) -> None:
        ns = self.entries.get(namespace, [])
        self.entries[namespace] = [e for e in ns if e["key"] != key]


def _agent():
    class _A:
        memory = "configured"
    return _A()


@pytest.mark.asyncio
async def test_recall_returns_matching_memories():
    store = FakeStore()
    await store.aput(("user", "u1"), "m1", {"content": "User likes pizza"})
    mgr = MemoryManager(_agent(), store=store)
    out = await mgr.recall(user_id="u1", query="pizza")
    assert any("pizza" in str(m) for m in out)


@pytest.mark.asyncio
async def test_save_via_sentinel():
    store = FakeStore()
    mgr = MemoryManager(_agent(), store=store)
    handled = await mgr.handle_tool_output(
        "__SAVE_MEMORY__|user|likes pizza",
        user_id="u1",
        project_id="p1",
    )
    assert handled is True
    assert ("user", "u1") in store.entries
    assert "pizza" in str(store.entries[("user", "u1")][0]["value"])


@pytest.mark.asyncio
async def test_forget_via_sentinel():
    store = FakeStore()
    await store.aput(("user", "u1"), "m1", {"content": "old"})
    mgr = MemoryManager(_agent(), store=store)
    handled = await mgr.handle_tool_output(
        "__FORGET_MEMORY__|m1",
        user_id="u1",
        project_id="p1",
    )
    assert handled is True
    assert store.entries[("user", "u1")] == []


@pytest.mark.asyncio
async def test_non_sentinel_passes_through():
    mgr = MemoryManager(_agent(), store=FakeStore())
    handled = await mgr.handle_tool_output("regular tool output", user_id="u1", project_id="p1")
    assert handled is False
