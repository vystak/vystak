"""Single-call summarizer."""

from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from vystak_adapter_langchain.compaction.errors import (
    CompactionError,
    SummaryResult,
)

_DEFAULT_SYSTEM = (
    "You are a session-history summarizer. Your output replaces older "
    "conversation turns when the model can no longer fit them. Preserve: "
    "(1) explicit facts, names, identifiers; (2) decisions and their "
    "rationale; (3) outstanding tasks. Drop: long quoted tool output, "
    "filler. Be concise and dense — 4-12 sentences."
)


async def summarize(
    model,
    messages: list[BaseMessage],
    *,
    instructions: str | None = None,
) -> SummaryResult:
    """Summarize `messages` via `model`. Raises CompactionError on failure."""
    system_text = _DEFAULT_SYSTEM
    if instructions:
        system_text = f"{system_text}\n\nAdditional guidance from caller:\n{instructions}"
    transcript = _render_transcript(messages)
    prompt: list[BaseMessage] = [
        SystemMessage(content=system_text),
        HumanMessage(content=f"Summarize this transcript:\n\n{transcript}"),
    ]
    try:
        response = await model.ainvoke(prompt)
    except Exception as exc:  # noqa: BLE001 — provider exceptions are heterogeneous
        raise CompactionError(str(exc), cause=exc) from exc

    text = response.content if isinstance(response.content, str) else _flatten(response.content)
    usage = dict(getattr(response, "usage_metadata", None) or {})
    model_id = getattr(model, "model_name", None) or getattr(model, "model", "unknown")
    return SummaryResult(text=text, model_id=str(model_id), usage=usage)


def _render_transcript(messages: list[BaseMessage]) -> str:
    lines = []
    for m in messages:
        role = getattr(m, "type", "msg")
        content = m.content if isinstance(m.content, str) else _flatten(m.content)
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


def _flatten(content) -> str:
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)
