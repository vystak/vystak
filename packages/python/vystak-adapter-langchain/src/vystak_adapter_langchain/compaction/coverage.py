"""Stable message identification for the compaction read path."""

from __future__ import annotations

from langchain_core.messages import BaseMessage

_KEY = "vystak_msg_id"


def message_id(msg: BaseMessage) -> str | None:
    """Return our stable id if assigned; otherwise the LangGraph-internal id."""
    vmid = (msg.additional_kwargs or {}).get(_KEY)
    if vmid:
        return vmid
    return getattr(msg, "id", None)


def assign_vystak_msg_id(
    messages: list[BaseMessage], *, thread_id: str, start: int
) -> int:
    """Stamp `vystak_msg_id` on messages that don't already carry one.

    Returns the next free counter value.
    """
    counter = start
    for msg in messages:
        kwargs = msg.additional_kwargs if msg.additional_kwargs is not None else {}
        if kwargs.get(_KEY):
            continue
        kwargs[_KEY] = f"{thread_id}:{counter}"
        msg.additional_kwargs = kwargs
        counter += 1
    return counter


def fraction_covered(messages: list[BaseMessage], *, up_to: str) -> float:
    """Fraction of `messages` with id ≤ up_to.

    Returns 0.0 if the up_to id never appears in the list.
    """
    if not messages:
        return 0.0
    seen_target = False
    covered = 0
    for msg in messages:
        mid = message_id(msg)
        covered += 1
        if mid == up_to:
            seen_target = True
            break
    if not seen_target:
        return 0.0
    return covered / len(messages)
