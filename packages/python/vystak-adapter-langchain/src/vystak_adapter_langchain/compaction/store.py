"""Compaction state store — postgres / sqlite / in-memory backends.

Single source of truth across all three layers (autonomous middleware,
threshold pre-call, manual /compact). Each row is a generation; the prompt
callable always reads the highest generation per thread_id.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class CompactionRow:
    thread_id: str
    generation: int
    summary_text: str
    up_to_message_id: str
    trigger: str  # 'autonomous' | 'threshold' | 'manual'
    summarizer_model: str
    input_tokens: int = 0
    output_tokens: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # noqa: UP017


class CompactionStore(ABC):
    """Backend-agnostic compaction store."""

    @abstractmethod
    async def write(
        self,
        *,
        thread_id: str,
        summary_text: str,
        up_to_message_id: str,
        trigger: str,
        summarizer_model: str,
        usage: dict,
    ) -> int:
        """Write a new generation; return the generation number."""

    @abstractmethod
    async def latest(self, thread_id: str) -> CompactionRow | None:
        """Return the highest-generation row for the thread, or None."""

    @abstractmethod
    async def list(self, thread_id: str) -> list[CompactionRow]:
        """Return all rows for the thread, generation-descending."""

    @abstractmethod
    async def get(self, thread_id: str, *, generation: int) -> CompactionRow | None:
        """Return the row for `(thread_id, generation)` or None."""


class InMemoryCompactionStore(CompactionStore):
    """Process-local store for MemorySaver-backed deployments."""

    def __init__(self) -> None:
        self._rows: dict[str, list[CompactionRow]] = {}

    async def write(
        self,
        *,
        thread_id: str,
        summary_text: str,
        up_to_message_id: str,
        trigger: str,
        summarizer_model: str,
        usage: dict,
    ) -> int:
        rows = self._rows.setdefault(thread_id, [])
        gen = len(rows) + 1
        rows.append(
            CompactionRow(
                thread_id=thread_id,
                generation=gen,
                summary_text=summary_text,
                up_to_message_id=up_to_message_id,
                trigger=trigger,
                summarizer_model=summarizer_model,
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            )
        )
        return gen

    async def latest(self, thread_id: str) -> CompactionRow | None:
        rows = self._rows.get(thread_id) or []
        return rows[-1] if rows else None

    async def list(self, thread_id: str) -> list[CompactionRow]:
        rows = self._rows.get(thread_id) or []
        return list(reversed(rows))

    async def get(self, thread_id: str, *, generation: int) -> CompactionRow | None:
        rows = self._rows.get(thread_id) or []
        for row in rows:
            if row.generation == generation:
                return row
        return None
