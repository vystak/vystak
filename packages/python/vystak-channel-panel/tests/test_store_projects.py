"""SqlitePanelStore — projects, members, default project."""

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
async def users(store):
    a = await store.create_user("a@example.com", role="admin")
    b = await store.create_user("b@example.com")
    return a, b


async def test_create_get_list(store, users):
    a, b = users
    p = await store.create_project("Research", a.id)
    assert (await store.get_project(p.id)).name == "Research"
    assert [x.id for x in await store.list_projects_for_user(a.id)] == [p.id]
    assert await store.list_projects_for_user(b.id) == []


async def test_membership_visibility(store, users):
    a, b = users
    p = await store.create_project("Shared", a.id)
    assert not await store.user_can_access_project(p.id, b.id)
    await store.add_member(p.id, b.id)
    await store.add_member(p.id, b.id)  # idempotent
    assert await store.user_can_access_project(p.id, b.id)
    assert [x.id for x in await store.list_projects_for_user(b.id)] == [p.id]
    assert {u.email for u in await store.list_members(p.id)} == {"b@example.com"}
    await store.remove_member(p.id, b.id)
    assert not await store.user_can_access_project(p.id, b.id)


async def test_owner_always_has_access(store, users):
    a, _ = users
    p = await store.create_project("Mine", a.id)
    assert await store.user_can_access_project(p.id, a.id)


async def test_ensure_default_project_idempotent(store, users):
    a, _ = users
    p1 = await store.ensure_default_project(a.id)
    p2 = await store.ensure_default_project(a.id)
    assert p1.id == p2.id
    assert p1.is_default and p1.name == "Personal"


async def test_second_default_project_rejected(store, users):
    a, _ = users
    await store.ensure_default_project(a.id)
    with pytest.raises(sqlite3.IntegrityError):
        await store.create_project("Other", a.id, is_default=True)


async def test_ensure_default_project_recovers_from_lost_race(store, users, monkeypatch):
    a, _ = users
    existing = await store.ensure_default_project(a.id)

    real_get_default = store._get_default_project
    call_count = 0

    async def flaky_get_default(user_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Pretend no default exists yet, forcing ensure_default_project
            # down the create_project() path where it loses the race.
            return None
        return await real_get_default(user_id)

    monkeypatch.setattr(store, "_get_default_project", flaky_get_default)

    winner = await store.ensure_default_project(a.id)

    assert winner.id == existing.id
    assert call_count == 2


async def test_failed_delete_project_does_not_leak_into_later_commit(
    store, users, monkeypatch
):
    a, b = users
    p = await store.create_project("Doomed", a.id)
    await store.add_member(p.id, b.id)
    now = "2026-01-01T00:00:00+00:00"
    await store.db.execute(
        "INSERT INTO conversations (id, project_id, creator_id, agent_name, title, "
        "last_response_id, created_at, updated_at) "
        "VALUES ('conv-1', ?, ?, 'agent-x', '', NULL, ?, ?)",
        (p.id, a.id, now, now),
    )
    await store.db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, response_id, "
        "created_at) VALUES ('msg-1', 'conv-1', 'user', 'hi', NULL, ?)",
        (now,),
    )
    await store.db.commit()

    real_execute = store.db.execute
    call_count = 0

    async def flaky_execute(sql, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:  # second DELETE inside delete_project fails
            raise sqlite3.OperationalError("simulated failure")
        return await real_execute(sql, *args, **kwargs)

    monkeypatch.setattr(store.db, "execute", flaky_execute)

    with pytest.raises(sqlite3.OperationalError):
        await store.delete_project(p.id)

    monkeypatch.undo()

    # An unrelated later write must not silently persist the partial delete.
    await store.create_user("c@example.com")

    assert await store.get_project(p.id) is not None
    assert {u.id for u in await store.list_members(p.id)} == {b.id}
    async with store.db.execute(
        "SELECT COUNT(*) AS n FROM conversations WHERE project_id = ?", (p.id,)
    ) as cur:
        assert (await cur.fetchone())["n"] == 1
    async with store.db.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE conversation_id = ?", ("conv-1",)
    ) as cur:
        assert (await cur.fetchone())["n"] == 1


async def test_delete_project_cascades(store, users):
    a, b = users
    p = await store.create_project("Doomed", a.id)
    await store.add_member(p.id, b.id)
    c = await store.create_conversation(p.id, a.id, "agent-x")
    await store.add_message(c.id, "user", "hi")
    await store.delete_project(p.id)
    assert await store.get_project(p.id) is None
    assert await store.list_members(p.id) == []
    assert await store.list_conversations(p.id) == []
    assert await store.list_messages(c.id) == []
