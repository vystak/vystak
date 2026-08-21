"""Streaming client for an agent's OpenAI Responses API (/v1/responses)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Literal

import httpx
from pydantic import BaseModel


class PanelStreamEvent(BaseModel):
    type: Literal[
        "token", "done", "error", "tool_call", "tool_result", "rewind",
        "approval_requested",
    ]
    text: str = ""
    response_id: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    arguments: str = ""
    output: str = ""
    is_error: bool = False
    # Only set on `approval_requested` events — the raw payload from the
    # bridge's `vystak.approval.requested` JetStream event: {kind, tool,
    # args, skill}.
    approval: dict = {}
    # Only set on `rewind` events (Task 11 produces these) — the accumulator
    # seq to roll back to, so a resumed run's re-emitted events don't
    # duplicate what was already accumulated before a restart.
    to_seq: int = -1


def agent_base_url(route_entry: dict | str) -> str:
    """Resolve a routes.json entry to the agent's HTTP root.

    routes.json addresses point at the A2A endpoint
    (http://vystak-<agent>:8000/a2a); the Responses API lives at the root.
    """
    address = (
        route_entry.get("address", "") if isinstance(route_entry, dict)
        else route_entry
    )
    return address.rstrip("/").removesuffix("/a2a")


class ResponsesClient:
    """POST /v1/responses with stream=true; yields typed panel events.

    Session continuity is the Responses contract: pass the conversation's
    stored id as previous_response_id; the agent uses it as its LangGraph
    thread_id. An id unknown to the agent (e.g. after a redeploy with a
    fresh session store) starts an empty thread under the same id — it
    does not error.
    """

    def __init__(
        self,
        timeout_s: float = 300.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout = timeout_s
        self._http_client = http_client

    async def stream_message(
        self,
        base_url: str,
        text: str,
        *,
        previous_response_id: str | None,
        user_id: str | None = None,
        project_id: str | None = None,
        on_response_id: Callable[[str], None] | None = None,
    ) -> AsyncIterator[PanelStreamEvent]:
        """*on_response_id*, if given, is called with the id off the raw
        `response.created` event as soon as it's seen on the wire — before
        translation, so it costs `translate_responses_event` nothing (that
        event type still translates to `None`, same as always). Lets a
        caller learn the agent's freshly-minted thread id on a
        conversation's very first turn, when there is no
        `previous_response_id`/`last_response_id` yet to key a later
        checkpoint probe on (see routes_messages.py's `_detect_park`)."""
        body = {
            "model": "",
            "input": text,
            "previous_response_id": previous_response_id,
            "store": True,
            "stream": True,
            "user_id": user_id,
            "project_id": project_id,
        }
        async for ev in self._stream_sse(
            f"{base_url.rstrip('/')}/v1/responses", body,
            on_response_id=on_response_id,
        ):
            yield ev

    async def resume_stream(
        self, base_url: str, thread_id: str, resume: dict
    ) -> AsyncIterator[PanelStreamEvent]:
        """POST /v1/_vystak/resume {thread_id, resume} — same SSE shape and
        parsing as `stream_message`, used to consume a parked turn's
        continuation after an approval decision."""
        body = {"thread_id": thread_id, "resume": resume}
        async for ev in self._stream_sse(
            f"{base_url.rstrip('/')}/v1/_vystak/resume", body
        ):
            yield ev

    async def get_checkpoint(self, base_url: str, thread_id: str) -> dict:
        """GET /v1/_vystak/checkpoint?thread_id=... — the agent's current
        LangGraph checkpoint state for a thread: `{checkpoint_id,
        interrupted, interrupts: [payload...]}`."""
        client = self._http_client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._http_client is None
        try:
            resp = await client.get(
                f"{base_url.rstrip('/')}/v1/_vystak/checkpoint",
                params={"thread_id": thread_id},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if owns_client:
                await client.aclose()

    async def _stream_sse(
        self,
        url: str,
        body: dict,
        *,
        on_response_id: Callable[[str], None] | None = None,
    ) -> AsyncIterator[PanelStreamEvent]:
        """Shared SSE-consumption loop for `stream_message` and
        `resume_stream`: POST *body* to *url*, translate each Responses-API
        event into a `PanelStreamEvent`. Kept as one helper so the two paths
        can never drift on error handling or event translation."""
        client = self._http_client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._http_client is None
        closing = False
        # Keyed by call_id: holds the tool name from the `function_call`
        # output_item.added event and accumulates the arguments string from
        # each function_call_arguments.delta, so it is complete by the time
        # function_call_arguments.done yields the tool_call event.
        pending_calls: dict[str, dict] = {}
        # circular: turn_stream imports PanelStreamEvent from this module
        from vystak_channel_panel.turn_stream import translate_responses_event

        try:
            async with client.stream(
                "POST", url, json=body, timeout=self._timeout,
            ) as resp:
                try:
                    if resp.status_code != 200:
                        yield PanelStreamEvent(
                            type="error", text=f"agent returned {resp.status_code}"
                        )
                        return
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            return
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if (
                            on_response_id is not None
                            and data.get("type") == "response.created"
                        ):
                            rid = (data.get("response") or {}).get("id")
                            if rid:
                                on_response_id(rid)
                        ev = translate_responses_event(data, pending_calls)
                        if ev is not None:
                            yield ev
                except GeneratorExit:
                    # Consumer abandoned the stream (e.g. browser disconnect).
                    # Flag it so a close-time transport error below can't try
                    # to yield an error event while we're being closed.
                    closing = True
                    raise
        except httpx.HTTPError as exc:
            if closing:
                # __aexit__ raised while GeneratorExit was propagating; it
                # replaced GeneratorExit as the in-flight exception. Yielding
                # here would raise "async generator ignored GeneratorExit".
                return
            yield PanelStreamEvent(type="error", text=f"agent unreachable: {exc}")
        finally:
            if owns_client:
                await client.aclose()
