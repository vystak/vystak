"""Three-tier token estimation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

EstimateMethod = Literal["early_out", "pre_flight", "chars_div_4"]

# Below this fraction of the trigger we trust the cheap early-out and skip
# the pre-flight call.
_EARLY_OUT_HEADROOM = 0.6


@dataclass(frozen=True)
class EstimateResult:
    tokens: int
    method: EstimateMethod


async def estimate_tokens(
    messages: list[BaseMessage],
    *,
    model,
    last_input_tokens: int | None,
    trigger_pct: float,
    context_window: int,
) -> EstimateResult:
    """Best-effort estimate of the prompt size for `messages`."""
    threshold = int(trigger_pct * context_window)
    if last_input_tokens is not None:
        cheap = last_input_tokens + _chars_div_4(messages)
        if cheap < int(threshold * _EARLY_OUT_HEADROOM):
            return EstimateResult(tokens=cheap, method="early_out")

    try:
        n = await model.aget_num_tokens_from_messages(messages)
        return EstimateResult(tokens=int(n), method="pre_flight")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "vystak.compaction.tokens.fallback chars_div_4 reason=%s",
            exc,
        )
        return EstimateResult(tokens=_chars_div_4(messages), method="chars_div_4")


def _chars_div_4(messages: list[BaseMessage]) -> int:
    total = 0
    for m in messages:
        if isinstance(m.content, str):
            total += len(m.content)
        elif isinstance(m.content, list):
            for block in m.content:
                if isinstance(block, dict):
                    total += len(str(block.get("text", "")))
                else:
                    total += len(str(block))
    return total // 4
