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


class _FakeEvent:
    def __init__(self, name: str, attributes: dict) -> None:
        self.name = name
        self.attributes = attributes


class _FakeSpan:
    """Stand-in for ``_Span`` exposing the surface our processor uses.

    Mirrors the SDK's invariant: by the time ``_on_ending`` fires, the
    span's ``_end_time`` is already set, so ``set_status`` would warn and
    no-op. The processor mutates ``_status`` directly; we test that
    directly.
    """

    def __init__(self, name: str, events: list, status_code: str = "ERROR") -> None:
        from opentelemetry.trace import Status, StatusCode

        self.name = name
        self.events = events
        self._status = Status(getattr(StatusCode, status_code))


def _make_proc():
    pytest.importorskip("opentelemetry.sdk.trace")
    telemetry = _reload_module()
    return telemetry._make_suppressor_class()()


def test_suppressor_downgrades_a2a_queueshutdown_spans():
    """QueueShutDown on a2a event_queue paths → status reset to UNSET."""
    from opentelemetry.trace import StatusCode

    proc = _make_proc()
    span = _FakeSpan(
        name="a2a.server.events.event_queue_v2.EventQueueSource.dequeue_event",
        events=[
            _FakeEvent("exception", {"exception.type": "culsans.QueueShutDown"}),
        ],
    )
    proc._on_ending(span)
    assert span._status.status_code == StatusCode.UNSET


def test_suppressor_keeps_unrelated_errors():
    """A real error on the same a2a path stays ERROR."""
    from opentelemetry.trace import StatusCode

    proc = _make_proc()
    span = _FakeSpan(
        name="a2a.server.events.event_queue_v2.EventQueueSource.dequeue_event",
        events=[
            _FakeEvent("exception", {"exception.type": "ValueError"}),
        ],
    )
    proc._on_ending(span)
    assert span._status.status_code == StatusCode.ERROR


def test_suppressor_keeps_mixed_errors():
    """Benign + real exception in same span → still ERROR."""
    from opentelemetry.trace import StatusCode

    proc = _make_proc()
    span = _FakeSpan(
        name="a2a.server.events.event_queue_v2.EventQueueSource.dequeue_event",
        events=[
            _FakeEvent("exception", {"exception.type": "culsans.QueueShutDown"}),
            _FakeEvent("exception", {"exception.type": "RuntimeError"}),
        ],
    )
    proc._on_ending(span)
    assert span._status.status_code == StatusCode.ERROR


def test_suppressor_ignores_non_a2a_spans():
    """QueueShutDown on a non-a2a span path is left alone."""
    from opentelemetry.trace import StatusCode

    proc = _make_proc()
    span = _FakeSpan(
        name="some.other.module.method",
        events=[
            _FakeEvent("exception", {"exception.type": "culsans.QueueShutDown"}),
        ],
    )
    proc._on_ending(span)
    assert span._status.status_code == StatusCode.ERROR


def test_suppressor_no_op_on_clean_spans():
    """Span with no exception events is left alone."""
    from opentelemetry.trace import StatusCode

    proc = _make_proc()
    span = _FakeSpan(
        name="a2a.server.events.event_queue_v2.EventQueueSource.dequeue_event",
        events=[],
        status_code="OK",
    )
    proc._on_ending(span)
    assert span._status.status_code == StatusCode.OK
