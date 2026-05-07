"""A2AHandler dispatch — non-streaming JSON-RPC methods."""

import pytest
from _vystak.runtime.a2a.handler import A2AHandler
from _vystak.runtime.a2a.tasks import TaskManager, TaskState


class FakeGraph:
    """Minimal CompiledGraph stand-in returning a canned final response."""

    def __init__(self, response_text: str = "ok") -> None:
        self._text = response_text

    async def ainvoke(self, input, config):  # noqa: ANN001
        return {"messages": [{"role": "assistant", "content": self._text}]}


@pytest.fixture
def handler():
    return A2AHandler(agent=None, graph=FakeGraph("hello"), task_manager=TaskManager())


@pytest.mark.asyncio
async def test_tasks_send_returns_completed_with_text(handler):
    payload = {
        "jsonrpc": "2.0",
        "id": "rpc-1",
        "method": "tasks/send",
        "params": {
            "id": "task-1",
            "message": {"role": "user", "parts": [{"text": "hi"}]},
        },
    }
    result = await handler.dispatch(payload)
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == "rpc-1"
    assert result["result"]["status"]["state"] == "completed"
    assert result["result"]["status"]["message"]["parts"][0]["text"] == "hello"


@pytest.mark.asyncio
async def test_tasks_get_returns_stored_task(handler):
    await handler.dispatch({
        "jsonrpc": "2.0", "id": "1", "method": "tasks/send",
        "params": {"id": "task-1", "message": {"role": "user", "parts": [{"text": "hi"}]}},
    })
    result = await handler.dispatch({
        "jsonrpc": "2.0", "id": "2", "method": "tasks/get",
        "params": {"id": "task-1"},
    })
    assert result["result"]["id"] == "task-1"


@pytest.mark.asyncio
async def test_tasks_cancel_marks_canceled(handler):
    handler.task_manager.create("task-1", {})
    handler.task_manager.set_state("task-1", TaskState.WORKING)
    result = await handler.dispatch({
        "jsonrpc": "2.0", "id": "3", "method": "tasks/cancel",
        "params": {"id": "task-1"},
    })
    assert result["result"]["status"]["state"] == "canceled"


@pytest.mark.asyncio
async def test_unknown_method_returns_jsonrpc_error(handler):
    result = await handler.dispatch({
        "jsonrpc": "2.0", "id": "x", "method": "tasks/unknown", "params": {},
    })
    assert "error" in result
    assert result["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_get_unknown_task_returns_jsonrpc_error(handler):
    result = await handler.dispatch({
        "jsonrpc": "2.0", "id": "y", "method": "tasks/get",
        "params": {"id": "missing"},
    })
    assert result["error"]["code"] == -32602
