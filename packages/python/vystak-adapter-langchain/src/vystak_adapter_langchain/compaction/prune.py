"""Layer 1 — head-and-tail truncation of oversized tool outputs.

Pure synchronous function. Never writes to any store, never calls an LLM,
never touches HumanMessage / AIMessage text content. The last
`keep_last_turns` user→assistant pairs are preserved byte-for-byte.
"""

from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

_HEAD_BYTES = 512
_TAIL_BYTES = 512


def prune_messages(
    messages: list[BaseMessage],
    *,
    max_tool_output_bytes: int,
    keep_last_turns: int = 3,
) -> list[BaseMessage]:
    """Soft-trim oversized tool outputs head-and-tail; protect last N turns."""
    if not messages:
        return []
    cutoff_index = _index_of_keep_zone(messages, keep_last_turns)
    out: list[BaseMessage] = []
    for i, msg in enumerate(messages):
        if i >= cutoff_index:
            out.append(msg)
            continue
        if isinstance(msg, ToolMessage) and isinstance(msg.content, str):
            content = msg.content
            if len(content.encode("utf-8")) > max_tool_output_bytes:
                head = content[:_HEAD_BYTES]
                tail = content[-_TAIL_BYTES:]
                trimmed_bytes = len(content) - len(head) - len(tail)
                msg = msg.model_copy(
                    update={
                        "content": (
                            f"{head}\n...truncated {trimmed_bytes} bytes...\n{tail}"
                        )
                    }
                )
        out.append(msg)
    return out


def _index_of_keep_zone(messages: list[BaseMessage], keep_last_turns: int) -> int:
    """Return the first index that belongs in the protected recent zone."""
    if keep_last_turns <= 0:
        return len(messages)
    turns_seen = 0
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            turns_seen += 1
            if turns_seen >= keep_last_turns:
                return i
    return 0  # whole list is recent
