"""LangChain callback that publishes GenAI token-usage telemetry.

Hooks ``on_chat_model_start`` / ``on_chat_model_end`` to:

* Record an OTel histogram metric ``gen_ai.client.token.usage`` (one
  data point per token-direction: ``input`` / ``output`` / ``cache_read``
  / ``cache_creation``) — for fleet-wide usage dashboards.
* Record ``gen_ai.client.operation.duration`` (seconds, derived from
  the start/end callback delta).
* Stamp the same numbers as attributes on the active OTel span — so a
  Jaeger/Tempo trace can show per-call usage without crossing services.

Token attributes follow the OTel GenAI semantic conventions:
``gen_ai.usage.input_tokens``, ``gen_ai.usage.output_tokens``,
``gen_ai.usage.cache_read_input_tokens``,
``gen_ai.usage.cache_creation_input_tokens``,
``gen_ai.request.model``, ``gen_ai.system``.

Reads ``usage_metadata`` off the AIMessage in the model response — the
LangChain v1 standard shape (`input_tokens`, `output_tokens`,
``input_token_details``). Falls back to ``llm_output['usage']`` when
the provider hasn't surfaced standard metadata.

Safe to instantiate in containers that don't have OTel installed: the
constructor degrades to a silent no-op handler.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

logger = logging.getLogger("vystak.runtime.token_usage")

_GEN_AI_SYSTEM = "anthropic"  # Vystak agents talk to anthropic-compat endpoints


def _try_import_otel():
    try:
        from opentelemetry import metrics, trace

        return metrics, trace
    except ImportError:
        return None, None


class _NoOpCallback:
    """Returned in place of TokenUsageCallback when OTel is unavailable.

    Implements the ``BaseCallbackHandler`` surface as no-ops so callers
    can register it unconditionally.
    """

    def on_chat_model_start(self, *_a: Any, **_kw: Any) -> None:
        return None

    def on_llm_end(self, *_a: Any, **_kw: Any) -> None:
        return None

    def on_chat_model_end(self, *_a: Any, **_kw: Any) -> None:
        return None


def build_token_usage_callback() -> Any:
    """Return a configured TokenUsageCallback, or a no-op when OTel is absent.

    The handler reads the meter and tracer at construction time — call
    this *after* ``init_telemetry`` so the global providers are wired.
    """
    metrics, trace = _try_import_otel()
    if metrics is None or trace is None:
        return _NoOpCallback()

    try:
        from langchain_core.callbacks import BaseCallbackHandler
    except ImportError:  # pragma: no cover
        logger.warning(
            "langchain_core unavailable; TokenUsageCallback disabled",
        )
        return _NoOpCallback()

    meter = metrics.get_meter("vystak.runtime.token_usage")

    token_histogram = meter.create_histogram(
        name="gen_ai.client.token.usage",
        description="Number of tokens used in the request and response",
        unit="{token}",
    )
    duration_histogram = meter.create_histogram(
        name="gen_ai.client.operation.duration",
        description="Duration of the GenAI client operation",
        unit="s",
    )

    class TokenUsageCallback(BaseCallbackHandler):
        def __init__(self) -> None:
            self._starts: dict[UUID, float] = {}

        def on_chat_model_start(
            self,
            serialized: dict,
            messages: list,
            *,
            run_id: UUID,
            parent_run_id: UUID | None = None,
            tags: list[str] | None = None,
            metadata: dict | None = None,
            **kwargs: Any,
        ) -> None:
            self._starts[run_id] = time.monotonic()

        def on_llm_end(
            self,
            response: Any,
            *,
            run_id: UUID,
            parent_run_id: UUID | None = None,
            **kwargs: Any,
        ) -> None:
            start = self._starts.pop(run_id, None)
            duration = time.monotonic() - start if start is not None else None

            usage, model_name = _extract_usage(response)
            if not usage:
                return

            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            details = usage.get("input_token_details") or {}
            cache_read = int(details.get("cache_read") or 0)
            cache_creation = int(details.get("cache_creation") or 0)

            attrs = {
                "gen_ai.system": _GEN_AI_SYSTEM,
                "gen_ai.request.model": model_name or "unknown",
            }

            # Histogram metrics — one data point per token-direction.
            for direction, value in (
                ("input", input_tokens),
                ("output", output_tokens),
                ("cache_read", cache_read),
                ("cache_creation", cache_creation),
            ):
                if value:
                    token_histogram.record(
                        value,
                        attributes={**attrs, "gen_ai.token.type": direction},
                    )

            if duration is not None:
                duration_histogram.record(duration, attributes=attrs)

            # Span attributes — visible on whichever span is active when
            # the model returns (typically a `/a2a` server span on the
            # agent side).
            span = trace.get_current_span()
            if span is not None and span.is_recording():
                span.set_attribute("gen_ai.system", _GEN_AI_SYSTEM)
                if model_name:
                    span.set_attribute("gen_ai.request.model", model_name)
                if input_tokens:
                    span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
                if output_tokens:
                    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
                if cache_read:
                    span.set_attribute(
                        "gen_ai.usage.cache_read_input_tokens", cache_read,
                    )
                if cache_creation:
                    span.set_attribute(
                        "gen_ai.usage.cache_creation_input_tokens", cache_creation,
                    )

    return TokenUsageCallback()


def _extract_usage(response: Any) -> tuple[dict, str | None]:
    """Pull standardized usage_metadata + model name off an LLMResult.

    Prefers LangChain v1's standard ``usage_metadata`` on the AIMessage
    (input_tokens, output_tokens, input_token_details). Falls back to
    ``llm_output`` shapes used by older provider integrations.
    """
    model_name: str | None = None
    llm_output = getattr(response, "llm_output", None) or {}
    if isinstance(llm_output, dict):
        model_name = llm_output.get("model_name") or llm_output.get("model")

    generations = getattr(response, "generations", None) or []
    for gen_list in generations:
        for gen in gen_list:
            message = getattr(gen, "message", None)
            usage = getattr(message, "usage_metadata", None)
            if isinstance(usage, dict) and usage:
                # response_metadata may carry a more specific model name.
                resp_meta = getattr(message, "response_metadata", None) or {}
                if isinstance(resp_meta, dict):
                    model_name = (
                        resp_meta.get("model")
                        or resp_meta.get("model_name")
                        or model_name
                    )
                return usage, model_name

    # Older fallback: token_usage / usage block on llm_output.
    if isinstance(llm_output, dict):
        usage = llm_output.get("usage") or llm_output.get("token_usage") or {}
        if isinstance(usage, dict) and usage:
            normalized = {
                "input_tokens": usage.get("input_tokens")
                or usage.get("prompt_tokens"),
                "output_tokens": usage.get("output_tokens")
                or usage.get("completion_tokens"),
                "input_token_details": {
                    "cache_read": usage.get("cache_read_input_tokens"),
                    "cache_creation": usage.get("cache_creation_input_tokens"),
                },
            }
            return normalized, model_name

    return {}, model_name
