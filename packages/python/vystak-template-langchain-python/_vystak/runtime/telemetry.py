"""OpenTelemetry initialization for agent containers.

Reads ``OTEL_*`` env vars set by the Docker provider when
``Platform.telemetry`` is enabled. Auto-instruments FastAPI + httpx
so HTTP requests carry W3C traceparent headers automatically; the
NATS path adds traceparent injection manually (see ``subagents.py``,
``nats_bridge.py``) since NATS isn't covered by upstream OTel
auto-instrumentation.

Idempotent — safe to call multiple times. Containers without
telemetry (``OTEL_EXPORTER_OTLP_ENDPOINT`` unset) skip the init
entirely and pay no instrumentation cost.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("vystak.runtime.telemetry")

_initialized = False


def _make_suppressor_class() -> Any:
    """Build the SpanProcessor subclass lazily.

    Importing OTel at module load would force the dependency on consumers
    that don't enable telemetry. Defer until ``init_telemetry`` is called.
    """
    from opentelemetry.sdk.trace import SpanProcessor
    from opentelemetry.trace import Status, StatusCode

    class _SuppressBenignA2AErrors(SpanProcessor):
        """Downgrade a2a-sdk control-flow exceptions from ERROR to UNSET.

        a2a-sdk's ``@trace_function`` decorator marks every span ERROR when
        its wrapped function raises — including ``culsans.QueueShutDown``,
        which the SDK itself uses as a control-flow signal for end-of-stream
        on its event queues (caught and explicitly suppressed at
        ``a2a.server.events.event_queue_v2`` L115/L191/L310). Those caught
        exceptions surface as red errors in Jaeger even though no real
        failure occurred. Mutate status on the ``_on_ending`` hook (the
        span is still mutable then) when the only recorded exception is a
        known benign control-flow signal.
        """

        _BENIGN_EXCEPTIONS = frozenset({"culsans.QueueShutDown"})
        _MATCHING_PREFIXES = ("a2a.server.events.event_queue_v2",)

        def _on_ending(self, span: Any) -> None:
            if not span.name.startswith(self._MATCHING_PREFIXES):
                return
            events = getattr(span, "events", ())
            if not events:
                return
            saw_exception = False
            for event in events:
                if event.name != "exception":
                    continue
                saw_exception = True
                exc_type = (
                    event.attributes.get("exception.type")
                    if event.attributes else None
                )
                if exc_type not in self._BENIGN_EXCEPTIONS:
                    return
            if not saw_exception:
                return
            # `set_status` is gated by `@_check_span_ended` and OTel's SDK
            # sets `_end_time` *before* dispatching `_on_ending`, so the
            # public setter would warn + no-op here. Mutate the private
            # attribute directly — both this processor and the downstream
            # BatchSpanProcessor/exporter read the same object.
            span._status = Status(StatusCode.UNSET)  # noqa: SLF001

    return _SuppressBenignA2AErrors


def init_telemetry(service_name: str | None = None) -> Any:
    """Bootstrap an OTLP-gRPC tracer provider + httpx auto-instrumentation.

    Returns ``(provider, FastAPIInstrumentor)`` on first successful init,
    ``None`` on subsequent calls or when ``OTEL_EXPORTER_OTLP_ENDPOINT``
    is unset. Caller should pass the result to ``instrument_app(app, ...)``
    to wire FastAPI server-span generation.
    """
    global _initialized
    if _initialized:
        return None
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as e:
        # Container was deployed without the OTel deps — treat as soft fail.
        # Should not happen in practice (Docker provider only sets the env
        # when telemetry is configured, and the template ships the deps),
        # but a partial install shouldn't crash the agent at boot.
        logger.warning(
            "OTel SDK packages unavailable; telemetry disabled (%s)", e,
        )
        return None

    resource = Resource.create({
        "service.name": service_name or os.environ.get(
            "OTEL_SERVICE_NAME", "vystak-agent",
        ),
    })
    provider = TracerProvider(resource=resource)
    # `_on_ending` fires before the span closes, so this mutation is visible
    # to the BatchSpanProcessor's exporter regardless of registration order.
    provider.add_span_processor(_make_suppressor_class()())
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)),
    )
    trace.set_tracer_provider(provider)

    # Auto-instrument outbound httpx — server-span instrumentation is
    # caller-driven (instrument_app() below).
    HTTPXClientInstrumentor().instrument()

    _initialized = True
    logger.info(
        "OTel telemetry initialized: service=%s endpoint=%s",
        resource.attributes.get("service.name"),
        endpoint,
    )
    return provider, FastAPIInstrumentor


def instrument_app(app: Any, service_name: str | None = None) -> None:
    """Initialize OTel (if not already) + wire FastAPI server-span generation.

    Safe to call after ``init_telemetry`` has already run elsewhere —
    re-imports FastAPIInstrumentor and applies it. No-op when telemetry
    isn't configured (``OTEL_EXPORTER_OTLP_ENDPOINT`` unset).
    """
    init_telemetry(service_name)
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:
        return
    FastAPIInstrumentor.instrument_app(app)
