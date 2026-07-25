"""SqlitePanelStore — projects, members, default project."""

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


@pytest.mark.skip(reason="conversations land in next task")
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
