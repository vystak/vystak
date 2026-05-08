"""Tests for Telemetry schema model."""

import pytest
from pydantic import ValidationError
from vystak.schema import Platform, Provider, Telemetry


class TestTelemetry:
    def test_defaults(self):
        t = Telemetry()
        assert t.type == "jaeger"
        assert t.enabled is True
        assert t.endpoint is None

    def test_explicit_endpoint(self):
        t = Telemetry(endpoint="http://otel-collector.example.com:4317")
        assert t.enabled is True
        assert t.endpoint == "http://otel-collector.example.com:4317"

    def test_disabled(self):
        t = Telemetry(enabled=False)
        assert t.enabled is False

    def test_only_jaeger_type_supported(self):
        with pytest.raises(ValidationError):
            Telemetry(type="datadog")  # type: ignore[arg-type]


class TestPlatformTelemetryField:
    def _provider(self) -> Provider:
        return Provider(name="docker", type="docker")

    def test_platform_default_no_telemetry(self):
        p = Platform(name="local", type="docker", provider=self._provider())
        assert p.telemetry is None

    def test_platform_with_telemetry(self):
        p = Platform(
            name="local",
            type="docker",
            provider=self._provider(),
            telemetry=Telemetry(),
        )
        assert p.telemetry is not None
        assert p.telemetry.type == "jaeger"
        assert p.telemetry.enabled is True
