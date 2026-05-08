"""Layer 1 — head-and-tail prune of oversized ToolMessages."""

from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

KEEP_RECENT_TURNS = 3


class PreCallPruner:
    """Pure transform applied to messages before each LLM call."""

    def __init__(self, compaction: Any) -> None:
        self._threshold = compaction.prune_tool_output_bytes

    def prune(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        if not messages:
            return messages

        recent_cutoff = self._find_recent_cutoff(messages)
        out: list[BaseMessage] = []
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage) and i < recent_cutoff:
                content = str(msg.content)
                if len(content) > self._threshold:
                    half = self._threshold // 2 - 10
                    truncated = (
                        content[:half]
                        + f"\n... [truncated {len(content) - 2 * half} bytes] ...\n"
                        + content[-half:]
                    )
                    out.append(ToolMessage(
                        content=truncated,
                        tool_call_id=getattr(msg, "tool_call_id", ""),
                    ))
                    continue
            out.append(msg)
        return out

    def _find_recent_cutoff(self, messages: list[BaseMessage]) -> int:
        """Find the index N such that messages[N:] are 'recent' (last 3 turns)."""
        human_indices = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
        if len(human_indices) <= KEEP_RECENT_TURNS:
            return 0
        return human_indices[-KEEP_RECENT_TURNS]
