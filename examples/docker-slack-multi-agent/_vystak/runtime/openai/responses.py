"""Stateful /v1/responses handler."""

import time
import uuid
from typing import Any


class ResponsesHandler:
    """OpenAI Responses API — stateful via previous_response_id (LangGraph thread_id)."""

    def __init__(self, agent: Any, graph: Any, *, store: Any | None) -> None:
        self.agent = agent
        self.graph = graph
        self.store = store

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
        content = last["content"] if isinstance(last, dict) else getattr(last, "content", "")

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
                if ev.get("event") == "on_chat_model_stream":
                    chunk = ev.get("data", {}).get("chunk")
                    if isinstance(chunk, dict):
                        text = chunk["content"]
                    else:
                        text = getattr(chunk, "content", "")
                    if text:
                        full_text.append(text)
                        yield _sse({
                            "type": "response.output_text.delta",
                            "item_id": item_id,
                            "output_index": 0,
                            "content_index": 0,
                            "delta": text,
                        })
        except Exception as e:  # noqa: BLE001
            yield _sse({
                "type": "response.failed",
                "response": {"id": thread_id, "status": "failed", "error": {"message": str(e)}},
            })
            yield "data: [DONE]\n\n"
            return

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
        text = last["content"] if isinstance(last, dict) else getattr(last, "content", "")

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
    import json
    return f"data: {json.dumps(payload)}\n\n"
