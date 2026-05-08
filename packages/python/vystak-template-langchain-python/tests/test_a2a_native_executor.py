"""LangGraphExecutor — drives the a2a-sdk lifecycle from a fake graph."""

import pytest
from _vystak.runtime.a2a_native.executor import LangGraphExecutor
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role, TaskState


class FakeGraph:
    """Stand-in for a CompiledGraph that returns a single canned message."""

    def __init__(self, final_text: str = "hello"):
        self._final = final_text

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        # Async-generator stub — the executor only consumes events, doesn't
        # forward them. Returning without yielding is valid.
        return
        yield  # unreachable, here to mark this as an async generator

    async def aget_state(self, config):  # noqa: ANN001
        text = self._final

        class _Msg:
            content = text

        class _Snap:
            values = {"messages": [_Msg()]}

        return _Snap()


class FakeFailingGraph:
    """Stand-in graph that raises during astream_events."""

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        raise RuntimeError("graph blew up")
        yield  # unreachable

    async def aget_state(self, config):  # noqa: ANN001
        raise AssertionError("aget_state should not be called when astream raises")


class RecordingQueue(EventQueue):
    """Captures every event for assertion."""

    def __init__(self):
        super().__init__()
        self.events: list = []

    async def enqueue_event(self, event):  # noqa: ANN001
        self.events.append(event)


class FakeContext:
    task_id = "t-1"
    context_id = "ctx-1"
    message = Message(
        role=Role.ROLE_USER,
        message_id="m-1",
        parts=[Part(text="ping")],
    )


@pytest.mark.asyncio
async def test_executor_completes_with_final_text():
    """Successful run -> two events: WORKING (start) + COMPLETED (final)."""
    graph = FakeGraph("the answer is 42")
    executor = LangGraphExecutor(graph=graph)
    queue = RecordingQueue()

    await executor.execute(FakeContext(), queue)

    # Two TaskStatusUpdateEvent enqueued: start_work + complete.
    assert len(queue.events) == 2
    states = [ev.status.state for ev in queue.events]
    assert states[0] == TaskState.TASK_STATE_WORKING
    assert states[-1] == TaskState.TASK_STATE_COMPLETED

    # The completion event carries the final text in status.message.parts[0].text.
    completion = queue.events[-1]
    assert completion.status.message.parts[0].text == "the answer is 42"


@pytest.mark.asyncio
async def test_executor_marks_failed_when_graph_raises():
    executor = LangGraphExecutor(graph=FakeFailingGraph())
    queue = RecordingQueue()

    await executor.execute(FakeContext(), queue)

    states = [ev.status.state for ev in queue.events]
    assert TaskState.TASK_STATE_FAILED in states
    failure = queue.events[-1]
    assert "graph blew up" in failure.status.message.parts[0].text


@pytest.mark.asyncio
async def test_executor_cancel_emits_canceled_state():
    executor = LangGraphExecutor(graph=FakeGraph("never returned"))
    queue = RecordingQueue()

    await executor.cancel(FakeContext(), queue)

    states = [ev.status.state for ev in queue.events]
    assert states == [TaskState.TASK_STATE_CANCELED]
