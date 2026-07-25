"""Password hashing/verification on the panel store."""

from __future__ import annotations

import pytest
from vystak_channel_panel.store import SqlitePanelStore


@pytest.fixture
async def store(tmp_path):
    s = SqlitePanelStore(tmp_path / "panel.db")
    await s.connect()
    yield s
    await s.close()


async def test_set_and_verify_roundtrip(store):
    user = await store.create_user("alice@example.com")
    assert await store.set_user_password(user.id, "testpass-alice-1") is True
    verified = await store.verify_user_password("alice@example.com", "testpass-alice-1")
    assert verified is not None
    assert verified.id == user.id
    assert verified.has_password is True


async def test_wrong_password_returns_none(store):
    user = await store.create_user("alice@example.com")
    await store.set_user_password(user.id, "testpass-alice-1")
    assert await store.verify_user_password("alice@example.com", "wrongpass-000") is None


async def test_unknown_email_returns_none(store):
    assert await store.verify_user_password("ghost@example.com", "testpass-x") is None


async def test_no_password_set_returns_none(store):
    await store.create_user("alice@example.com")
    assert await store.verify_user_password("alice@example.com", "testpass-x") is None


async def test_deactivated_user_returns_none(store):
    user = await store.create_user("alice@example.com")
    await store.set_user_password(user.id, "testpass-alice-1")
    await store.update_user(user.id, status="deactivated")
    assert await store.verify_user_password("alice@example.com", "testpass-alice-1") is None


async def test_overwrite_replaces_old_password(store):
    user = await store.create_user("alice@example.com")
    await store.set_user_password(user.id, "testpass-old-1")
    await store.set_user_password(user.id, "testpass-new-2")
    assert await store.verify_user_password("alice@example.com", "testpass-old-1") is None
    assert await store.verify_user_password("alice@example.com", "testpass-new-2") is not None


async def test_set_password_unknown_user_returns_false(store):
    assert await store.set_user_password("nope", "testpass-x-1") is False


async def test_hash_never_in_user_payloads(store):
    user = await store.create_user("alice@example.com")
    await store.set_user_password(user.id, "testpass-alice-1")
    for u in (
        await store.get_user(user.id),
        await store.get_user_by_email("alice@example.com"),
        *(await store.list_users()),
    ):
        assert "password_hash" not in u.model_dump()
        assert u.has_password is True


async def test_verify_email_is_case_insensitive(store):
    user = await store.create_user("Alice@Example.com")
    await store.set_user_password(user.id, "testpass-alice-1")
    assert await store.verify_user_password("ALICE@example.com", "testpass-alice-1") is not None


async def test_verify_with_nul_password_returns_none(store):
    user = await store.create_user("alice@example.com")
    await store.set_user_password(user.id, "testpass-alice-1")
    assert await store.verify_user_password("alice@example.com", "bad\x00pass") is None
