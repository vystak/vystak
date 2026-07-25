"""JetStream helpers for durable per-turn event streams.

Subject/naming convention — KEEP IN SYNC with the template runtime's copy in
vystak-template-langchain-python/_vystak/runtime/nats_bridge.py (the template
cannot import this package: agent images install vystak from PyPI only):

- tasks subject:  {prefix}.{ns}.agents.{name}.tasks
- stream base:    {prefix}.{ns}                  (everything before ".agents.")
- turn subject:   {base}.streams.{conversation_id}.{turn_id}
- stream name:    base with "." -> "-", plus "-streams"

Every message on a turn subject is ``{"seq": <int>, "event": <payload>}``
where ``event`` is one OpenAI Responses SSE payload. A turn is over when
``event.type`` is ``response.completed`` or ``response.failed``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import nats.errors
from nats.js.api import RetentionPolicy, StorageType, StreamConfig

DEFAULT_MAX_AGE_S = 3600.0
TERMINAL_EVENT_TYPES = frozenset({"response.completed", "response.failed"})


class TurnStreamIdle(TimeoutError):
    """No event arrived on a turn subject within the idle timeout."""


def stream_base(tasks_subject: str) -> str:
    base, sep, _ = tasks_subject.partition(".agents.")
    if not sep:
        raise ValueError(f"not a tasks subject: {tasks_subject!r}")
    return base


def stream_name_for_base(base: str) -> str:
    return base.replace(".", "-") + "-streams"


def turn_subject(base: str, conversation_id: str, turn_id: str) -> str:
    return f"{base}.streams.{conversation_id}.{turn_id}"


def is_terminal_event(payload: dict[str, Any]) -> bool:
    return (payload.get("event") or {}).get("type") in TERMINAL_EVENT_TYPES


async def ensure_stream(js: Any, base: str, *, max_age_s: float = DEFAULT_MAX_AGE_S) -> None:
    """Idempotently create (or converge) the turn-event stream for *base*."""
    cfg = StreamConfig(
        name=stream_name_for_base(base),
        subjects=[f"{base}.streams.>"],
        retention=RetentionPolicy.LIMITS,
        max_age=max_age_s,
        storage=StorageType.FILE,
    )
    try:
        await js.add_stream(cfg)
    except Exception:  # noqa: BLE001 — nats-py raises server-specific API errors
        # Stream already exists (possibly with an older subject list) —
        # converge via update instead.
        await js.update_stream(cfg)


async def read_turn_events(
    nc: Any, subject: str, *, idle_timeout_s: float = 120.0
) -> AsyncIterator[dict[str, Any]]:
    """Yield ``{"seq", "event"}`` payloads from seq 0 until a terminal event.

    Uses an ordered (ephemeral, deliver-all) JetStream consumer, so every
    caller independently replays the full turn. Raises :class:`TurnStreamIdle`
    when nothing arrives within *idle_timeout_s*.
    """
    js = nc.jetstream()
    sub = await js.subscribe(subject, ordered_consumer=True)
    try:
        while True:
            try:
                msg = await sub.next_msg(timeout=idle_timeout_s)
            except nats.errors.TimeoutError as e:
                raise TurnStreamIdle(subject) from e
            payload = json.loads(msg.data)
            yield payload
            if is_terminal_event(payload):
                return
    finally:
        await sub.unsubscribe()
