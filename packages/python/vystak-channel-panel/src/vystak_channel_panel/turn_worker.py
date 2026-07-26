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
    infra_failure = False
    try:
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
            # Unexpected failure (e.g. a transient JetStream subscribe error) is
            # not the turn concluding — the agent's output may still be sitting
            # in JetStream. Don't persist a partial/empty row and don't clear
            # active_turn_id: leave the turn as-is so the panel's startup rescan
            # (_resume_active_turns) retries it instead of orphaning it forever.
            logger.exception("turn persister failed conv=%s turn=%s", conv_id, turn_id)
            infra_failure = True
        try:
            if not infra_failure:
                # Idempotent w.r.t. a crash between add_message and
                # clear_active_turn on a previous attempt: the startup rescan
                # (_resume_active_turns) replays this turn from JetStream seq
                # 0, and without this check would insert a second assistant
                # row. If one is already there, only the second half
                # (update_conversation/clear_active_turn) still needs to run.
                existing = await rt.panel_store.get_message_by_turn_id(conv_id, turn_id)
                if existing is None and (not errored or acc.has_output):
                    # Same rules as the HTTP path: a clean done always
                    # persists (even empty); an errored turn persists only
                    # what the user already saw.
                    await rt.panel_store.add_message(
                        conv_id,
                        "assistant",
                        acc.content,
                        response_id=response_id,
                        parts=acc.parts(),
                        turn_id=turn_id,
                    )
                if response_id:
                    await rt.panel_store.update_conversation(
                        conv_id, last_response_id=response_id
                    )
        except Exception:  # noqa: BLE001 — persister must reach the cleanup below
            # A store failure here (e.g. disk full) is symmetric with the
            # infra_failure branch above: the clean stream terminal already
            # happened, JetStream output is accounted for, but nothing durable
            # was written. Don't clear active_turn_id — leave the turn active
            # so the startup rescan retries the persist, this time skipping
            # the insert via get_message_by_turn_id if it partially landed.
            logger.exception(
                "turn persister failed to persist conv=%s turn=%s", conv_id, turn_id
            )
            infra_failure = True
        else:
            # `else`, not `finally`: a CancelledError here isn't an
            # `Exception` subclass so the `except` above won't catch it —
            # with `finally` this would still run and wrongly clear the
            # active turn without knowing whether the write completed. On
            # any uncaught exception `else` is skipped, leaving
            # active_turn_id set for the rescan to retry, same as the
            # infra_failure paths above.
            if not infra_failure:
                await rt.panel_store.clear_active_turn(conv_id, turn_id)
    finally:
        rt.turn_tasks.pop(turn_id, None)
