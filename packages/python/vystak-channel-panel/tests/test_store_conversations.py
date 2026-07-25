"""SqlitePanelStore — conversations + messages."""

import sqlite3

import pytest
from vystak_channel_panel.store import SqlitePanelStore


@pytest.fixture
async def store(tmp_path):
    s = SqlitePanelStore(tmp_path / "panel.db")
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
async def project(store):
    user = await store.create_user("a@example.com", role="admin")
    proj = await store.create_project("P", user.id)
    return user, proj


async def test_create_and_list(store, project):
    user, proj = project
    c1 = await store.create_conversation(proj.id, user.id, "weather-agent")
    c2 = await store.create_conversation(proj.id, user.id, "time-agent", title="T")
    assert c1.title == "" and c2.title == "T"
    listed = await store.list_conversations(proj.id)
    assert {c.id for c in listed} == {c1.id, c2.id}


async def test_list_conversations_orders_newest_updated_first(store, project):
    user, proj = project
    c1 = await store.create_conversation(proj.id, user.id, "weather-agent")
    await store.create_conversation(proj.id, user.id, "time-agent")
    # Bumping c1's updated_at should move it to the front, ahead of a
    # conversation created after it but never touched again.
    await store.add_message(c1.id, "user", "hi")
    listed = await store.list_conversations(proj.id)
    assert listed[0].id == c1.id


async def test_update_title_and_response_id(store, project):
    user, proj = project
    c = await store.create_conversation(proj.id, user.id, "weather-agent")
    updated = await store.update_conversation(
        c.id, title="Hello", last_response_id="resp_1"
    )
    assert updated.title == "Hello"
    assert updated.last_response_id == "resp_1"
    assert updated.updated_at >= c.updated_at
    assert await store.update_conversation("missing", title="x") is None


async def test_messages_round_trip_ordered(store, project):
    user, proj = project
    c = await store.create_conversation(proj.id, user.id, "weather-agent")
    m1 = await store.add_message(c.id, "user", "hi")
    m2 = await store.add_message(c.id, "assistant", "hello!", response_id="resp_1")
    msgs = await store.list_messages(c.id)
    assert [m.id for m in msgs] == [m1.id, m2.id]
    assert msgs[1].response_id == "resp_1"


async def test_add_message_bumps_conversation_updated_at(store, project):
    user, proj = project
    c = await store.create_conversation(proj.id, user.id, "weather-agent")
    await store.add_message(c.id, "user", "hi")
    got = await store.get_conversation(c.id)
    assert got.updated_at >= c.updated_at


async def test_delete_conversation_cascades(store, project):
    user, proj = project
    c = await store.create_conversation(proj.id, user.id, "weather-agent")
    await store.add_message(c.id, "user", "hi")
    await store.delete_conversation(c.id)
    assert await store.get_conversation(c.id) is None
    assert await store.list_messages(c.id) == []


async def test_list_messages_survives_malformed_parts_json(store, project, caplog):
    """A malformed `parts` value must not take out the whole conversation's
    history with a json.JSONDecodeError — degrade to parts=None and log a
    warning instead."""
    user, proj = project
    c = await store.create_conversation(proj.id, user.id, "weather-agent")
    m = await store.add_message(c.id, "user", "hi", parts=[{"type": "text"}])

    # Corrupt the stored parts column directly — simulates a torn write or
    # hand-edited row, not something reachable through add_message's own
    # json.dumps().
    async with store._write() as db:
        await db.execute(
            "UPDATE messages SET parts = ? WHERE id = ?",
            ("{not valid json", m.id),
        )

    with caplog.at_level("WARNING"):
        msgs = await store.list_messages(c.id)

    assert len(msgs) == 1
    assert msgs[0].parts is None
    assert any("parts" in rec.message for rec in caplog.records)


async def test_active_turn_lifecycle(store, project):
    user, proj = project
    conv = await store.create_conversation(proj.id, user.id, "agent-a")
    assert conv.active_turn_id is None

    await store.set_active_turn(conv.id, "turn-1")
    conv2 = await store.get_conversation(conv.id)
    assert conv2.active_turn_id == "turn-1"
    assert [c.id for c in await store.list_active_turns()] == [conv.id]

    # mismatched turn id: no-op
    assert await store.clear_active_turn(conv.id, "other-turn") is False
    assert (await store.get_conversation(conv.id)).active_turn_id == "turn-1"

    assert await store.clear_active_turn(conv.id, "turn-1") is True
    assert (await store.get_conversation(conv.id)).active_turn_id is None
    assert await store.list_active_turns() == []
    # idempotent second clear
    assert await store.clear_active_turn(conv.id, "turn-1") is False


async def test_add_message_persists_turn_id(store, project):
    user, proj = project
    conv = await store.create_conversation(proj.id, user.id, "agent-a")
    msg = await store.add_message(conv.id, "assistant", "hello", turn_id="turn-9")
    fetched = (await store.list_messages(conv.id))[-1]
    assert fetched.turn_id == "turn-9"
    assert msg.turn_id == "turn-9"


async def test_add_message_does_not_leak_into_later_commit(store, project, monkeypatch):
    user, proj = project
    c = await store.create_conversation(proj.id, user.id, "weather-agent")

    real_execute = store.db.execute
    call_count = 0

    async def flaky_execute(sql, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:  # the updated_at bump inside add_message fails
            raise sqlite3.OperationalError("simulated failure")
        return await real_execute(sql, *args, **kwargs)

    monkeypatch.setattr(store.db, "execute", flaky_execute)

    with pytest.raises(sqlite3.OperationalError):
        await store.add_message(c.id, "user", "hi")

    monkeypatch.undo()

    # An unrelated later write must not silently persist the partial insert.
    await store.create_user("z@example.com")

    assert await store.list_messages(c.id) == []
