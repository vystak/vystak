"""OpenTelemetry initialization for channel containers.

Mirror of ``_vystak.runtime.telemetry`` (template-side). Reads
``OTEL_*`` env vars set by the Docker provider when
``Platform.telemetry`` is enabled. Auto-instruments FastAPI + httpx
so HTTP requests carry W3C traceparent automatically; the NATS path
adds traceparent injection manually in ``agent_client.NatsAgentClient``.

Idempotent — safe to call multiple times. Channels without telemetry
(``OTEL_EXPORTER_OTLP_ENDPOINT`` unset) skip the init entirely.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("vystak.channel.runtime.telemetry")

_initialized = False


def init_telemetry(service_name: str | None = None) -> Any:
    """Bootstrap an OTLP-gRPC tracer provider + httpx auto-instrumentation.

    Returns ``(provider, FastAPIInstrumentor)`` on first successful init,
    ``None`` on subsequent calls or when telemetry isn't configured.
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
        logger.warning(
            "OTel SDK packages unavailable; telemetry disabled (%s)", e,
        )
        return None

    resource = Resource.create({
        "service.name": service_name or os.environ.get(
            "OTEL_SERVICE_NAME", "vystak-channel",
        ),
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)),
    )
    trace.set_tracer_provider(provider)
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

    Safe to call after ``init_telemetry`` has already run elsewhere
    (e.g. the launcher) — re-imports the FastAPIInstrumentor and applies
    it. No-op when telemetry isn't configured.
    """
    # Run init in case it hasn't been initialized yet. If it was, the
    # global flag short-circuits and we still need to apply
    # FastAPIInstrumentor here, so we import it explicitly below.
    init_telemetry(service_name)
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:
        return
    FastAPIInstrumentor.instrument_app(app)
