"""HeartbeatSessionStore — abstract per-thread model selection store.

Concrete implementations (InMemoryStore, SqliteStore) land in Plan Task 9.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class HeartbeatSessionStore(ABC):
    @abstractmethod
    async def get_model(self, session_id: str) -> str | None: ...

    @abstractmethod
    async def set_model(self, session_id: str, model_name: str) -> None: ...

    async def close(self) -> None:
        return None


class InMemoryStore(HeartbeatSessionStore):
    """Minimal in-memory impl used until Task 9 fully populates this module."""

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    async def get_model(self, session_id: str) -> str | None:
        return self._d.get(session_id)

    async def set_model(self, session_id: str, model_name: str) -> None:
        self._d[session_id] = model_name
