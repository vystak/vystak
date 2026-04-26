"""Emit the shared one-shot and streaming cores into the agent's ``server.py``.

Every generated agent server includes ``process_turn`` and
``process_turn_streaming`` exactly once, regardless of which protocol
adapters (A2A, /v1/chat/completions, /v1/responses) are present. The
cores own ``_agent.ainvoke`` / ``_agent.astream_events``,
``handle_memory_actions``, ``_task_manager`` state transitions, and
interrupt/resume handling. Each protocol layer is a thin wire-shape
translator around them.

Spec: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
"""

from __future__ import annotations

_TURN_CORE_SRC = '''\
@dataclass
class TurnResult:
    """One-shot turn result. Returned by ``process_turn``."""

    response_text: str
    messages: list
    interrupt_text: str | None = None


@dataclass
class TurnEvent:
    """Single streamed event. Yielded by ``process_turn_streaming``."""

    type: Literal["token", "tool_call", "interrupt", "final", "error"]
    text: str = ""
    data: dict | None = None
    final: bool = False


def _flatten_message_content(content) -> str:
    """Flatten an Anthropic-style message content into a single string."""
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _build_turn_config(metadata: dict, *, session_id: str) -> dict:
    """Build the LangGraph ``configurable`` block from A2A-style metadata."""
    return {"configurable": {
        "thread_id": session_id,
        "trace_id": metadata.get("trace_id") or str(uuid.uuid4()),
        "user_id": metadata.get("user_id"),
        "project_id": metadata.get("project_id"),
        "parent_task_id": metadata.get("parent_task_id"),
        "agent_name": AGENT_NAME,
    }}


async def process_turn(
    text: str,
    metadata: dict,
    *,
    resume_text: str | None = None,
    task_id: str | None = None,
    messages: list | None = None,
) -> TurnResult:
    """Run one agent turn. Used by every one-shot protocol path.

    Cross-cutting concerns (memory persistence, interrupt detection)
    happen here so they cannot drift between protocols.

    If ``messages`` is provided, it overrides ``text`` and is used directly
    as the LangGraph input — useful for stateless multi-turn protocols
    (OpenAI chat completions).
    """
    session_id = metadata.get("sessionId") or task_id or str(uuid.uuid4())
    user_id = metadata.get("user_id")
    project_id = metadata.get("project_id")
    config = _build_turn_config(metadata, session_id=session_id)

    if resume_text is not None:
        agent_input = Command(resume=resume_text)
    elif messages is not None:
        agent_input = {"messages": messages}
    else:
        agent_input = {"messages": [("user", text)]}

    result = await _agent.ainvoke(agent_input, config=config)

    if _store is not None:
        await handle_memory_actions(
            _store, result["messages"],
            user_id=user_id, project_id=project_id,
        )

    if "__interrupt__" in result:
        iv = result["__interrupt__"]
        interrupt_text = str(iv[0].value) if iv else "Input required"
        return TurnResult(
            response_text=interrupt_text,
            messages=result["messages"],
            interrupt_text=interrupt_text,
        )

    response_text = _flatten_message_content(result["messages"][-1].content)
    return TurnResult(response_text=response_text, messages=result["messages"])


async def process_turn_streaming(
    text: str,
    metadata: dict,
    *,
    resume_text: str | None = None,
    task_id: str | None = None,
    messages: list | None = None,
):
    """Stream agent events. Used by every streaming protocol path.

    Yields ``TurnEvent`` values. Memory persistence runs after the
    stream completes — once tool messages are collected from
    ``on_tool_end`` events.

    If ``messages`` is provided, it overrides ``text`` and is used directly
    as the LangGraph input — useful for stateless multi-turn protocols
    (OpenAI chat completions).
    """
    session_id = metadata.get("sessionId") or task_id or str(uuid.uuid4())
    user_id = metadata.get("user_id")
    project_id = metadata.get("project_id")
    config = _build_turn_config(metadata, session_id=session_id)

    if resume_text is not None:
        agent_input = Command(resume=resume_text)
    elif messages is not None:
        agent_input = {"messages": messages}
    else:
        agent_input = {"messages": [("user", text)]}

    accumulated: list[str] = []
    tool_msgs: list = []

    async for event in _agent.astream_events(
        agent_input, config=config, version="v2",
    ):
        if "__interrupt__" in event:
            iv = event["__interrupt__"]
            interrupt_text = str(iv[0].value) if iv else "Input required"
            yield TurnEvent(
                type="interrupt", text=interrupt_text,
                data={"state": "input_required"}, final=True,
            )
            return

        ev_kind = event.get("event")
        if ev_kind == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            raw = getattr(chunk, "content", "") if chunk is not None else ""
            token = _flatten_message_content(raw)
            if token:
                accumulated.append(token)
                yield TurnEvent(type="token", text=token)
        elif ev_kind == "on_tool_end":
            tm = event["data"].get("output")
            if tm is not None:
                # handle_memory_actions expects objects with .content (ToolMessage shape).
                # Bare strings (e.g. save_memory's "__SAVE_MEMORY__|..." return) are wrapped.
                if hasattr(tm, "content"):
                    tool_msgs.append(tm)
                elif isinstance(tm, str):
                    tool_msgs.append(SimpleNamespace(content=tm))
                # else: ignore — non-string, non-message outputs aren't memory sentinels.

    if _store is not None and tool_msgs:
        await handle_memory_actions(
            _store, tool_msgs,
            user_id=user_id, project_id=project_id,
        )

    yield TurnEvent(
        type="final", text="".join(accumulated),
        data={"state": "completed"}, final=True,
    )
'''


def emit_turn_core_helpers() -> str:
    """Return the shared turn-core source spliced into every ``server.py``.

    The returned string is plain Python source. It assumes the
    surrounding module has imported ``dataclass``, ``Literal``,
    ``uuid``, ``Command``, ``SimpleNamespace``, and that the names
    ``_agent``, ``_store``, ``handle_memory_actions``, and ``AGENT_NAME``
    are already bound at module level — these are all already part of
    the existing ``SERVER_PY`` shape.

    Helpers ``_flatten_message_content`` and ``_build_turn_config`` are
    defined inside the emitted source itself, not assumed at the splice
    site.
    """
    return _TURN_CORE_SRC
