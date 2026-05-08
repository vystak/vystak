"""Tests for the channel runtime's OTel init."""

from __future__ import annotations

import importlib

import pytest


def _reload_module():
    from vystak_channel_runtime import telemetry

    importlib.reload(telemetry)
    return telemetry


def _shutdown_global_tracer_provider() -> None:
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
    yield
    _shutdown_global_tracer_provider()


def test_init_returns_none_without_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    telemetry = _reload_module()
    assert telemetry.init_telemetry() is None


def test_instrument_app_noop_without_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    telemetry = _reload_module()

    class _FakeApp:
        pass

    telemetry.instrument_app(_FakeApp())  # must not raise


def test_init_idempotent_when_endpoint_set(monkeypatch):
    pytest.importorskip("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
    pytest.importorskip("opentelemetry.instrumentation.fastapi")

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "vystak-channel-test")
    telemetry = _reload_module()
    first = telemetry.init_telemetry()
    second = telemetry.init_telemetry()
    assert first is not None
    assert second is None


def test_init_uses_explicit_service_name(monkeypatch):
    pytest.importorskip("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "from-env")
    telemetry = _reload_module()
    result = telemetry.init_telemetry(service_name="explicit-arg")
    assert result is not None
    provider, _ = result
    assert provider.resource.attributes["service.name"] == "explicit-arg"
