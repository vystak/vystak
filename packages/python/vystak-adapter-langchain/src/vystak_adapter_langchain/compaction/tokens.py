"""Three-tier token estimation."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

EstimateMethod = Literal["early_out", "pre_flight", "pre_flight_sync", "chars_div_4"]

# Below this fraction of the trigger we trust the cheap early-out and skip
# the pre-flight call.
_EARLY_OUT_HEADROOM = 0.6

# Module-level state: which provider tokenizer paths exist on this model.
# Probed once on the first call and cached so we don't hammer logs every turn.
_TOKENIZER_PROBE_CACHE: dict[int, str] = {}


@dataclass(frozen=True)
class EstimateResult:
    tokens: int
    method: EstimateMethod


def _probe_tokenizer(model) -> str:
    """Return which tokenizer path to use for `model`: 'async', 'sync', or 'none'.

    Result cached per-model-id so we only probe (and log) once.
    """
    key = id(model)
    cached = _TOKENIZER_PROBE_CACHE.get(key)
    if cached is not None:
        return cached
    if hasattr(model, "aget_num_tokens_from_messages"):
        result = "async"
    elif hasattr(model, "get_num_tokens_from_messages"):
        result = "sync"
    else:
        result = "none"
        logger.info(
            "vystak.compaction.tokens: %s exposes neither aget_num_tokens_from_messages "
            "nor get_num_tokens_from_messages — falling back to chars/4 estimate.",
            type(model).__name__,
        )
    _TOKENIZER_PROBE_CACHE[key] = result
    return result


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

    path = _probe_tokenizer(model)
    if path == "async":
        try:
            n = await model.aget_num_tokens_from_messages(messages)
            return EstimateResult(tokens=int(n), method="pre_flight")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "vystak.compaction.tokens.async_failed reason=%s", exc
            )
    elif path == "sync":
        try:
            # Run sync tokenizer in a worker thread to avoid blocking the loop.
            n = await asyncio.to_thread(model.get_num_tokens_from_messages, messages)
            return EstimateResult(tokens=int(n), method="pre_flight_sync")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "vystak.compaction.tokens.sync_failed reason=%s", exc
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
