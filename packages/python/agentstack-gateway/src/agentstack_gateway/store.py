"""Registration store — persists agent registrations across gateway restarts."""

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path


class RegistrationStore(ABC):
    """Abstract store for agent registrations."""

    @abstractmethod
    async def save(self, agent_name: str, data: dict) -> None: ...

    @abstractmethod
    async def delete(self, agent_name: str) -> None: ...

    @abstractmethod
    async def list_all(self) -> dict[str, dict]: ...

    @abstractmethod
    async def setup(self) -> None: ...


class SqliteRegistrationStore(RegistrationStore):
    """SQLite-backed registration store."""

    def __init__(self, db_path: str = "/data/registrations.db"):
        self._db_path = db_path
        self._conn = None

    async def setup(self) -> None:
        import aiosqlite
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS registrations "
            "(agent_name TEXT PRIMARY KEY, data TEXT)"
        )
        await self._conn.commit()

    async def save(self, agent_name: str, data: dict) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO registrations (agent_name, data) VALUES (?, ?)",
            (agent_name, json.dumps(data)),
        )
        await self._conn.commit()

    async def delete(self, agent_name: str) -> None:
        await self._conn.execute(
            "DELETE FROM registrations WHERE agent_name = ?", (agent_name,)
        )
        await self._conn.commit()

    async def list_all(self) -> dict[str, dict]:
        cursor = await self._conn.execute("SELECT agent_name, data FROM registrations")
        rows = await cursor.fetchall()
        return {row[0]: json.loads(row[1]) for row in rows}


class PostgresRegistrationStore(RegistrationStore):
    """Postgres-backed registration store."""

    def __init__(self, conn_string: str):
        self._conn_string = conn_string
        self._pool = None

    async def setup(self) -> None:
        import asyncpg
        self._pool = await asyncpg.create_pool(self._conn_string)
        async with self._pool.acquire() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS registrations "
                "(agent_name TEXT PRIMARY KEY, data JSONB)"
            )

    async def save(self, agent_name: str, data: dict) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO registrations (agent_name, data) VALUES ($1, $2) "
                "ON CONFLICT (agent_name) DO UPDATE SET data = $2",
                agent_name, json.dumps(data),
            )

    async def delete(self, agent_name: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM registrations WHERE agent_name = $1", agent_name
            )

    async def list_all(self) -> dict[str, dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT agent_name, data FROM registrations")
            return {row["agent_name"]: json.loads(row["data"]) for row in rows}


class MemoryRegistrationStore(RegistrationStore):
    """In-memory store (no persistence). For testing or when no storage is configured."""

    def __init__(self):
        self._data: dict[str, dict] = {}

    async def setup(self) -> None:
        pass

    async def save(self, agent_name: str, data: dict) -> None:
        self._data[agent_name] = data

    async def delete(self, agent_name: str) -> None:
        self._data.pop(agent_name, None)

    async def list_all(self) -> dict[str, dict]:
        return dict(self._data)


def create_store() -> RegistrationStore:
    """Create a registration store based on environment config."""
    store_url = os.environ.get("REGISTRATION_STORE_URL", "")

    if store_url.startswith("postgresql://") or store_url.startswith("postgres://"):
        return PostgresRegistrationStore(store_url)

    if store_url.startswith("sqlite://") or store_url.endswith(".db"):
        db_path = store_url.replace("sqlite://", "") if store_url.startswith("sqlite://") else store_url
        return SqliteRegistrationStore(db_path)

    if store_url:
        # Assume postgres if it looks like a connection string
        return PostgresRegistrationStore(store_url)

    # Default: in-memory
    return MemoryRegistrationStore()
