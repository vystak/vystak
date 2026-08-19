"""Stateful /v1/responses handler."""

import json
import time
import uuid
from typing import Any

from _vystak.runtime.content import flatten_content


class ResponsesHandler:
    """OpenAI Responses API — stateful via previous_response_id (LangGraph thread_id)."""

    def __init__(
        self,
        agent: Any,
        graph: Any,
        *,
        store: Any | None = None,
        observer: Any | None = None,
    ) -> None:
        self.agent = agent
        self.graph = graph
        self.store = store
        self._observer = observer

    async def create(self, body: dict) -> dict | Any:
        if body.get("stream"):
            return await self._create_stream(body)
        return await self._create_non_stream(body)

    async def _create_non_stream(self, body: dict) -> dict:
        thread_id = body.get("previous_response_id") or _new_response_id()
        messages = _normalize_input(body.get("input"))
        config = {"configurable": {"thread_id": thread_id}}

        result = await self.graph.ainvoke({"messages": messages}, config)
        last = result["messages"][-1]
        raw_content = last["content"] if isinstance(last, dict) else getattr(last, "content", "")
        content = flatten_content(raw_content)

        return {
            "id": thread_id,
            "object": "response",
            "created_at": int(time.time()),
            "model": body.get("model", f"vystak/{self.agent.name}"),
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": content}],
                }
            ],
        }

    async def _create_stream(self, body: dict):
        return self._stream_iterator(body)

    async def _stream_iterator(self, body: dict):
        thread_id = body.get("previous_response_id") or _new_response_id()
        model = body.get("model", f"vystak/{self.agent.name}")
        created = int(time.time())

        yield _sse({
            "type": "response.created",
            "response": {
                "id": thread_id,
                "object": "response",
                "created_at": created,
                "model": model,
                "status": "in_progress",
            },
        })

        messages = _normalize_input(body.get("input"))
        config = {"configurable": {"thread_id": thread_id}}
        full_text = []
        item_id = f"msg_{uuid.uuid4().hex[:12]}"

        try:
            async for ev in self.graph.astream_events(
                {"messages": messages}, config, version="v2"
            ):
                if self._observer is not None:
                    for checkpoint_id in self._observer.drain(thread_id):
                        yield _sse({
                            "type": "vystak.checkpoint",
                            "checkpoint_id": checkpoint_id,
                        })
                ev_type = ev.get("event")
                if ev_type == "on_chat_model_stream":
                    chunk = ev.get("data", {}).get("chunk")
                    if isinstance(chunk, dict):
                        raw_text = chunk["content"]
                    else:
                        raw_text = getattr(chunk, "content", "")
                    text = flatten_content(raw_text)
                    if text:
                        full_text.append(text)
                        yield _sse({
                            "type": "response.output_text.delta",
                            "item_id": item_id,
                            "output_index": 0,
                            "content_index": 0,
                            "delta": text,
                        })
                elif ev_type == "on_tool_start":
                    # Same events a2a_native/executor.py watches to surface
                    # tool activity to Slack; here they become the OpenAI
                    # Responses tool-call SSE shapes vystak-chat/client.py
                    # already parses. run_id is the stable per-invocation key
                    # (matches the executor's start/end correlation).
                    call_id = str(ev.get("run_id") or "")
                    if call_id:
                        tool_name = ev.get("name") or ""
                        arguments = _serialize_tool_payload(
                            ev.get("data", {}).get("input", {})
                        )
                        yield _sse({
                            "type": "response.output_item.added",
                            "item": {
                                "type": "function_call",
                                "id": call_id,
                                "call_id": call_id,
                                "name": tool_name,
                                "arguments": "",
                            },
                        })
                        yield _sse({
                            "type": "response.function_call_arguments.delta",
                            "call_id": call_id,
                            "delta": arguments,
                        })
                        yield _sse({
                            "type": "response.function_call_arguments.done",
                            "call_id": call_id,
                            "arguments": arguments,
                        })
                elif ev_type == "on_tool_end":
                    call_id = str(ev.get("run_id") or "")
                    if call_id:
                        output = _serialize_tool_payload(
                            ev.get("data", {}).get("output", "")
                        )
                        yield _sse({
                            "type": "response.output_item.added",
                            "item": {
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": output,
                            },
                        })
                elif ev_type == "on_tool_error":
                    # LangChain emits on_tool_error instead of on_tool_end
                    # when a tool raises. Without a terminating output event
                    # here, the function_call start emitted above would have
                    # no matching end — a consumer (e.g. the control-panel
                    # UI) can never learn the call finished and renders it as
                    # perpetually running. Emit the same function_call_output
                    # shape as on_tool_end, marked as an error, so existing
                    # consumers that ignore the extra key still see the call
                    # terminate. `data["error"]` is an exception instance,
                    # not a string. Stringify it before handing it to the
                    # same defensive serializer used for tool output: an
                    # exception isn't `str` or `list`, so without this it
                    # falls to _serialize_tool_payload's json.dumps(...,
                    # default=str) branch, which wraps the message in extra
                    # JSON quotes (`'"boom"'`) — consumers like
                    # vystak-chat/chat.py render `output` as raw text, so
                    # that would show literal quote characters.
                    call_id = str(ev.get("run_id") or "")
                    if call_id:
                        raw_error = ev.get("data", {}).get("error", "")
                        if isinstance(raw_error, BaseException):
                            raw_error = str(raw_error)
                        output = _serialize_tool_payload(raw_error)
                        yield _sse({
                            "type": "response.output_item.added",
                            "item": {
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": output,
                                "error": True,
                            },
                        })
        except Exception as e:  # noqa: BLE001
            yield _sse({
                "type": "response.failed",
                "response": {"id": thread_id, "status": "failed", "error": {"message": str(e)}},
            })
            yield "data: [DONE]\n\n"
            return

        if self._observer is not None:
            for checkpoint_id in self._observer.drain(thread_id):
                yield _sse({
                    "type": "vystak.checkpoint",
                    "checkpoint_id": checkpoint_id,
                })

        final_text = "".join(full_text)
        yield _sse({
            "type": "response.output_text.done",
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "text": final_text,
        })
        yield _sse({
            "type": "response.completed",
            "response": {
                "id": thread_id,
                "object": "response",
                "created_at": created,
                "model": model,
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": final_text}],
                    }
                ],
            },
        })
        yield "data: [DONE]\n\n"

    async def get(self, response_id: str) -> dict:
        config = {"configurable": {"thread_id": response_id}}
        snapshot = await self.graph.aget_state(config)
        messages = (snapshot.values or {}).get("messages")
        if not messages:
            raise KeyError(f"Unknown response: {response_id}")

        last = messages[-1]
        raw_text = last["content"] if isinstance(last, dict) else getattr(last, "content", "")
        text = flatten_content(raw_text)

        return {
            "id": response_id,
            "object": "response",
            "model": f"vystak/{self.agent.name}",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
        }


def _new_response_id() -> str:
    return f"resp_{uuid.uuid4().hex[:24]}"


def _normalize_input(value: Any) -> list[dict]:
    if isinstance(value, str):
        return [{"role": "user", "content": value}]
    if isinstance(value, list):
        return value
    return []


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _serialize_tool_payload(value: Any) -> str:
    """Serialize a tool call's `input`/`output` for the wire.

    Neither is guaranteed to be a string: `input` is typically a plain dict
    of kwargs, and `output` is whatever the tool returned — which can itself
    be LangChain-style content (a list of typed blocks, e.g. extended
    thinking/tool-result shapes) if the tool returns multi-part content.
    `output` also isn't the tool's raw return value on the `on_tool_end`
    path: LangChain wraps it in a `ToolMessage`, whose repr (`content=...
    name=... tool_call_id=...`) would otherwise leak onto the wire. Unwrap
    any message-like object (anything exposing `.content`) before the rest
    of this function runs, flattening its `.content` the same way as any
    other LangChain content shape. Plain values (str/dict/list/numbers)
    don't have a `.content` attribute, so this is a no-op for them.
    Try flatten_content first for the str/list-of-content-block shapes the
    rest of this runtime already contends with; fall back to json.dumps for
    arbitrary objects (dicts, numbers, custom types). A dict must never reach
    flatten_content directly — it falls through to `str(dict)`, which is a
    Python repr, not valid JSON.
    """
    if hasattr(value, "content"):
        value = value.content
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        flattened = flatten_content(value)
        if flattened:
            return flattened
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)
