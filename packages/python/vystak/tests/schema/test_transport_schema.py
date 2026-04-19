"""Tests for Transport schema models."""

import pytest
from pydantic import ValidationError
from vystak.schema import (
    HttpConfig,
    NatsConfig,
    Platform,
    Provider,
    ServiceBusConfig,
    Transport,
    TransportConnection,
)


class TestTransport:
    def test_minimal_http(self):
        t = Transport(name="default", type="http")
        assert t.name == "default"
        assert t.type == "http"
        assert t.config is None
        assert t.connection is None

    def test_nats_with_config(self):
        t = Transport(
            name="bus",
            type="nats",
            config=NatsConfig(jetstream=True, subject_prefix="vystak"),
        )
        assert t.type == "nats"
        assert t.config.jetstream is True
        assert t.config.subject_prefix == "vystak"

    def test_service_bus_with_byo(self):
        t = Transport(
            name="bus",
            type="azure-service-bus",
            connection=TransportConnection(
                url_env="SB_URL",
                credentials_secret="sb-creds",
            ),
            config=ServiceBusConfig(namespace_name="my-sb-ns"),
        )
        assert t.connection.url_env == "SB_URL"
        assert t.config.namespace_name == "my-sb-ns"
        assert t.config.use_sessions is True

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            Transport(name="x", type="kafka")

    def test_canonical_name(self):
        t = Transport(name="bus", type="nats", namespace="prod")
        assert t.canonical_name == "bus.transports.prod"

    def test_canonical_name_default_namespace(self):
        t = Transport(name="bus", type="nats")
        assert t.canonical_name == "bus.transports.default"

    def test_mismatched_config_type_rejected(self):
        with pytest.raises(ValidationError, match="config.type"):
            Transport(name="bus", type="nats", config=HttpConfig())

    def test_matching_config_type_ok(self):
        t = Transport(name="bus", type="nats", config=NatsConfig())
        assert t.type == "nats"
        assert t.config.type == "nats"

    def test_no_config_ok(self):
        t = Transport(name="bus", type="http")
        assert t.config is None


class TestNatsConfig:
    def test_defaults(self):
        c = NatsConfig()
        assert c.type == "nats"
        assert c.jetstream is True
        assert c.subject_prefix == "vystak"
        assert c.stream_name is None
        assert c.max_message_size_mb == 1

    def test_max_message_size_must_be_positive(self):
        with pytest.raises(ValidationError):
            NatsConfig(max_message_size_mb=0)


class TestServiceBusConfig:
    def test_defaults(self):
        c = ServiceBusConfig()
        assert c.type == "azure-service-bus"
        assert c.use_sessions is True
        assert c.namespace_name is None


class TestHttpConfig:
    def test_defaults(self):
        c = HttpConfig()
        assert c.type == "http"


class TestTransportConnection:
    def test_both_optional(self):
        c = TransportConnection()
        assert c.url_env is None
        assert c.credentials_secret is None

    def test_byo(self):
        c = TransportConnection(url_env="FOO_URL", credentials_secret="foo-creds")
        assert c.url_env == "FOO_URL"
        assert c.credentials_secret == "foo-creds"


class TestPlatformTransport:
    def _provider(self) -> Provider:
        return Provider(name="docker", type="docker")

    def test_default_transport_synthesized(self):
        """Platform without an explicit transport gets a default-http."""
        p = Platform(name="main", type="docker", provider=self._provider())
        assert p.transport is not None
        assert p.transport.name == "default-http"
        assert p.transport.type == "http"

    def test_explicit_http_transport_preserved(self):
        p = Platform(
            name="main",
            type="docker",
            provider=self._provider(),
            transport=Transport(name="my-http", type="http"),
        )
        assert p.transport.name == "my-http"
        assert p.transport.type == "http"

    def test_explicit_nats_transport_preserved(self):
        p = Platform(
            name="aca",
            type="container-apps",
            provider=Provider(name="azure", type="azure"),
            transport=Transport(
                name="bus",
                type="nats",
                config=NatsConfig(jetstream=True),
            ),
        )
        assert p.transport.type == "nats"
        assert p.transport.config.jetstream is True

    def test_transport_config_mismatch_still_rejected(self):
        """The Transport-level validator (from Task 1) still fires when
        Transport is embedded in a Platform."""
        with pytest.raises(ValidationError, match="config.type"):
            Platform(
                name="main",
                type="docker",
                provider=self._provider(),
                transport=Transport(name="bus", type="nats", config=HttpConfig()),
            )

    def test_default_transport_is_a_new_instance_per_platform(self):
        """Two platforms should not share the same default-http instance —
        mutating one must not affect the other."""
        p1 = Platform(name="a", type="docker", provider=self._provider())
        p2 = Platform(name="b", type="docker", provider=self._provider())
        assert p1.transport is not p2.transport
