"""Layer 3 — threshold pre-call summarize with idempotency guard."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from langchain_core.messages import BaseMessage, SystemMessage

from vystak_adapter_langchain.compaction.coverage import (
    fraction_covered,
    message_id,
)
from vystak_adapter_langchain.compaction.errors import CompactionError
from vystak_adapter_langchain.compaction.metrics import (
    CompactionMetrics,
    record_compaction,
    record_suppression,
)
from vystak_adapter_langchain.compaction.store import CompactionStore
from vystak_adapter_langchain.compaction.tokens import estimate_tokens

logger = logging.getLogger(__name__)

LAYER3_SUPPRESS_RECENT_PCT = 0.30
LAYER3_SUPPRESS_RECENT_SECONDS = 60


async def maybe_compact(
    messages: list[BaseMessage],
    *,
    model,
    last_input_tokens: int | None,
    context_window: int,
    trigger_pct: float,
    keep_recent_pct: float,
    target_tokens: int,
    summarizer,
    summarize_fn,
    compaction_store: CompactionStore,
    thread_id: str,
    metrics: CompactionMetrics | None = None,
) -> tuple[list[BaseMessage], str | None]:
    """Maybe replace older messages with a summary."""
    latest = await compaction_store.latest(thread_id)
    if latest is not None:
        already = fraction_covered(messages, up_to=latest.up_to_message_id)
        seconds_since = (
            datetime.now(UTC) - latest.created_at
        ).total_seconds()
        if (
            already >= 1 - LAYER3_SUPPRESS_RECENT_PCT
            or seconds_since < LAYER3_SUPPRESS_RECENT_SECONDS
        ):
            logger.debug(
                "vystak.compaction.threshold.suppressed thread_id=%s "
                "covered=%.2f seconds_since=%.0f",
                thread_id, already, seconds_since,
            )
            if metrics is not None:
                reason = "covered" if already >= 1 - LAYER3_SUPPRESS_RECENT_PCT else "recent"
                record_suppression(metrics, layer="layer3", reason=reason)
            return messages, None

    estimate = await estimate_tokens(
        messages,
        model=model,
        last_input_tokens=last_input_tokens,
        trigger_pct=trigger_pct,
        context_window=context_window,
    )
    if estimate.tokens < int(trigger_pct * context_window):
        return messages, None

    cutoff = max(1, int(len(messages) * (1 - keep_recent_pct)))
    older, recent = messages[:cutoff], messages[cutoff:]
    try:
        summary = await summarize_fn(summarizer, older)
    except CompactionError as exc:
        logger.warning(
            "vystak.compaction.threshold.fallback thread_id=%s reason=%s",
            thread_id, exc.reason,
        )
        truncated = _hard_truncate(messages, target_tokens)
        if metrics is not None:
            record_compaction(
                metrics, layer="layer3", trigger="threshold",
                outcome="failed_fallback",
            )
        return truncated, exc.reason

    last_id = message_id(older[-1]) or ""
    await compaction_store.write(
        thread_id=thread_id,
        summary_text=summary.text,
        up_to_message_id=last_id,
        trigger="threshold",
        summarizer_model=summary.model_id,
        usage=summary.usage,
    )
    if metrics is not None:
        record_compaction(
            metrics, layer="layer3", trigger="threshold", outcome="written",
            input_tokens=int(summary.usage.get("input_tokens", 0)),
            output_tokens=int(summary.usage.get("output_tokens", 0)),
            messages_compacted=len(older),
        )
    return [SystemMessage(content=summary.text)] + recent, None


def _hard_truncate(
    messages: list[BaseMessage], target_tokens: int
) -> list[BaseMessage]:
    """Drop oldest messages until the chars/4 estimate fits target_tokens."""
    out = list(messages)
    target_chars = target_tokens * 4
    total = sum(len(m.content) if isinstance(m.content, str) else 0 for m in out)
    while out and total > target_chars and len(out) > 1:
        dropped = out.pop(0)
        if isinstance(dropped.content, str):
            total -= len(dropped.content)
    return out
