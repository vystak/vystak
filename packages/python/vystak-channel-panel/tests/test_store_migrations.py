"""SqlitePanelStore — schema migrations.

`connect()` used to be `CREATE TABLE IF NOT EXISTS` only, so an existing
`/data` volume would silently never gain a new column. These tests build a
v1-shaped database by hand (the schema as it exists in the live deployment,
before `messages.parts` / `schema_version` existed) and prove `connect()`
migrates it in place without touching pre-existing data.
"""

import sqlite3

import pytest
from vystak_channel_panel.store import SqlitePanelStore

# Verbatim copy of the pre-migration schema (verified against the live
# `vystak-panel-state` volume's `sqlite_master.sql`) — deliberately NOT
# imported from store.py, since that module's _SCHEMA now includes `parts`.
_V1_SCHEMA = """
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deactivated')),
    created_at TEXT NOT NULL
);
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_projects_one_default
    ON projects (owner_id) WHERE is_default = 1;
CREATE TABLE project_members (
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    PRIMARY KEY (project_id, user_id)
);
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    creator_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    last_response_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    response_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_messages_conversation
    ON messages (conversation_id, created_at);
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _build_v1_db(path) -> None:
    """Hand-build a v1 database: old schema, no schema_version row, with a
    pre-existing user / conversation / message already in it."""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_V1_SCHEMA)
        conn.execute(
            "INSERT INTO users (id, email, name, image, role, status, created_at) "
            "VALUES ('u1', 'a@example.com', 'Ada', '', 'admin', 'active', 't0')"
        )
        conn.execute(
            "INSERT INTO projects (id, name, owner_id, is_default, created_at) "
            "VALUES ('p1', 'Personal', 'u1', 1, 't0')"
        )
        conn.execute(
            "INSERT INTO conversations "
            "(id, project_id, creator_id, agent_name, title, last_response_id, "
            " created_at, updated_at) "
            "VALUES ('c1', 'p1', 'u1', 'weather-agent', '', NULL, 't0', 't0')"
        )
        conn.execute(
            "INSERT INTO messages "
            "(id, conversation_id, role, content, response_id, created_at) "
            "VALUES ('m1', 'c1', 'user', 'hello there', NULL, 't0')"
        )
        conn.commit()
    finally:
        conn.close()


async def test_migrates_v1_database_in_place(tmp_path):
    db_path = tmp_path / "panel.db"
    _build_v1_db(db_path)

    store = SqlitePanelStore(db_path)
    await store.connect()
    try:
        # (a) parts column now exists
        async with store.db.execute("PRAGMA table_info(messages)") as cur:
            cols = {row["name"] async for row in cur}
        assert "parts" in cols

        # (b) pre-existing message still reads back intact, parts is None
        msgs = await store.list_messages("c1")
        assert len(msgs) == 1
        assert msgs[0].id == "m1"
        assert msgs[0].content == "hello there"
        assert msgs[0].parts is None

        # (c) schema_version is now 4
        version = await store.get_setting("schema_version")
        assert version == "4"
    finally:
        await store.close()

    # (d) a second connect() (fresh store, same file) is a clean no-op —
    # must not raise "duplicate column" or otherwise disturb the data.
    store2 = SqlitePanelStore(db_path)
    await store2.connect()
    try:
        version = await store2.get_setting("schema_version")
        assert version == "4"
        msgs = await store2.list_messages("c1")
        assert len(msgs) == 1
        assert msgs[0].content == "hello there"
        assert msgs[0].parts is None
    finally:
        await store2.close()


async def test_fresh_database_gets_schema_version_4(tmp_path):
    store = SqlitePanelStore(tmp_path / "panel.db")
    await store.connect()
    try:
        version = await store.get_setting("schema_version")
        assert version == "4"
    finally:
        await store.close()


async def test_migrates_v2_to_v3_adds_password_hash(tmp_path):
    """A v2 database (messages.parts present, users.password_hash absent,
    schema_version=2) gains the password_hash column without disturbing rows."""
    db_path = tmp_path / "panel.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        # v2 shape: users WITHOUT password_hash, messages WITH parts.
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL DEFAULT '', image TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );
        CREATE TABLE messages (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL,
            response_id TEXT, parts TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO settings (key, value) VALUES ('schema_version', '2');
        INSERT INTO users (id, email, role, created_at)
            VALUES ('u1', 'admin@example.com', 'admin', '2026-01-01T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    store = SqlitePanelStore(db_path)
    await store.connect()
    try:
        async with store.db.execute("PRAGMA table_info(users)") as cur:
            columns = {row["name"] async for row in cur}
        assert "password_hash" in columns
        assert await store.get_setting("schema_version") == "4"
        user = await store.get_user("u1")
        assert user is not None and user.email == "admin@example.com"
        assert user.has_password is False
        # Idempotent: reconnecting is a no-op.
        await store.close()
        store2 = SqlitePanelStore(db_path)
        await store2.connect()
        assert await store2.get_setting("schema_version") == "4"
        await store2.close()
    finally:
        await store.close()


@pytest.fixture
async def store(tmp_path):
    s = SqlitePanelStore(tmp_path / "panel.db")
    await s.connect()
    yield s
    await s.close()


async def test_add_message_with_parts_round_trips(store):
    user = await store.create_user("a@example.com", role="admin")
    proj = await store.create_project("P", user.id)
    conv = await store.create_conversation(proj.id, user.id, "weather-agent")

    parts = [
        {"type": "tool_call", "name": "get_weather", "args": {"city": "NYC"}},
        {"type": "tool_result", "output": "72F"},
    ]
    msg = await store.add_message(conv.id, "assistant", "It's 72F.", parts=parts)
    assert msg.parts == parts

    listed = await store.list_messages(conv.id)
    assert len(listed) == 1
    assert listed[0].content == "It's 72F."
    assert listed[0].parts == parts


async def test_add_message_without_parts_stays_none(store):
    user = await store.create_user("a@example.com", role="admin")
    proj = await store.create_project("P", user.id)
    conv = await store.create_conversation(proj.id, user.id, "weather-agent")

    msg = await store.add_message(conv.id, "user", "hi")
    assert msg.parts is None

    listed = await store.list_messages(conv.id)
    assert listed[0].parts is None


async def test_v4_adds_turn_columns(tmp_path):
    # Build a store, then simulate an existing v3 DB by dropping the new
    # columns is not possible in SQLite — instead assert a fresh connect()
    # yields the columns and schema_version == 4.
    store = SqlitePanelStore(tmp_path / "p.db")
    await store.connect()
    async with store.db.execute("PRAGMA table_info(conversations)") as cur:
        conv_cols = {row["name"] async for row in cur}
    async with store.db.execute("PRAGMA table_info(messages)") as cur:
        msg_cols = {row["name"] async for row in cur}
    assert "active_turn_id" in conv_cols
    assert "turn_id" in msg_cols
    assert await store.get_setting("schema_version") == "4"
    await store.close()


async def test_migrates_v3_to_v4_adds_turn_columns(tmp_path):
    """A v3 database (password_hash present, active_turn_id/turn_id absent,
    schema_version=3) gains the turn columns without disturbing rows."""
    db_path = tmp_path / "panel.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        # v3 shape: users WITH password_hash, messages WITH parts,
        # conversations/messages WITHOUT the v4 turn columns.
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL DEFAULT '', image TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            password_hash TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE projects (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, owner_id TEXT NOT NULL,
            is_default INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
            creator_id TEXT NOT NULL, agent_name TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '', last_response_id TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE messages (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL,
            response_id TEXT, parts TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO settings (key, value) VALUES ('schema_version', '3');
        INSERT INTO users (id, email, name, image, role, status, created_at)
            VALUES ('u1', 'admin@example.com', '', '', 'admin', 'active',
                    '2026-01-01T00:00:00+00:00');
        INSERT INTO projects (id, name, owner_id, is_default, created_at)
            VALUES ('p1', 'Personal', 'u1', 1, 't0');
        INSERT INTO conversations
            (id, project_id, creator_id, agent_name, title, last_response_id,
             created_at, updated_at)
            VALUES ('c1', 'p1', 'u1', 'weather-agent', '', NULL, 't0', 't0');
        """
    )
    conn.commit()
    conn.close()

    store = SqlitePanelStore(db_path)
    await store.connect()
    try:
        async with store.db.execute("PRAGMA table_info(conversations)") as cur:
            conv_cols = {row["name"] async for row in cur}
        async with store.db.execute("PRAGMA table_info(messages)") as cur:
            msg_cols = {row["name"] async for row in cur}
        assert "active_turn_id" in conv_cols
        assert "turn_id" in msg_cols
        assert await store.get_setting("schema_version") == "4"
        conv = await store.get_conversation("c1")
        assert conv is not None and conv.active_turn_id is None
        # Idempotent: reconnecting is a no-op.
        await store.close()
        store2 = SqlitePanelStore(db_path)
        await store2.connect()
        assert await store2.get_setting("schema_version") == "4"
        await store2.close()
    finally:
        await store.close()
