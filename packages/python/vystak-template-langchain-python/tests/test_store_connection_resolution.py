"""Postgres connection-string resolution for sessions + memory.

Regression coverage for the bug fixed alongside Task 17's release-cell
audit: `build_checkpointer`'s postgres branch used to read a nonexistent
`sessions.connection_string` attribute directly (the schema only has
`connection_string_env`, an env var *name*) and never consulted the
provider-injected `SESSION_STORE_URL` env var the way `build_memory_store`
already did for `MEMORY_STORE_URL`. `_resolve_connection_string` is the
shared helper both factories now use; these tests pin its resolution
order and the two call sites that depend on it.
"""

import os
from unittest import mock

from _vystak.runtime.store import (
    _resolve_connection_string,
    build_checkpointer,
    build_memory_store,
)


class _Service:
    def __init__(self, engine=None, connection_string_env=None):
        self.engine = engine
        self.connection_string_env = connection_string_env


class _Agent:
    def __init__(self, sessions=None, memory=None):
        self.sessions = sessions
        self.memory = memory


# --- _resolve_connection_string -----------------------------------------


def test_resolve_prefers_injected_env_var():
    """SESSION_STORE_URL / MEMORY_STORE_URL (provider-injected) wins even
    when a BYO connection_string_env is also set."""
    svc = _Service(connection_string_env="MY_DB_URL")
    with mock.patch.dict(
        os.environ,
        {"SESSION_STORE_URL": "postgresql://provider", "MY_DB_URL": "postgresql://byo"},
        clear=True,
    ):
        assert _resolve_connection_string(svc, "SESSION_STORE_URL") == "postgresql://provider"


def test_resolve_falls_back_to_connection_string_env():
    """No provider-injected var (BYO/unmanaged service): resolve via the
    schema's connection_string_env indirection — an env var *name*, read
    here, not a literal connection string on the schema object."""
    svc = _Service(connection_string_env="MY_DB_URL")
    with mock.patch.dict(os.environ, {"MY_DB_URL": "postgresql://byo"}, clear=True):
        assert _resolve_connection_string(svc, "SESSION_STORE_URL") == "postgresql://byo"


def test_resolve_returns_none_when_nothing_set():
    svc = _Service()
    with mock.patch.dict(os.environ, {}, clear=True):
        assert _resolve_connection_string(svc, "SESSION_STORE_URL") is None


def test_resolve_ignores_nonexistent_connection_string_attribute():
    """Guards the exact regression: a plain object with no
    connection_string_env at all (e.g. legacy fixtures using the old,
    nonexistent `connection_string` attribute) must not raise."""

    class _Bare:
        engine = "postgres"

    with mock.patch.dict(os.environ, {}, clear=True):
        assert _resolve_connection_string(_Bare(), "SESSION_STORE_URL") is None


# --- build_checkpointer(sessions=postgres) -------------------------------


def test_build_checkpointer_postgres_uses_injected_session_store_url():
    captured = {}

    class _FakeSaver:
        @staticmethod
        def from_conn_string(conn):
            captured["conn"] = conn
            return "fake-cm"

    sessions = _Service(engine="postgres")
    env = {"SESSION_STORE_URL": "postgresql://from-provider"}
    with (
        mock.patch.dict(os.environ, env, clear=True),
        mock.patch("langgraph.checkpoint.postgres.aio.AsyncPostgresSaver", _FakeSaver),
    ):
        cp = build_checkpointer(_Agent(sessions=sessions))
        cp.context_manager()

    assert captured["conn"] == "postgresql://from-provider"


def test_build_checkpointer_postgres_byo_connection_string_env():
    captured = {}

    class _FakeSaver:
        @staticmethod
        def from_conn_string(conn):
            captured["conn"] = conn
            return "fake-cm"

    sessions = _Service(engine="postgres", connection_string_env="EXTERNAL_PG_URL")
    with (
        mock.patch.dict(os.environ, {"EXTERNAL_PG_URL": "postgresql://byo"}, clear=True),
        mock.patch("langgraph.checkpoint.postgres.aio.AsyncPostgresSaver", _FakeSaver),
    ):
        cp = build_checkpointer(_Agent(sessions=sessions))
        cp.context_manager()

    assert captured["conn"] == "postgresql://byo"


# --- build_memory_store(memory=postgres) ---------------------------------


def test_build_memory_store_postgres_uses_injected_memory_store_url():
    captured = {}

    class _FakeStore:
        @staticmethod
        def from_conn_string(conn):
            captured["conn"] = conn
            return "fake-cm"

    memory = _Service(engine="postgres")
    with (
        mock.patch.dict(os.environ, {"MEMORY_STORE_URL": "postgresql://from-provider"}, clear=True),
        mock.patch("langgraph.store.postgres.aio.AsyncPostgresStore", _FakeStore),
    ):
        store = build_memory_store(_Agent(memory=memory))
        store.context_manager()

    assert captured["conn"] == "postgresql://from-provider"
