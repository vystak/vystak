"""Tests for Transport schema models."""

import pytest
from pydantic import ValidationError
from vystak.schema import (
    HttpConfig,
    NatsConfig,
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


class TestNatsConfig:
    def test_defaults(self):
        c = NatsConfig()
        assert c.type == "nats"
        assert c.jetstream is True
        assert c.subject_prefix == "vystak"
        assert c.stream_name is None
        assert c.max_message_size_mb == 1


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
