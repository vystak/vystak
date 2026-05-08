"""Stateless /v1/chat/completions handler."""

import time
import uuid
from typing import Any


class ChatCompletionsHandler:
    """Stateless Chat Completions — no checkpointer, full message array per call."""

    def __init__(self, agent: Any, graph: Any) -> None:
        self.agent = agent
        self.graph = graph

    async def create(self, body: dict) -> dict:
        messages = body.get("messages", [])
        # LangGraph requires a thread_id when the graph has a checkpointer.
        # For stateless chat, use a fresh per-call thread_id so no state survives.
        ephemeral_thread = f"chat-{uuid.uuid4().hex[:16]}"
        config = {"configurable": {"thread_id": ephemeral_thread}}
        result = await self.graph.ainvoke({"messages": messages}, config=config)

        last = result["messages"][-1]
        content = last["content"] if isinstance(last, dict) else getattr(last, "content", "")

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", f"vystak/{self.agent.name}"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            # TODO(phase-5): real token counts from LLM provider's usage_metadata.
            # Zero values are placeholders; clients should treat usage as advisory.
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
