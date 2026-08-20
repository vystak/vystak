"""Shared turn-stream machinery: Responses-event translation, accumulation,
and browser-frame shapes. Used by both the HTTP proxy path and the NATS
JetStream path so the two can never drift."""

from __future__ import annotations

import json

from vystak_channel_panel.responses_client import PanelStreamEvent


def translate_responses_event(
    data: dict, pending_calls: dict[str, dict]
) -> PanelStreamEvent | None:
    event_type = data.get("type", "")
    if event_type == "response.output_text.delta":
        return PanelStreamEvent(type="token", text=data.get("delta", ""))
    if event_type == "response.output_item.added":
        item = data.get("item") or {}
        item_type = item.get("type")
        if item_type == "function_call":
            call_id = item.get("call_id") or item.get("id") or ""
            if call_id:
                pending_calls[call_id] = {
                    "tool_name": item.get("name", ""),
                    "arguments": "",
                }
            return None
        if item_type == "function_call_output":
            return PanelStreamEvent(
                type="tool_result",
                tool_call_id=item.get("call_id", ""),
                output=item.get("output", ""),
                is_error=bool(item.get("error", False)),
            )
        return None
    if event_type == "response.function_call_arguments.delta":
        pending = pending_calls.get(data.get("call_id", ""))
        if pending is not None:
            pending["arguments"] += data.get("delta", "")
        return None
    if event_type == "response.function_call_arguments.done":
        call_id = data.get("call_id", "")
        pending = pending_calls.pop(call_id, None)
        if pending is not None:
            tool_name = pending["tool_name"]
            arguments = pending["arguments"]
        else:
            # No matching output_item.added was seen for this call_id —
            # fall back to whatever this event itself carries rather than
            # dropping the tool call entirely.
            tool_name = ""
            arguments = data.get("arguments", "")
        return PanelStreamEvent(
            type="tool_call",
            tool_call_id=call_id,
            tool_name=tool_name,
            arguments=arguments,
        )
    if event_type == "response.completed":
        return PanelStreamEvent(
            type="done", response_id=data.get("response", {}).get("id", "")
        )
    if event_type == "response.failed":
        err = (
            data.get("response", {}).get("error", {})
            .get("message", "agent stream failed")
        )
        return PanelStreamEvent(type="error", text=err)
    if event_type == "vystak.turn.rewind":
        return PanelStreamEvent(type="rewind", to_seq=int(data.get("to_seq", -1)))
    if event_type == "vystak.approval.requested":
        return PanelStreamEvent(
            type="approval_requested", approval=data.get("payload") or {}
        )
    return None


def _approval_call_id(ev: PanelStreamEvent) -> str:
    # Deterministic id — one pending approval per park in v1.
    return f"approval:{ev.approval.get('tool', '')}"


class TurnAccumulator:
    """Accumulates one turn's events into (content, parts) for persistence.

    `text_chunks` is every text token seen, in order — it becomes `content`,
    the flattened-text source of truth, unaffected by tool events.
    `_current_text` is the still-open text segment; `msg_parts` is the
    ordered, persisted rendering of the turn (text segments interleaved with
    completed tool calls) — a tool that ran between two bursts of text must
    end up between them, so a tool_call flushes whatever text segment is
    open before it.

    `_pending_tool_calls` is keyed by tool_call_id: the tool_call event's
    name + arguments, held until the matching tool_result arrives so both
    sides of the call land in one `parts` entry. A call that never gets a
    matching tool_result (stream errors/drops mid-call) is deliberately
    dropped from `parts` rather than persisted half-finished — Task 5 hasn't
    defined a shape for that state.
    """

    def __init__(self) -> None:
        self.text_chunks: list[str] = []
        self._current_text: list[str] = []
        self.msg_parts: list[dict] = []
        self._pending_tool_calls: dict[str, dict] = {}
        self._log: list[tuple[int, PanelStreamEvent]] = []

    def feed(self, ev: PanelStreamEvent) -> None:
        if ev.type == "token":
            self.text_chunks.append(ev.text)
            self._current_text.append(ev.text)
        elif ev.type == "tool_call":
            self._flush_text()
            # A stale, never-resolved pending call for the same tool name
            # (the pre-park attempt, whose matching tool_result never
            # arrived on this stream) would otherwise sit in the pending
            # map forever — drop it so it can't be confused with the new
            # in-flight call.
            for stale_id in [
                cid for cid, call in self._pending_tool_calls.items()
                if call["tool_name"] == ev.tool_name
            ]:
                self._pending_tool_calls.pop(stale_id, None)
            self._pending_tool_calls[ev.tool_call_id] = {
                "tool_name": ev.tool_name,
                "arguments": ev.arguments,
            }
            # A resolved tool_call/tool_result pair for the same tool name
            # supersedes any pending approval-requested part left over from
            # the park — drop it so the transcript shows one entry.
            self.msg_parts = [
                p for p in self.msg_parts
                if not (
                    p.get("type") == "tool"
                    and p.get("state") == "approval-requested"
                    and p.get("tool_name") == ev.tool_name
                )
            ]
        elif ev.type == "approval_requested":
            self._flush_text()
            tool_name = ev.approval.get("tool", "")
            # The tool part immediately preceding this park (if any, same
            # tool name) is the pre-park attempt that got interrupted
            # mid-execution: LangChain's callback layer sees the raised
            # GraphInterrupt like any other tool exception and the runtime
            # turns it into a resolved, is_error tool part for the SAME
            # tool_name before the graph-level park is detected and this
            # approval_requested event is synthesized. It never gets a real
            # result and would otherwise sit alongside the approval card
            # (and later the real result) as a phantom "completed" entry —
            # drop it now, superseded by the pending approval part. Gated on
            # is_error too: a DENIED gated tool also produces a resolved,
            # same-tool-name part, but with is_error False (`_denied_result`
            # returns normally) — that's a legitimate transcript entry, not
            # an interrupt artifact, and must survive if the LLM retries the
            # same tool later in the turn and parks again.
            if (
                self.msg_parts
                and self.msg_parts[-1].get("type") == "tool"
                and self.msg_parts[-1].get("tool_name") == tool_name
                and self.msg_parts[-1].get("state") != "approval-requested"
                and self.msg_parts[-1].get("is_error")
            ):
                self.msg_parts.pop()
            self.msg_parts.append({
                "type": "tool",
                "state": "approval-requested",
                "tool_call_id": _approval_call_id(ev),
                "tool_name": tool_name,
                "input": json.dumps(ev.approval.get("args", {})),
                "output": "",
                "is_error": False,
            })
        elif ev.type == "tool_result":
            call = self._pending_tool_calls.pop(ev.tool_call_id, None)
            self.msg_parts.append({
                "type": "tool",
                "tool_call_id": ev.tool_call_id,
                "tool_name": call["tool_name"] if call else "",
                "input": call["arguments"] if call else "",
                "output": ev.output,
                "is_error": ev.is_error,
            })

    def _flush_text(self) -> None:
        if self._current_text:
            self.msg_parts.append({"type": "text", "text": "".join(self._current_text)})
            self._current_text.clear()

    def feed_seq(self, seq: int, ev: PanelStreamEvent) -> None:
        """Feed an event with a sequence number, logging it for potential rewind."""
        self._log.append((seq, ev))
        self.feed(ev)

    def retained(self) -> list[tuple[int, PanelStreamEvent]]:
        """Return the list of all retained (seq, event) pairs."""
        return list(self._log)

    def rewind(self, to_seq: int) -> None:
        """Discard events above `to_seq` (inclusive of `to_seq` itself) and
        re-fold. A resumed run re-emits exactly these, so keeping them would
        duplicate output."""
        survivors = [(s, e) for s, e in self._log if s <= to_seq]
        self.text_chunks.clear()
        self._current_text.clear()
        self.msg_parts.clear()
        self._pending_tool_calls.clear()
        self._log = []
        for s, e in survivors:
            self.feed_seq(s, e)

    @property
    def content(self) -> str:
        return "".join(self.text_chunks)

    def parts(self) -> list[dict] | None:
        self._flush_text()
        return self.msg_parts or None

    @property
    def has_output(self) -> bool:
        return bool(self.text_chunks or self.msg_parts or self._current_text)


def browser_frame(ev: PanelStreamEvent) -> dict:
    """The panel→browser SSE payload for one streaming event."""
    if ev.type == "token":
        return {"type": "delta", "text": ev.text}
    if ev.type == "rewind":
        return {"type": "reset"}
    if ev.type == "tool_call":
        return {
            "type": "tool_call",
            "tool_call_id": ev.tool_call_id,
            "tool_name": ev.tool_name,
            "arguments": ev.arguments,
        }
    if ev.type == "tool_result":
        return {
            "type": "tool_result",
            "tool_call_id": ev.tool_call_id,
            "output": ev.output,
            "is_error": ev.is_error,
        }
    if ev.type == "approval_requested":
        return {
            "type": "approval",
            "tool_call_id": _approval_call_id(ev),
            "tool_name": ev.approval.get("tool", ""),
            "input": ev.approval.get("args", {}),
        }
    return {"type": "error", "message": ev.text}
