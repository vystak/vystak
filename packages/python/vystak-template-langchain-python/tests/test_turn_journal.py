import pytest
from _vystak.runtime.turn_journal import InMemoryTurnJournal, SqliteTurnJournal


def _journals(tmp_path):
    return [
        ("memory", InMemoryTurnJournal()),
        ("sqlite", SqliteTurnJournal(str(tmp_path / "turns.db"))),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "sqlite"])
async def test_create_then_get_roundtrip(tmp_path, kind):
    j = dict(_journals(tmp_path))[kind]
    await j.create("t1", "subj.a", {"input": "hello"})
    rec = await j.get("t1")
    assert rec.turn_id == "t1"
    assert rec.stream_subject == "subj.a"
    assert rec.request == {"input": "hello"}
    assert rec.status == "running"
    assert rec.last_seq == -1
    assert rec.boundary_seq == -1
    assert rec.attempts == 0
    await j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "sqlite"])
async def test_boundary_lookup_by_checkpoint(tmp_path, kind):
    j = dict(_journals(tmp_path))[kind]
    await j.create("t1", "subj.a", {})
    await j.record_boundary("t1", "ck-1", 4)
    await j.record_boundary("t1", "ck-2", 9)
    assert await j.seq_for_checkpoint("t1", "ck-1") == 4
    assert await j.seq_for_checkpoint("t1", "ck-2") == 9
    assert await j.seq_for_checkpoint("t1", "ck-missing") is None
    rec = await j.get("t1")
    assert rec.boundary_seq == 9
    await j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "sqlite"])
async def test_list_running_excludes_terminal_and_parked(tmp_path, kind):
    j = dict(_journals(tmp_path))[kind]
    for turn_id, status in [("a", "running"), ("b", "done"), ("c", "failed"), ("d", "parked")]:
        await j.create(turn_id, "s", {})
        if status != "running":
            await j.set_status(turn_id, status)
    assert sorted(r.turn_id for r in await j.list_running()) == ["a"]
    await j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "sqlite"])
async def test_bump_attempts_returns_new_value(tmp_path, kind):
    j = dict(_journals(tmp_path))[kind]
    await j.create("t1", "s", {})
    assert await j.bump_attempts("t1") == 1
    assert await j.bump_attempts("t1") == 2
    assert (await j.get("t1")).attempts == 2
    await j.close()


@pytest.mark.asyncio
async def test_sqlite_survives_reopen(tmp_path):
    path = str(tmp_path / "turns.db")
    j = SqliteTurnJournal(path)
    await j.create("t1", "subj.a", {"input": "hello"})
    await j.set_last_seq("t1", 7)
    await j.set_thread_id("t1", "resp_abc")
    await j.close()

    reopened = SqliteTurnJournal(path)
    rec = await reopened.get("t1")
    assert rec.last_seq == 7
    assert rec.thread_id == "resp_abc"
    assert rec.status == "running"
    await reopened.close()


@pytest.mark.asyncio
async def test_get_unknown_turn_returns_none(tmp_path):
    j = SqliteTurnJournal(str(tmp_path / "turns.db"))
    assert await j.get("nope") is None
    await j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "sqlite"])
async def test_duplicate_create_preserves_original_row(tmp_path, kind):
    j = dict(_journals(tmp_path))[kind]
    await j.create("t1", "subj.a", {"input": "hello"})
    await j.bump_attempts("t1")
    await j.set_last_seq("t1", 5)
    await j.create("t1", "subj.b", {"input": "goodbye"})
    rec = await j.get("t1")
    assert rec.stream_subject == "subj.a"
    assert rec.request == {"input": "hello"}
    assert rec.attempts == 1
    assert rec.last_seq == 5
    await j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "sqlite"])
async def test_unknown_turn_id_mutations_are_silent_noops(tmp_path, kind):
    j = dict(_journals(tmp_path))[kind]
    await j.set_thread_id("nope", "resp_abc")
    await j.record_boundary("nope", "ck-1", 3)
    await j.set_last_seq("nope", 5)
    await j.set_status("nope", "done")
    assert await j.get("nope") is None
    assert await j.seq_for_checkpoint("nope", "ck-1") is None
    await j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "sqlite"])
async def test_bump_attempts_on_unknown_turn_returns_zero(tmp_path, kind):
    j = dict(_journals(tmp_path))[kind]
    assert await j.bump_attempts("nope") == 0
    assert await j.get("nope") is None
    await j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "sqlite"])
async def test_get_result_mutation_does_not_affect_stored_state(tmp_path, kind):
    j = dict(_journals(tmp_path))[kind]
    await j.create("t1", "subj.a", {"input": "hello"})
    rec = await j.get("t1")
    rec.status = "done"
    rec.attempts = 99
    fresh = await j.get("t1")
    assert fresh.status == "running"
    assert fresh.attempts == 0
    await j.close()
