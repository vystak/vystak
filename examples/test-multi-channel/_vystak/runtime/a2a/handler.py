"""A2AHandler — JSON-RPC dispatch over /a2a."""

from typing import Any

from _vystak.runtime.a2a.tasks import TaskManager, TaskState


class A2AHandler:
    def __init__(self, agent, graph, task_manager: TaskManager) -> None:  # noqa: ANN001
        self.agent = agent
        self.graph = graph
        self.task_manager = task_manager

    async def dispatch(self, payload: dict) -> dict:
        method = payload.get("method")
        rpc_id = payload.get("id")
        params = payload.get("params") or {}

        try:
            if method == "tasks/send":
                result = await self._tasks_send(params)
            elif method == "tasks/get":
                result = self._tasks_get(params)
            elif method == "tasks/cancel":
                result = self._tasks_cancel(params)
            else:
                return _err(rpc_id, -32601, f"Method not found: {method}")
        except _RpcError as e:
            return _err(rpc_id, e.code, e.message)

        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

    async def _tasks_send(self, params: dict) -> dict:
        task_id = params["id"]
        message = params.get("message", {})
        self.task_manager.create(task_id, message)
        self.task_manager.set_state(task_id, TaskState.WORKING)

        config = {"configurable": {"thread_id": task_id}}
        result = await self.graph.ainvoke({"messages": [_to_lc_message(message)]}, config)

        last = result["messages"][-1]
        self.task_manager.set_state(task_id, TaskState.COMPLETED)
        return _task_payload(self.task_manager.get(task_id), final_text=_extract_text(last))

    def _tasks_get(self, params: dict) -> dict:
        task = self.task_manager.get(params["id"])
        if task is None:
            raise _RpcError(-32602, f"Task not found: {params['id']}")
        return _task_payload(task)

    def _tasks_cancel(self, params: dict) -> dict:
        task = self.task_manager.get(params["id"])
        if task is None:
            raise _RpcError(-32602, f"Task not found: {params['id']}")
        self.task_manager.cancel(params["id"])
        return _task_payload(self.task_manager.get(params["id"]))

    async def stream_dispatch(self, payload: dict):
        """Yields SSE frames (str, ending in \\n\\n) for tasks/sendSubscribe."""
        method = payload.get("method")
        rpc_id = payload.get("id")
        params = payload.get("params") or {}
        if method != "tasks/sendSubscribe":
            yield _sse(_err(rpc_id, -32601, f"Method not found: {method}"))
            return

        task_id = params["id"]
        message = params.get("message", {})
        self.task_manager.create(task_id, message)
        self.task_manager.set_state(task_id, TaskState.WORKING)
        yield _sse({
            "jsonrpc": "2.0", "id": rpc_id,
            "result": _task_payload(self.task_manager.get(task_id)),
        })

        config = {"configurable": {"thread_id": task_id}}
        try:
            async for ev in self.graph.astream_events(
                {"messages": [_to_lc_message(message)]}, config, version="v2"
            ):
                if ev.get("event") == "on_chat_model_stream":
                    chunk = ev.get("data", {}).get("chunk")
                    text = _extract_text(chunk) if chunk else ""
                    if text:
                        yield _sse({
                            "jsonrpc": "2.0", "id": rpc_id,
                            "result": {
                                "id": task_id,
                                "status": {"state": "working"},
                                "artifact": {"parts": [{"text": text}]},
                            },
                        })
        except Exception as e:  # noqa: BLE001
            self.task_manager.set_state(task_id, TaskState.FAILED)
            yield _sse(_err(rpc_id, -32000, f"Stream error: {e}"))
            return

        self.task_manager.set_state(task_id, TaskState.COMPLETED)
        yield _sse({
            "jsonrpc": "2.0", "id": rpc_id,
            "result": {"id": task_id, "status": {"state": "completed"}, "final": True},
        })


class _RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message


def _err(rpc_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def _to_lc_message(msg: dict) -> dict:
    parts = msg.get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    return {"role": msg.get("role", "user"), "content": text}


def _extract_text(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return getattr(message, "content", "")


def _task_payload(task, final_text: str | None = None) -> dict:  # noqa: ANN001
    payload = {
        "id": task.id,
        "status": {
            "state": task.state.value,
        },
    }
    if final_text is not None:
        payload["status"]["message"] = {
            "role": "assistant",
            "parts": [{"text": final_text}],
        }
    return payload


def _sse(payload: dict) -> str:
    import json
    return f"data: {json.dumps(payload)}\n\n"
