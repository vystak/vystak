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

from _vystak.runtime.content import flatten_content


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
            # Drive the graph and surface token-stream events as WORKING-state
            # status updates so subscribers (vystak-channel-slack, vystak-chat)
            # can render incremental output. Each non-empty `on_chat_model_stream`
            # chunk publishes a status frame carrying the partial-token text in
            # message.parts[0].text — channel runtime accumulates these on its end.
            running_text: list[str] = []
            async for ev in self._graph.astream_events(
                {"messages": [{"role": "user", "content": text}]},
                config,
                version="v2",
            ):
                ev_type = ev.get("event")
                if ev_type == "on_chat_model_stream":
                    chunk = ev.get("data", {}).get("chunk")
                    delta = flatten_content(
                        getattr(chunk, "content", "") if chunk is not None else ""
                    )
                    if delta:
                        running_text.append(delta)
                        chunk_msg = updater.new_agent_message(
                            [Part(text=delta)]
                        )
                        await updater.update_status(
                            TaskState.TASK_STATE_WORKING,
                            message=chunk_msg,
                        )
                elif ev_type in ("on_tool_start", "on_tool_end"):
                    # Surface tool activity so subscribers (vystak-channel-slack)
                    # can render "is calling <tool>…" status hints. The wire
                    # carries the event under message.metadata["vystak_event"].
                    tool_name = ev.get("name") or ""
                    if tool_name:
                        kind = "tool_call" if ev_type == "on_tool_start" else "tool_result"
                        tool_msg = updater.new_agent_message(
                            [Part(text="")],
                            metadata={"vystak_event": kind, "tool_name": tool_name},
                        )
                        await updater.update_status(
                            TaskState.TASK_STATE_WORKING,
                            message=tool_msg,
                        )

            snapshot = await self._graph.aget_state(config)
            messages = (snapshot.values or {}).get("messages") or []
            final_text = flatten_content(
                messages[-1].content if messages else ""
            )
            # Fall back to the streamed accumulation if the snapshot is empty
            # (some graph/stream patterns clear values on completion).
            if not final_text and running_text:
                final_text = "".join(running_text)
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
