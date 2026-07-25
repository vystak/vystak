"""Process-owned turn persister — consumes a turn's JetStream subject and
writes the assistant row, independent of any browser connection."""

from __future__ import annotations

import logging
from typing import Any

from vystak_transport_nats.streams import TurnStreamIdle

from vystak_channel_panel.turn_stream import TurnAccumulator

logger = logging.getLogger("vystak.channel.panel.turns")


async def run_turn_persister(rt: Any, conv_id: str, turn_id: str, subject: str) -> None:
    acc = TurnAccumulator()
    response_id: str | None = None
    errored = False
    try:
        async for _seq, ev in rt.nats_client.stream_turn_events(subject):
            if ev.type == "done":
                response_id = ev.response_id or None
                break
            if ev.type == "error":
                errored = True
                break
            acc.feed(ev)
    except TurnStreamIdle:
        logger.warning("turn idle timeout conv=%s turn=%s", conv_id, turn_id)
        errored = True
    except Exception:  # noqa: BLE001 — persister must reach the cleanup below
        logger.exception("turn persister failed conv=%s turn=%s", conv_id, turn_id)
        errored = True
    try:
        # Same rules as the HTTP path: a clean done always persists (even
        # empty); an errored turn persists only what the user already saw.
        if not errored or acc.has_output:
            await rt.panel_store.add_message(
                conv_id,
                "assistant",
                acc.content,
                response_id=response_id,
                parts=acc.parts(),
                turn_id=turn_id,
            )
        if response_id:
            await rt.panel_store.update_conversation(conv_id, last_response_id=response_id)
    finally:
        await rt.panel_store.clear_active_turn(conv_id, turn_id)
        rt.turn_tasks.pop(turn_id, None)
