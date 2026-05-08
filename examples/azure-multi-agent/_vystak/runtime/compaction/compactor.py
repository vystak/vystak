"""Layer 3 — threshold-driven summarize."""

from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

SUMMARY_PROMPT = (
    "You are summarizing a conversation between a user and an AI assistant. "
    "Produce a concise summary that preserves all facts, decisions, and "
    "context the assistant would need to continue the conversation. "
    "Do not include filler, greetings, or meta-commentary."
)


class ThresholdCompactor:
    def __init__(self, agent: Any, store: Any, summarizer: Any) -> None:
        self.agent = agent
        self.store = store
        self.summarizer = summarizer

    async def maybe_compact(
        self,
        thread_id: str,
        messages: list[BaseMessage],
        prefill_token_estimate: int,
    ) -> list[BaseMessage]:
        cmp = self.agent.compaction
        threshold = int(cmp.trigger_pct * cmp.context_window)
        if prefill_token_estimate < threshold:
            return messages

        if await self._idempotency_blocks(thread_id, messages):
            return messages

        keep_count = max(1, int(len(messages) * cmp.keep_recent_pct))
        older = messages[:-keep_count]
        recent = messages[-keep_count:]
        if not older:
            return messages

        summary_text = await self._summarize(older)
        await self._persist(thread_id, summary_text, len(older))

        return [
            SystemMessage(content=f"[Summary of earlier conversation]\n{summary_text}"),
            *recent,
        ]

    async def _idempotency_blocks(self, thread_id: str, messages: list[BaseMessage]) -> bool:
        latest = await self.store.latest(thread_id)
        if not latest:
            return False
        age = (datetime.now(UTC) - latest["created_at"]).total_seconds()
        coverage = latest["covered_message_count"] / max(len(messages), 1)
        return age < 60 or coverage >= 0.7

    async def _summarize(self, older: list[BaseMessage]) -> str:
        text = "\n".join(_render(m) for m in older)
        prompt = [SystemMessage(content=SUMMARY_PROMPT), HumanMessage(content=text)]
        result = await self.summarizer.ainvoke(prompt)
        return result.content if isinstance(result, AIMessage) else str(result)

    async def _persist(self, thread_id: str, summary: str, covered: int) -> None:
        latest = await self.store.latest(thread_id)
        gen = (latest["generation"] + 1) if latest else 1
        await self.store.write(
            thread_id=thread_id,
            generation=gen,
            summary=summary,
            created_at=datetime.now(UTC),
            covered_message_count=covered,
        )


def _render(m: BaseMessage) -> str:
    return f"{getattr(m, 'type', 'message')}: {m.content}"
