import json
import uuid

import httpx
from langgraph.config import get_stream_writer


TIME_AGENT_URL = "http://agentstack-time-agent:8000/a2a"


async def ask_time_agent(question: str) -> str:
    """Ask the time specialist agent a question via A2A protocol.

    Use this tool when the user asks about the current time.
    """
    writer = get_stream_writer()
    task_id = str(uuid.uuid4())

    writer({
        "type": "agent_call",
        "agent": "time-agent",
        "status": "started",
        "question": question,
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
            "response_preview": response_text[:100],
        })

        return response_text

    except Exception as e:
        writer({
            "type": "agent_call",
            "agent": "time-agent",
            "status": "failed",
            "error": str(e),
        })
        return f"Could not reach time agent: {e}"
