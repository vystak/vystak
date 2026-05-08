"""Build the prompt callable for LangGraph create_react_agent.

Per LangMem canonical pattern: this function is invoked fresh for every
turn, reconstructs the system message, applies Layer 1 prune, and inlines
any compaction summary as a SystemMessage at the top of the message list.
"""

from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


def build_prompt(agent: Any, *, memory_mgr: Any, compactor: Any, pruner: Any):
    instructions = (agent.instructions or "").strip()

    async def _prompt(
        state: dict, config: dict | None = None
    ) -> list[BaseMessage]:
        messages: list[BaseMessage] = list(state.get("messages", []))
        configurable = (config or {}).get("configurable") or {}

        if pruner is not None:
            messages = pruner.prune(messages)

        sys_parts = [instructions] if instructions else []

        if memory_mgr is not None:
            user_id = configurable.get("user_id", "default")
            query = _last_human_text(messages)
            recalled = await memory_mgr.recall(user_id=user_id, query=query)
            if recalled:
                sys_parts.append("## Memory\n" + "\n".join(recalled))

        if compactor is not None:
            thread_id = configurable.get("thread_id")
            if thread_id:
                latest = await compactor.store.latest(thread_id)
                if latest:
                    sys_parts.append(f"## Earlier conversation summary\n{latest['summary']}")

        sys_msg = SystemMessage(content="\n\n".join(sys_parts) or " ")
        return [sys_msg, *messages]

    return _prompt


def _last_human_text(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return str(m.content)
    return ""
