"""Transport resource schema — declares how east-west A2A traffic flows."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TransportConnection(BaseModel):
    """BYO connection details for an externally-managed broker.

    When set, the provider will not provision broker infrastructure and will
    instead plumb these values through to agents and channels.
    """

    url_env: str | None = None
    credentials_secret: str | None = None


class HttpConfig(BaseModel):
    """HTTP transport config. Currently empty; reserved for future tuning."""

    type: Literal["http"] = "http"


class NatsConfig(BaseModel):
    """NATS transport config."""

    type: Literal["nats"] = "nats"
    jetstream: bool = True
    subject_prefix: str = "vystak"
    stream_name: str | None = None
    max_message_size_mb: int = 1


class ServiceBusConfig(BaseModel):
    """Azure Service Bus transport config."""

    type: Literal["azure-service-bus"] = "azure-service-bus"
    namespace_name: str | None = None
    use_sessions: bool = True


TransportType = Literal["http", "nats", "azure-service-bus"]
TransportConfig = HttpConfig | NatsConfig | ServiceBusConfig


class Transport(BaseModel):
    """Declares a transport for east-west A2A traffic on a Platform."""

    name: str
    type: TransportType
    namespace: str | None = None
    connection: TransportConnection | None = None
    config: TransportConfig | None = Field(default=None, discriminator="type")

    @property
    def canonical_name(self) -> str:
        ns = self.namespace or "default"
        return f"{self.name}.transports.{ns}"
