"""Tests for the agent runtime's OTel init."""

from __future__ import annotations

import importlib

import pytest


def _reload_module():
    """Reload the telemetry module so the in-process ``_initialized``
    flag resets between tests."""
    from _vystak.runtime import telemetry

    importlib.reload(telemetry)
    return telemetry


def _shutdown_global_tracer_provider() -> None:
    """Drain + close the global tracer provider so BatchSpanProcessor
    threads don't keep retrying exports past the test's lifetime
    (OTel's BatchSpanProcessor leaks errors to stderr otherwise)."""
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        shutdown = getattr(provider, "shutdown", None)
        if shutdown is not None:
            shutdown()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _cleanup_otel():
    """Ensure each test starts and ends with a quiesced OTel state."""
    yield
    _shutdown_global_tracer_provider()


def test_init_returns_none_without_endpoint(monkeypatch):
    """No OTEL_EXPORTER_OTLP_ENDPOINT → init is a clean no-op."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    telemetry = _reload_module()
    assert telemetry.init_telemetry() is None


def test_instrument_app_noop_without_endpoint(monkeypatch):
    """instrument_app(app) is a no-op when telemetry isn't configured."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    telemetry = _reload_module()

    class _FakeApp:
        # If instrumented, FastAPIInstrumentor would mutate state on the
        # app. We just need to confirm we don't try to import OTel.
        pass

    telemetry.instrument_app(_FakeApp())  # must not raise


def test_init_idempotent_when_endpoint_set(monkeypatch):
    """Second call returns None even if the env stays set."""
    pytest.importorskip("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
    pytest.importorskip("opentelemetry.instrumentation.fastapi")

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "vystak-test")
    telemetry = _reload_module()
    first = telemetry.init_telemetry()
    second = telemetry.init_telemetry()
    assert first is not None
    assert second is None
    provider, fastapi_instrumentor_cls = first
    assert provider is not None
    assert fastapi_instrumentor_cls is not None


def test_init_uses_explicit_service_name(monkeypatch):
    """An explicit service_name beats OTEL_SERVICE_NAME from env."""
    pytest.importorskip("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "from-env")
    telemetry = _reload_module()
    result = telemetry.init_telemetry(service_name="explicit-arg")
    assert result is not None
    provider, _ = result
    assert provider.resource.attributes["service.name"] == "explicit-arg"
