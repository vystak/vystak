"""Channel store: persist thread bindings + route prefs across channel types."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from vystak_channel_runtime.types import ThreadBinding


@runtime_checkable
class ChannelStore(Protocol):
    """Generic store for runtime channel state.

    All keys are namespaced by (channel_type, scope_id, thread_id).
    Scope id meaning is per-channel:
      slack:   team_id
      discord: f"{guild_id}/{channel_id}" (or "dm/{user_id}")
      chat:    session originator
    """

    async def get_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> str | None: ...

    async def set_thread_binding(
        self,
        channel_type: str,
        scope_id: str,
        thread_id: str,
        agent_name: str,
        user_id: str | None = None,
    ) -> None: ...

    async def delete_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> None: ...

    async def get_route_pref(
        self, channel_type: str, scope_id: str
    ) -> str | None: ...

    async def set_route_pref(
        self, channel_type: str, scope_id: str, agent_name: str
    ) -> None: ...

    async def delete_route_pref(
        self, channel_type: str, scope_id: str
    ) -> None: ...

    async def list_thread_bindings(
        self, channel_type: str, scope_id: str | None = None
    ) -> list[ThreadBinding]: ...

    async def close(self) -> None: ...


class MemoryChannelStore:
    """In-memory ChannelStore. Loses state on restart. Test default."""

    def __init__(self) -> None:
        self._threads: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._prefs: dict[tuple[str, str], str] = {}

    async def get_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> str | None:
        row = self._threads.get((channel_type, scope_id, thread_id))
        return row["agent_name"] if row else None

    async def set_thread_binding(
        self,
        channel_type: str,
        scope_id: str,
        thread_id: str,
        agent_name: str,
        user_id: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        existing = self._threads.get((channel_type, scope_id, thread_id))
        created = existing["created_at"] if existing else now
        self._threads[(channel_type, scope_id, thread_id)] = {
            "agent_name": agent_name,
            "user_id": user_id,
            "created_at": created,
            "updated_at": now,
        }

    async def delete_thread_binding(
        self, channel_type: str, scope_id: str, thread_id: str
    ) -> None:
        self._threads.pop((channel_type, scope_id, thread_id), None)

    async def get_route_pref(
        self, channel_type: str, scope_id: str
    ) -> str | None:
        return self._prefs.get((channel_type, scope_id))

    async def set_route_pref(
        self, channel_type: str, scope_id: str, agent_name: str
    ) -> None:
        self._prefs[(channel_type, scope_id)] = agent_name

    async def delete_route_pref(
        self, channel_type: str, scope_id: str
    ) -> None:
        self._prefs.pop((channel_type, scope_id), None)

    async def list_thread_bindings(
        self, channel_type: str, scope_id: str | None = None
    ) -> list[ThreadBinding]:
        out: list[ThreadBinding] = []
        for (ct, sid, tid), row in self._threads.items():
            if ct != channel_type:
                continue
            if scope_id is not None and sid != scope_id:
                continue
            out.append(
                ThreadBinding(
                    channel_type=ct,
                    scope_id=sid,
                    thread_id=tid,
                    agent_name=row["agent_name"],
                    user_id=row.get("user_id"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                )
            )
        return out

    async def close(self) -> None:
        self._threads.clear()
        self._prefs.clear()
