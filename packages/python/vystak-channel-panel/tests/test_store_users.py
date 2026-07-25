"""SqlitePanelStore — users + settings."""

import sqlite3

import pytest
from vystak_channel_panel.store import SqlitePanelStore


@pytest.fixture
async def store(tmp_path):
    s = SqlitePanelStore(tmp_path / "panel.db")
    await s.connect()
    yield s
    await s.close()


async def test_count_users_empty(store):
    assert await store.count_users() == 0


async def test_create_and_get_user(store):
    u = await store.create_user("Admin@Example.com", name="Ada", role="admin")
    assert u.email == "admin@example.com"  # normalized lowercase
    assert u.role == "admin"
    assert u.status == "active"
    got = await store.get_user_by_email("ADMIN@example.COM")
    assert got is not None and got.id == u.id
    assert await store.get_user(u.id) == got


async def test_duplicate_email_rejected(store):
    await store.create_user("a@example.com")
    with pytest.raises(sqlite3.IntegrityError):
        await store.create_user("a@example.com")


async def test_list_and_update_user(store):
    u = await store.create_user("a@example.com")
    assert [x.id for x in await store.list_users()] == [u.id]
    updated = await store.update_user(u.id, role="admin", status="deactivated")
    assert updated.role == "admin" and updated.status == "deactivated"
    assert await store.update_user("missing", role="admin") is None


async def test_settings_round_trip(store):
    assert await store.get_setting("k") is None
    await store.set_setting("k", "v")
    await store.set_setting("k", "v2")
    assert await store.get_setting("k") == "v2"
