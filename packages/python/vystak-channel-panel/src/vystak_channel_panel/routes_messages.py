"""Streaming message route — the panel's core chat surface."""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from vystak_channel_panel.models import PanelUser
from vystak_channel_panel.responses_client import PanelStreamEvent, agent_base_url
from vystak_channel_panel.routes_conversations import require_conversation_access
from vystak_channel_panel.turn_stream import TurnAccumulator, browser_frame

if TYPE_CHECKING:
    from vystak_channel_panel.runtime import PanelChannelRuntime

logger = logging.getLogger("vystak.channel.panel.messages")

_TITLE_MAX = 60


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


class MessageIn(BaseModel):
    text: str


def build_messages_router(rt: PanelChannelRuntime, current_user) -> APIRouter:
    router = APIRouter(prefix="/api/conversations")

    @router.post("/{conv_id}/messages")
    async def post_message(
        conv_id: str, body: MessageIn, user: PanelUser = Depends(current_user)
    ) -> StreamingResponse:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="text required")
        conv = await require_conversation_access(rt, conv_id, user)
        route_entry = rt.routes.get(conv.agent_name)
        if route_entry is None:
            raise HTTPException(
                status_code=503, detail=f"agent not routed: {conv.agent_name}"
            )

        await rt.panel_store.add_message(conv_id, "user", text)
        title = conv.title
        if not title:
            title = text[:_TITLE_MAX]
            await rt.panel_store.update_conversation(conv_id, title=title)

        if rt.nats_client is not None:
            return await _post_message_nats(rt, conv, conv_id, text, user, title)
        base_url = agent_base_url(route_entry)

        async def gen():
            acc = TurnAccumulator()
            done_seen = False

            async def persist(response_id: str | None):
                # The single persistence path for every branch below (done,
                # error, truncated-stream, dropped-connection). They have
                # disagreed with each other before (discarding text on an
                # error event, then again on a dropped connection); routing
                # all four through one function makes that drift impossible
                # rather than relying on each branch to stay in sync by hand.
                return await rt.panel_store.add_message(
                    conv_id, "assistant", acc.content,
                    response_id=response_id,
                    parts=acc.parts(),
                )

            try:
                async for ev in rt.responses_client.stream_message(
                    base_url,
                    text,
                    previous_response_id=conv.last_response_id,
                    user_id=user.id,
                    project_id=conv.project_id,
                ):
                    if ev.type in ("token", "tool_call", "tool_result"):
                        acc.feed(ev)
                        yield _sse(browser_frame(ev))
                    elif ev.type == "done":
                        done_seen = True
                        msg = await persist(ev.response_id or None)
                        # An empty id means the agent's terminal event carried
                        # none; keep the previous one rather than clobbering it
                        # (COALESCE only guards NULL, and "" would silently
                        # start a new agent-side thread on the next turn).
                        if ev.response_id:
                            await rt.panel_store.update_conversation(
                                conv_id, last_response_id=ev.response_id
                            )
                        yield _sse({
                            "type": "done",
                            "message_id": msg.id,
                            "response_id": ev.response_id,
                            "title": title,
                        })
                    elif ev.type == "error":
                        done_seen = True
                        if acc.has_output:
                            # Same failure mode the truncated-stream branch
                            # below guards against: the user already watched
                            # this text (and any completed tool calls)
                            # stream in, so it must survive a reload even
                            # though the turn ended in error. No response_id
                            # — none was confirmed, and last_response_id is
                            # intentionally left untouched (the panel never
                            # replays history to the agent; it relies on
                            # previous_response_id).
                            await persist(None)
                        yield _sse(browser_frame(ev))
                if not done_seen:
                    # Stream ended with no terminal event. Either the turn
                    # parked mid-run (a HITL tool approval — Task 6/7) or the
                    # agent's `data: [DONE]` simply arrived with no preceding
                    # response.completed/failed. Ask the agent which one this
                    # is: a parked turn survives a `checkpoint_id`/interrupted
                    # state on its thread; anything else (including the
                    # checkpoint call itself failing) falls through to the
                    # truncated-stream handling below.
                    # KNOWN GAP: gated on last_response_id, which the agent
                    # uses as its LangGraph thread_id for turns 2+ (see
                    # responses_client.py's ResponsesClient docstring). On a
                    # conversation's very first turn there is no
                    # last_response_id yet (the agent mints a fresh thread id
                    # we never capture, since the panel only reads it off the
                    # `done` terminal event) — a first-turn park on the HTTP
                    # transport falls through to the truncated-stream branch
                    # below and is currently invisible to the browser. Fixing
                    # this would mean capturing `response.created`'s id
                    # without teaching `translate_responses_event` to emit a
                    # new frame for it (that would break the byte-exact
                    # `test_panel_sse_matches_cross_language_fixture` pin and
                    # add an unhandled event type to the NATS `_proxy_turn`).
                    checkpoint = None
                    if conv.last_response_id:
                        try:
                            checkpoint = await rt.responses_client.get_checkpoint(
                                base_url, conv.last_response_id
                            )
                        except Exception:  # noqa: BLE001 — best-effort probe
                            checkpoint = None
                    if checkpoint and checkpoint.get("interrupted"):
                        interrupts = checkpoint.get("interrupts") or []
                        approval_ev = PanelStreamEvent(
                            type="approval_requested",
                            approval=(interrupts[0] if interrupts else {}),
                        )
                        acc.feed(approval_ev)
                        await persist(None)
                        turn_id = conv.last_response_id
                        await rt.panel_store.set_active_turn(conv_id, turn_id)
                        frame = browser_frame(approval_ev)
                        frame["turn_id"] = turn_id
                        yield _sse(frame)
                    elif acc.has_output:
                        # Truncated agent stream: `data: [DONE]` arrived with
                        # no preceding response.completed/failed, so
                        # ResponsesClient yields no terminal event. Persist
                        # what we streamed — otherwise the user watches text
                        # (and any completed tool calls) appear and finds it
                        # gone on reload. last_response_id is left untouched:
                        # no new agent-side response id was confirmed.
                        msg = await persist(None)
                        yield _sse({
                            "type": "done",
                            "message_id": msg.id,
                            "response_id": conv.last_response_id or "",
                            "title": title,
                        })
            except Exception as exc:  # noqa: BLE001 — stream must not raise
                logger.exception("panel stream failed for conv=%s", conv_id)
                if acc.has_output:
                    # Same failure mode the `error` branch above guards
                    # against: the user already watched this text (and any
                    # completed tool calls) stream in, so it must survive a
                    # reload even though the connection dropped outright
                    # rather than surfacing an `error` event. No response_id
                    # — none was confirmed, and last_response_id is
                    # intentionally left untouched.
                    try:
                        await persist(None)
                    except Exception:  # noqa: BLE001 — last line of defence
                        logger.exception(
                            "failed to persist partial text for conv=%s",
                            conv_id,
                        )
                yield _sse({"type": "error", "message": str(exc)})

        return StreamingResponse(gen(), media_type="text/event-stream")

    @router.get("/{conv_id}/stream")
    async def resume_stream(conv_id: str, user: PanelUser = Depends(current_user)):
        conv = await require_conversation_access(rt, conv_id, user)
        if rt.nats_client is None or not conv.active_turn_id:
            return Response(status_code=204)
        route_entry = rt.routes.get(conv.agent_name)
        if route_entry is None:
            raise HTTPException(
                status_code=503, detail=f"agent not routed: {conv.agent_name}"
            )
        subject = rt.nats_client.turn_subject_for(
            route_entry, conv.id, conv.active_turn_id
        )
        gen = _proxy_turn(rt, subject, conv.active_turn_id, conv.title)
        return StreamingResponse(gen, media_type="text/event-stream")

    return router


async def _post_message_nats(rt, conv, conv_id: str, text: str, user, title: str):
    """The NATS-transport POST path: start a detached turn on the agent's
    JetStream subject and proxy it back as SSE. Persistence for this turn is
    owned entirely by the background persister (`rt.spawn_persister`), not by
    this request — any number of browser tabs can attach/detach from the
    same turn via this route or the GET resume endpoint without duplicating
    writes."""
    route_entry = rt.routes.get(conv.agent_name)
    turn_id = uuid.uuid4().hex
    await rt.panel_store.set_active_turn(conv_id, turn_id)
    try:
        subject = await rt.nats_client.start_turn(
            route_entry, text,
            conv_id=conv_id, turn_id=turn_id,
            previous_response_id=conv.last_response_id,
            user_id=user.id, project_id=conv.project_id,
        )
    except Exception as exc:  # noqa: BLE001 — surface as an SSE error frame
        logger.exception("createDetached failed conv=%s", conv_id)
        await rt.panel_store.clear_active_turn(conv_id, turn_id)
        # `exc` is bound by `except ... as exc` and Python implicitly deletes
        # it once this block exits. err_gen() only *creates* the generator
        # here — its body runs later, when the ASGI server iterates it,
        # after this function has already returned. A closure over `exc`
        # itself would hit a NameError at that point; capture the
        # message as a plain string instead.
        message = f"agent unreachable: {exc}"

        async def err_gen():
            yield _sse({"type": "error", "message": message})

        return StreamingResponse(err_gen(), media_type="text/event-stream")

    rt.spawn_persister(conv_id, turn_id, subject)
    gen = _proxy_turn(rt, subject, turn_id, title)
    return StreamingResponse(gen, media_type="text/event-stream")


async def _proxy_turn(rt, subject: str, turn_id: str, title: str | None):
    """Browser-facing SSE proxy over a turn's JetStream subject. Read-only:
    persistence belongs to the persister task, so any number of these can
    attach or vanish without consequence.

    Keeps a `TurnAccumulator` alongside the forwarding purely so a rewind
    event can replay: on `vystak.turn.rewind` the browser has already
    rendered events past the rollback point (a stale tool call, wrong text),
    so a bare forward isn't enough — the proxy must tell the browser to
    reset, then re-emit exactly the retained prefix so it rebuilds the
    committed state.
    """
    acc = TurnAccumulator()
    try:
        async for seq, ev in rt.nats_client.stream_turn_events(subject):
            if ev.type == "done":
                yield _sse({
                    "type": "done", "turn_id": turn_id, "seq": seq,
                    "response_id": ev.response_id, "title": title,
                })
                return
            if ev.type == "rewind":
                acc.rewind(ev.to_seq)
                reset_frame = browser_frame(ev)
                reset_frame["turn_id"] = turn_id
                reset_frame["seq"] = seq
                yield _sse(reset_frame)
                for kept_seq, kept in acc.retained():
                    kept_frame = browser_frame(kept)
                    kept_frame["turn_id"] = turn_id
                    kept_frame["seq"] = kept_seq
                    yield _sse(kept_frame)
                continue
            acc.feed_seq(seq, ev)
            frame = browser_frame(ev)
            frame["turn_id"] = turn_id
            frame["seq"] = seq
            yield _sse(frame)
            if ev.type == "error":
                return
    except Exception as exc:  # noqa: BLE001 — stream must not raise
        logger.exception("turn proxy failed subject=%s", subject)
        yield _sse({"type": "error", "message": str(exc), "turn_id": turn_id})
