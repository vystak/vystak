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
    """Initialize OTel and wire FastAPI server-span generation.

    Call after the FastAPI app is constructed. No-op when telemetry
    isn't configured (``OTEL_EXPORTER_OTLP_ENDPOINT`` unset).
    """
    result = init_telemetry(service_name)
    if result is None:
        return
    _, FastAPIInstrumentor = result
    FastAPIInstrumentor.instrument_app(app)
