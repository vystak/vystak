"""LangGraph-backed AgentExecutor for the a2a-sdk server.

Drives a compiled LangGraph state graph from the SDK's task lifecycle. Returns
the final assistant text via TaskUpdater.complete() with a `Message` carrying
the text in a single TextPart — which the SDK serializes into the wire shape
`result.status.message.parts[0].text` that vystak-channel-runtime + vystak-chat
already consume.

The SDK's ActiveTask consumer requires a Task event to be enqueued *before*
any TaskStatusUpdateEvent the first time — otherwise it raises
`InvalidAgentResponseError("Agent should enqueue Task before ...")`. So
`execute()` enqueues an initial Task with state SUBMITTED before delegating
to TaskUpdater.start_work().
"""

from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus


class LangGraphExecutor(AgentExecutor):
    """Drives a LangGraph compiled graph from the a2a-sdk task lifecycle."""

    def __init__(self, graph: Any, memory_mgr: Any = None) -> None:
        self._graph = graph
        self._memory_mgr = memory_mgr

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Enqueue an initial Task if this is a fresh request — the SDK's
        # ActiveTask consumer raises if a TaskStatusUpdateEvent arrives
        # before a Task has been seen for this task_id.
        if context.current_task is None:
            initial_task = Task(
                id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            )
            await event_queue.enqueue_event(initial_task)

        updater = TaskUpdater(
            event_queue,
            task_id=context.task_id,
            context_id=context.context_id,
        )
        await updater.start_work()

        text = _extract_user_text(context.message)
        config = {"configurable": {"thread_id": context.task_id}}

        try:
            # Drive the graph to completion. We don't surface intermediate
            # token chunks for now — the SDK SSE pipe still emits status
            # transitions and the final completion frame, which is what
            # vystak-channel-runtime keys off.
            async for _ev in self._graph.astream_events(
                {"messages": [{"role": "user", "content": text}]},
                config,
                version="v2",
            ):
                pass

            snapshot = await self._graph.aget_state(config)
            messages = (snapshot.values or {}).get("messages") or []
            final_text = _flatten_content(
                messages[-1].content if messages else ""
            )
        except Exception as e:  # noqa: BLE001
            failure_msg = updater.new_agent_message([Part(text=f"Error: {e}")])
            await updater.failed(message=failure_msg)
            return

        completion_msg = updater.new_agent_message([Part(text=final_text)])
        await updater.complete(message=completion_msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(
            event_queue,
            task_id=context.task_id,
            context_id=context.context_id,
        )
        await updater.cancel()


def _extract_user_text(message: Any) -> str:
    parts = getattr(message, "parts", None) or []
    out: list[str] = []
    for p in parts:
        text = getattr(p, "text", None)
        if isinstance(text, str):
            out.append(text)
    return "".join(out)


def _flatten_content(content: Any) -> str:
    """Flatten LangChain message content into a plain string.

    Anthropic extended-thinking returns content as a list of typed blocks
    [{"type": "thinking", ...}, {"type": "text", ...}, ...]. The A2A wire
    expects a string, so concatenate `text` blocks and drop thinking/tool_use.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                out.append(str(block.get("text", "")))
            elif isinstance(block, str):
                out.append(block)
        return "".join(out)
    return str(content)
