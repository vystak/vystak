"""Opt-in TTL cache for idempotency keys.

When a client supplies an `idempotency_key` in an A2A message's metadata,
the callee-side handler can check this cache before dispatching the
underlying work. A hit returns the previously-computed result without
re-running the agent; a miss runs the work and stores the result for the
TTL.

This is **client-driven** (the caller must supply the key). No key = no
dedup; behaviour is identical to pre-idempotency code paths. Default TTL
is 60 seconds — long enough to catch retries on a timed-out request,
short enough that memory pressure stays bounded on a busy agent.

This is a v0 implementation:
- In-process memory only; survives process lifetime, not restarts.
- No coordination across replicas (queue groups deliver to one replica,
  so a retry that lands on a different replica is a miss — acceptable for
  v0 since queue-group load balancing is stateless by design).
- Backed by a plain dict + asyncio.Lock; no LRU eviction beyond expiry.

A production-grade v1 would back this with the agent's session store
(Postgres/SQLite) so replicas and restarts see a shared view.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

logger = logging.getLogger("vystak.transport.idempotency")

T = TypeVar("T")

DEFAULT_TTL_SECONDS = 60.0


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: float


class IdempotencyCache(Generic[T]):
    """Thread-unsafe TTL cache keyed by idempotency_key.

    Intended for use inside a single asyncio event loop; no locking needed
    because `get` and `put` complete synchronously and the event loop
    serialises access between coroutines.
    """

    def __init__(self, *, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, _Entry[T]] = {}

    def get(self, key: str) -> T | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() >= entry.expires_at:
            self._store.pop(key, None)
            logger.debug("idempotency.miss key=%s (expired)", key)
            return None
        logger.info("idempotency.hit key=%s", key)
        return entry.value

    def put(self, key: str, value: T) -> None:
        self._store[key] = _Entry(
            value=value,
            expires_at=time.monotonic() + self._ttl,
        )
        logger.debug("idempotency.put key=%s ttl=%.0fs", key, self._ttl)
        # Opportunistic cleanup: on every put, sweep one expired entry if
        # the store is larger than 1024 keys. Bounded work per put.
        if len(self._store) > 1024:
            now = time.monotonic()
            expired = next(
                (k for k, e in self._store.items() if now >= e.expires_at),
                None,
            )
            if expired is not None:
                self._store.pop(expired, None)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


def extract_idempotency_key(metadata: dict[str, Any]) -> str | None:
    """Pull an idempotency_key from a message's metadata.

    Looks for the key under two common names (`idempotency_key` and
    `idempotencyKey` for OpenAI-style camelCase). Returns None if neither
    is present or the value is not a non-empty string.
    """
    for name in ("idempotency_key", "idempotencyKey"):
        value = metadata.get(name)
        if isinstance(value, str) and value:
            return value
    return None
