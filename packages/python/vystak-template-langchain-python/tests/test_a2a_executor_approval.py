"""LangGraphExecutor -- parks the task in input-required state when the
graph interrupts mid-turn for a tool approval, instead of completing it."""

import json

import pytest
from _vystak.runtime.a2a_native.executor import LangGraphExecutor
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role, TaskState, TaskStatusUpdateEvent

PAYLOAD = {"kind": "tool_approval", "tool": "dangerous", "args": {"x": 1}, "skill": "ops"}


class _Interrupt:
    def __init__(self, value):
        self.value = value


class _InterruptedTask:
    def __init__(self, interrupts):
        self.interrupts = interrupts


class ApprovalGraph:
    """Stand-in for a CompiledGraph paused on interrupt() mid-turn."""

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        return
        yield  # unreachable, marks this as an async generator

    async def aget_state(self, config):  # noqa: ANN001
        class _Snap:
            values = {"messages": []}
            next = ("tools",)
            tasks = (_InterruptedTask([_Interrupt(PAYLOAD)]),)

        return _Snap()


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
    current_task = None
    message = Message(
        role=Role.ROLE_USER,
        message_id="m-1",
        parts=[Part(text="do the dangerous thing")],
    )


class NextWithoutInterruptsGraph:
    """snapshot.next is truthy (e.g. a scheduled retry) but no interrupts
    were raised -- must fall through to the normal completion path."""

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        return
        yield  # unreachable, marks this as an async generator

    async def aget_state(self, config):  # noqa: ANN001
        class _Msg:
            content = "done anyway"

        class _Snap:
            values = {"messages": [_Msg()]}
            next = ("tools",)
            tasks = ()

        return _Snap()


@pytest.mark.asyncio
async def test_executor_completes_normally_when_next_truthy_but_no_interrupts():
    executor = LangGraphExecutor(graph=NextWithoutInterruptsGraph())
    queue = RecordingQueue()

    await executor.execute(FakeContext(), queue)

    status_events = [ev for ev in queue.events if isinstance(ev, TaskStatusUpdateEvent)]
    states = [ev.status.state for ev in status_events]
    assert states[-1] == TaskState.TASK_STATE_COMPLETED
    assert status_events[-1].status.message.parts[0].text == "done anyway"


@pytest.mark.asyncio
async def test_executor_parks_on_interrupt_instead_of_completing():
    executor = LangGraphExecutor(graph=ApprovalGraph())
    queue = RecordingQueue()

    await executor.execute(FakeContext(), queue)

    status_events = [ev for ev in queue.events if isinstance(ev, TaskStatusUpdateEvent)]
    states = [ev.status.state for ev in status_events]

    # start_work (WORKING) then the park -- never COMPLETED.
    assert TaskState.TASK_STATE_COMPLETED not in states
    assert states[-1] == TaskState.TASK_STATE_INPUT_REQUIRED

    parked = status_events[-1]
    marker = json.loads(parked.status.message.parts[0].text)
    assert marker == {
        "kind": "approval_pending",
        "payload": PAYLOAD,
        "thread_id": "t-1",
    }
