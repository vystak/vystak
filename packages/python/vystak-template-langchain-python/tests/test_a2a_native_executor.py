"""LangGraphExecutor — drives the a2a-sdk lifecycle from a fake graph."""

import pytest
from _vystak.runtime.a2a_native.executor import LangGraphExecutor
from _vystak.runtime.schedules import CURRENT_TURN_METADATA
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role, Task, TaskState, TaskStatusUpdateEvent
from google.protobuf.struct_pb2 import Struct


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
    current_task = None  # SDK uses this to detect a fresh request.
    message = Message(
        role=Role.ROLE_USER,
        message_id="m-1",
        parts=[Part(text="ping")],
    )


@pytest.mark.asyncio
async def test_executor_completes_with_final_text():
    """Successful run -> Task (initial) + WORKING (start) + COMPLETED (final)."""
    graph = FakeGraph("the answer is 42")
    executor = LangGraphExecutor(graph=graph)
    queue = RecordingQueue()

    await executor.execute(FakeContext(), queue)

    # Three events: initial Task (state=SUBMITTED), then start_work + complete
    # status updates. Initial Task is required by the SDK's ActiveTask consumer.
    assert len(queue.events) == 3
    assert isinstance(queue.events[0], Task)
    assert queue.events[0].status.state == TaskState.TASK_STATE_SUBMITTED

    status_events = [ev for ev in queue.events if isinstance(ev, TaskStatusUpdateEvent)]
    states = [ev.status.state for ev in status_events]
    assert states == [TaskState.TASK_STATE_WORKING, TaskState.TASK_STATE_COMPLETED]

    # The completion event carries the final text in status.message.parts[0].text.
    completion = status_events[-1]
    assert completion.status.message.parts[0].text == "the answer is 42"


@pytest.mark.asyncio
async def test_executor_marks_failed_when_graph_raises():
    executor = LangGraphExecutor(graph=FakeFailingGraph())
    queue = RecordingQueue()

    await executor.execute(FakeContext(), queue)

    # Status events only — drop the initial Task event.
    status_events = [ev for ev in queue.events if isinstance(ev, TaskStatusUpdateEvent)]
    states = [ev.status.state for ev in status_events]
    assert TaskState.TASK_STATE_FAILED in states
    failure = status_events[-1]
    assert "graph blew up" in failure.status.message.parts[0].text


@pytest.mark.asyncio
async def test_executor_cancel_emits_canceled_state():
    executor = LangGraphExecutor(graph=FakeGraph("never returned"))
    queue = RecordingQueue()

    await executor.cancel(FakeContext(), queue)

    states = [ev.status.state for ev in queue.events]
    assert states == [TaskState.TASK_STATE_CANCELED]


class FakeStreamingGraph:
    """Yields canned on_chat_model_stream events."""

    def __init__(self, deltas: list[str]):
        self._deltas = deltas

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        for delta in self._deltas:
            class _Chunk:
                content = delta
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": _Chunk()},
            }

    async def aget_state(self, config):  # noqa: ANN001
        full = "".join(self._deltas)

        class _Msg:
            content = full

        class _Snap:
            values = {"messages": [_Msg()]}

        return _Snap()


@pytest.mark.asyncio
async def test_executor_streams_token_deltas_as_working_status_updates():
    """Each non-empty on_chat_model_stream chunk produces a WORKING status frame
    so vystak-channel-slack and vystak-chat can render incremental output."""
    executor = LangGraphExecutor(graph=FakeStreamingGraph(["he", "llo", " world"]))
    queue = RecordingQueue()

    await executor.execute(FakeContext(), queue)

    status_events = [ev for ev in queue.events if isinstance(ev, TaskStatusUpdateEvent)]
    working_events = [ev for ev in status_events if ev.status.state == TaskState.TASK_STATE_WORKING]
    # Initial start_work + 3 token chunks = 4 WORKING events.
    assert len(working_events) == 4
    deltas = [ev.status.message.parts[0].text for ev in working_events[1:]]
    assert deltas == ["he", "llo", " world"]


@pytest.mark.asyncio
async def test_executor_skips_initial_task_when_already_present():
    """If RequestContext already has a current_task (e.g. follow-up call),
    the executor must not enqueue a new Task event — that would be a no-op
    in the SDK but pollutes the event stream."""

    class FollowUpContext(FakeContext):
        current_task = Task(id="t-1", context_id="ctx-1")

    executor = LangGraphExecutor(graph=FakeGraph("ack"))
    queue = RecordingQueue()

    await executor.execute(FollowUpContext(), queue)

    tasks = [ev for ev in queue.events if isinstance(ev, Task)]
    assert tasks == []  # no Task event emitted on follow-up


# ---------------------------------------------------------------------------
# Turn metadata — CURRENT_TURN_METADATA must be set from the incoming
# message before the graph runs, so a schedule_task tool call made mid-turn
# can read channel_canonical/thread_id (see _vystak/runtime/schedules.py).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_turn_metadata():
    token = CURRENT_TURN_METADATA.set({})
    yield
    CURRENT_TURN_METADATA.reset(token)


class MetadataCapturingGraph:
    """Records CURRENT_TURN_METADATA at astream_events time — proves the
    executor sets it before driving the graph, not after."""

    def __init__(self):
        self.seen_metadata: dict | None = None

    async def astream_events(self, input, config, version="v2"):  # noqa: ANN001
        self.seen_metadata = CURRENT_TURN_METADATA.get()
        return
        yield  # unreachable, marks this as an async generator

    async def aget_state(self, config):  # noqa: ANN001
        class _Msg:
            content = "ok"

        class _Snap:
            values = {"messages": [_Msg()]}

        return _Snap()


@pytest.mark.asyncio
async def test_executor_sets_current_turn_metadata_before_running_graph():
    """The incoming message's metadata (a google.protobuf.Struct on a2a-sdk
    1.0.2's protobuf-backed Message type) must land in CURRENT_TURN_METADATA
    as a plain dict before the graph runs."""
    meta = Struct()
    meta.update({"channel_canonical": "c.channels.d", "thread_id": "t9"})

    class ContextWithMetadata(FakeContext):
        message = Message(
            role=Role.ROLE_USER,
            message_id="m-2",
            parts=[Part(text="ping")],
            metadata=meta,
        )

    graph = MetadataCapturingGraph()
    executor = LangGraphExecutor(graph=graph)
    queue = RecordingQueue()

    await executor.execute(ContextWithMetadata(), queue)

    assert graph.seen_metadata == {"channel_canonical": "c.channels.d", "thread_id": "t9"}


@pytest.mark.asyncio
async def test_executor_sets_empty_turn_metadata_when_message_has_none():
    """FakeContext.message carries no metadata -> {} (never None), so
    schedule_task's CURRENT_TURN_METADATA.get().get(...) never raises."""
    graph = MetadataCapturingGraph()
    executor = LangGraphExecutor(graph=graph)
    queue = RecordingQueue()

    await executor.execute(FakeContext(), queue)

    assert graph.seen_metadata == {}
