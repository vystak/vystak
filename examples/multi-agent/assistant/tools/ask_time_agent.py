import json
import uuid

import httpx
from langgraph.config import get_config, get_stream_writer


TIME_AGENT_URL = "http://vystak-time-agent:8000/a2a"


async def ask_time_agent(question: str) -> str:
    """Ask the time specialist agent a question via A2A protocol.

    Use this tool when the user asks about the current time.
    """
    writer = get_stream_writer()
    task_id = str(uuid.uuid4())

    # Read context from the current agent's config
    config = get_config()
    configurable = config.get("configurable", {})
    trace_id = configurable.get("trace_id", str(uuid.uuid4()))
    user_id = configurable.get("user_id")
    project_id = configurable.get("project_id")
    parent_task_id = configurable.get("thread_id")

    writer({
        "type": "agent_call",
        "agent": "time-agent",
        "status": "started",
        "question": question,
        "trace_id": trace_id,
    })

    try:
        payload = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": 1,
            "params": {
                "id": task_id,
                "message": {
                    "role": "user",
                    "parts": [{"text": question}],
                },
                "metadata": {
                    "trace_id": trace_id,
                    "user_id": user_id,
                    "project_id": project_id,
                    "parent_task_id": parent_task_id,
                },
            },
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(TIME_AGENT_URL, json=payload)
            result = response.json()

        task_result = result.get("result", {})
        status = task_result.get("status", {})
        message = status.get("message", {})
        parts = message.get("parts", [])
        texts = [p.get("text", "") for p in parts if "text" in p]
        response_text = " ".join(texts) if texts else "No response from time agent"

        writer({
            "type": "agent_call",
            "agent": "time-agent",
            "status": "completed",
            "trace_id": trace_id,
            "response_preview": response_text[:100],
        })

        return response_text

    except Exception as e:
        writer({
            "type": "agent_call",
            "agent": "time-agent",
            "status": "failed",
            "trace_id": trace_id,
            "error": str(e),
        })
        return f"Could not reach time agent: {e}"
