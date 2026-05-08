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
            return self._create_stream(body)
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

    def _create_stream(self, body: dict):
        # Filled in by Task 2.3.
        raise NotImplementedError("streaming added in Task 2.3")


def _new_response_id() -> str:
    return f"resp_{uuid.uuid4().hex[:24]}"


def _normalize_input(value: Any) -> list[dict]:
    if isinstance(value, str):
        return [{"role": "user", "content": value}]
    if isinstance(value, list):
        return value
    return []
