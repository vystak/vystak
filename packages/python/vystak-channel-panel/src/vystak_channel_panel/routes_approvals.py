"""Approval-decision route — resolves a parked HITL tool-approval turn.

Split out of routes_messages.py: the resume path (NATS `resume_detached` vs
the HTTP checkpoint/resume dance) is a separate concern from the streaming
POST/GET routes there, and keeping it here matches those files' size.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from vystak_channel_panel.models import PanelUser
from vystak_channel_panel.responses_client import PanelStreamEvent, agent_base_url
from vystak_channel_panel.routes_conversations import require_conversation_access
from vystak_channel_panel.routes_messages import detect_park
from vystak_channel_panel.turn_stream import TurnAccumulator

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime

logger = logging.getLogger("vystak.channel.panel.approvals")


class ApprovalIn(BaseModel):
    turn_id: str
    approved: bool
    note: str | None = None


def build_approvals_router(rt: PanelChannelRuntime, current_user) -> APIRouter:
    router = APIRouter(prefix="/api/conversations")

    @router.post("/{conv_id}/approval")
    async def post_approval(
        conv_id: str, body: ApprovalIn, user: PanelUser = Depends(current_user)
    ) -> dict:
        conv = await require_conversation_access(rt, conv_id, user)
        if conv.active_turn_id != body.turn_id:
            raise HTTPException(
                status_code=422,
                detail="turn is not this conversation's active turn",
            )
        decision = {
            "approved": body.approved,
            "decided_by": user.email,
            "note": body.note,
        }
        if rt.nats_client is not None:
            try:
                await rt.nats_client.resume_detached(
                    conv.agent_name, body.turn_id, decision
                )
            except TimeoutError as e:
                # Distinct from "already resolved" (RuntimeError below): the
                # broker call itself didn't complete, so the turn's real
                # state is unknown — leave it parked, let the caller retry.
                raise HTTPException(status_code=503, detail=str(e)) from e
            except RuntimeError as e:
                raise HTTPException(status_code=409, detail=str(e)) from e
            return {"ok": True}

        # In-flight guard (first-decision-wins): claim `rt.turn_tasks[turn_id]`
        # in the SAME synchronous block as the membership check, with no
        # `await` anywhere in between — asyncio only switches coroutines at
        # an `await`, so this check-then-claim is atomic no matter how two
        # concurrent POSTs for the same turn interleave everywhere else.
        # Claiming immediately (before connecting to the agent) matters:
        # connecting is itself an `await`, and claiming only *after* it
        # would reopen exactly this race for two POSTs that both start
        # connecting before either registers.
        turn_id = body.turn_id
        if turn_id in rt.turn_tasks:
            raise HTTPException(status_code=409, detail="resume already in progress")
        route_entry = rt.routes.get(conv.agent_name)
        if route_entry is None:
            raise HTTPException(
                status_code=503, detail=f"agent not routed: {conv.agent_name}"
            )
        base_url = agent_base_url(route_entry)
        thread_id = conv.last_response_id or ""
        loop = asyncio.get_running_loop()
        first_event: asyncio.Future[PanelStreamEvent | None] = loop.create_future()
        task = asyncio.create_task(
            _run_resume_http(
                rt, conv_id, turn_id, base_url, thread_id, decision, first_event
            )
        )
        rt.turn_tasks[turn_id] = task

        # Connecting to the agent and reading its first event happens
        # inside the task (so the claim above stays atomic); wait for that
        # outcome here so a connect failure or a translated `error` event
        # becomes a real HTTP failure instead of a silent 200. The task's
        # own `finally` owns popping `rt.turn_tasks` in every case,
        # including this one — nothing here needs to undo the claim.
        try:
            ev = await first_event
        except Exception as exc:  # noqa: BLE001 — surfaced as a 502 below
            raise HTTPException(
                status_code=502, detail=f"agent unreachable: {exc}"
            ) from exc
        if ev is not None and ev.type == "error":
            raise HTTPException(status_code=502, detail=ev.text)

        return {"ok": True}

    return router


async def _run_resume_http(
    rt: PanelChannelRuntime,
    conv_id: str,
    turn_id: str,
    base_url: str,
    thread_id: str,
    decision: dict,
    first_event: asyncio.Future[PanelStreamEvent | None],
) -> None:
    """POST /v1/_vystak/resume and consume its SSE end to end.

    Reports its first event (or connection failure) through *first_event*
    so the route can turn a dead-on-arrival resume into a real HTTP error
    response before returning — the route awaits that future and then gets
    out of the way; everything past the first event runs here, in the
    background, exactly like `post_message`'s persist pattern for
    done/error/truncated-stream (single `persist()` closure, same set of
    branches).

    `active_turn_id` is cleared ONLY on a confirmed successful completion
    (a `done` event, persisted) — spec Task 9 fix-round §8: an unreachable
    agent, a mid-stream error, or an exception here must leave the turn
    parked so the approval route's `active_turn_id` check still lets the
    user retry the same `turn_id`, rather than 422ing forever against a
    turn the panel silently gave up on.

    A stream that ends with no terminal event is probed the same way
    `post_message`'s HTTP branch probes a fresh turn (`detect_park`) — the
    resumed run can park AGAIN on a second gated tool, and that must
    persist a new pending-approval part and stay parked, not read as a
    successful (but empty) completion.
    """
    acc = TurnAccumulator()
    gen = rt.responses_client.resume_stream(base_url, thread_id, decision)

    async def persist(response_id: str | None, *, turn_id: str | None = None):
        return await rt.panel_store.add_message(
            conv_id, "assistant", acc.content,
            response_id=response_id,
            parts=acc.parts(),
            turn_id=turn_id,
        )

    try:
        try:
            first_ev = await gen.__anext__()
        except StopAsyncIteration:
            first_ev = None
        except Exception as exc:  # noqa: BLE001 — reported via the future
            if not first_event.done():
                first_event.set_exception(exc)
            return

        if not first_event.done():
            first_event.set_result(first_ev)

        if first_ev is not None and first_ev.type == "error":
            # Already reported to the route as a 502 above; nothing was
            # accumulated yet, so there's nothing to persist.
            return

        async def _all_events():
            if first_ev is not None:
                yield first_ev
            async for ev in gen:
                yield ev

        terminal_ev: PanelStreamEvent | None = None
        async for ev in _all_events():
            if ev.type in ("token", "tool_call", "tool_result"):
                acc.feed(ev)
            elif ev.type in ("done", "error"):
                terminal_ev = ev
                break

        if terminal_ev is not None and terminal_ev.type == "done":
            await persist(terminal_ev.response_id or None)
            if terminal_ev.response_id:
                await rt.panel_store.update_conversation(
                    conv_id, last_response_id=terminal_ev.response_id
                )
            await _resolve_pending_part(rt, conv_id, turn_id)
            await rt.panel_store.clear_active_turn(conv_id, turn_id)
            return

        if terminal_ev is not None and terminal_ev.type == "error":
            # Resume failed mid-stream — leave active_turn_id set (see
            # docstring); persist whatever text/tool activity did complete
            # so it isn't lost on the next reload.
            if acc.has_output:
                await persist(None)
            return

        # No terminal event at all: either a genuine truncated stream, or
        # the resumed run parked again on another gated tool.
        checkpoint = await detect_park(rt, base_url, thread_id)
        if checkpoint:
            interrupts = checkpoint.get("interrupts") or []
            approval_ev = PanelStreamEvent(
                type="approval_requested",
                approval=(interrupts[0] if interrupts else {}),
            )
            acc.feed(approval_ev)
            await persist(None, turn_id=turn_id)
            # Same thread, same turn_id — still parked, so active_turn_id
            # is intentionally left as-is (not cleared, not re-set).
            return

        if acc.has_output:
            await persist(None)
        # Inconclusive, not a confirmed success — active_turn_id stays set.
    except Exception as exc:  # noqa: BLE001 — background task must not raise
        logger.exception("resume_http failed conv=%s", conv_id)
        if not first_event.done():
            first_event.set_exception(exc)
        if acc.has_output:
            try:
                await persist(None)
            except Exception:  # noqa: BLE001 — last line of defence
                logger.exception(
                    "failed to persist partial resume text for conv=%s",
                    conv_id,
                )
        # active_turn_id stays set — see docstring.
    finally:
        # Isolated from every store call above (which can itself raise) so
        # this always runs — a dead task must never linger in
        # rt.turn_tasks and permanently block the in-flight guard above.
        rt.turn_tasks.pop(turn_id, None)
        if not first_event.done():
            # Only reachable if something above raised before either
            # __anext__ branch got to set the future — a cancelled future
            # still resolves the route's `await first_event` (with
            # CancelledError) instead of hanging it forever.
            first_event.cancel()
        # Every path above either breaks out of `_all_events()` (the
        # `done`/`error`-terminal happy paths) or returns early — `gen` is
        # left suspended either way, never naturally exhausted. Closing it
        # explicitly (rather than abandoning it to asyncgen finalization)
        # matters because the production ResponsesClient owns its own
        # httpx.AsyncClient per call (`runtime.py` constructs it with no
        # injected client) and only tears it down in _stream_sse's own
        # `finally` — abandoning `gen` would defer that indefinitely.
        # aclose() on an already-exhausted generator is a no-op; on a
        # suspended one it raises GeneratorExit into _stream_sse, which
        # already handles that explicitly (the same machinery
        # test_aclose_during_abandonment_does_not_raise pins).
        try:
            await gen.aclose()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            logger.exception("failed to close resume stream conv=%s", conv_id)


async def _resolve_pending_part(
    rt: PanelChannelRuntime, conv_id: str, turn_id: str | None
) -> None:
    """Flip the parked message's persisted `approval-requested` part to
    `resolved` once its resume completes successfully, so a reload doesn't
    render a live approve/reject control for a decision that's already
    been made (clicking it would just 422)."""
    if turn_id is None:
        return
    pending = await rt.panel_store.get_message_by_turn_id(conv_id, turn_id)
    if pending is None or not pending.parts:
        return
    updated = [
        {**p, "state": "resolved"}
        if p.get("type") == "tool" and p.get("state") == "approval-requested"
        else p
        for p in pending.parts
    ]
    if updated != pending.parts:
        await rt.panel_store.update_message_parts(pending.id, updated)
