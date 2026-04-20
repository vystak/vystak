"""NatsTransportPlugin — registers the NATS transport with providers."""

from __future__ import annotations

from vystak.providers.base import GeneratedCode, TransportPlugin
from vystak.schema import Platform, Transport
from vystak.schema.agent import Agent
from vystak.transport.naming import slug


class NatsTransportPlugin(TransportPlugin):
    type = "nats"

    def build_provision_nodes(self, transport: Transport, platform: Platform):
        # The Docker provider constructs the actual NatsServerNode; this
        # plugin just signals that a broker is needed. The provider
        # checks `plugin.type == "nats"` and knows to add its own
        # NatsServerNode with platform-specific config.
        return []

    def generate_env_contract(self, transport: Transport, context: dict) -> dict[str, str]:
        # context may include a resolved NATS URL from the provider's
        # provisioning step. For v1 Docker: "nats://vystak-nats:4222".
        env = {"VYSTAK_TRANSPORT_TYPE": "nats"}
        if "nats_url" in context:
            env["VYSTAK_NATS_URL"] = context["nats_url"]
        if transport.config and getattr(transport.config, "subject_prefix", None):
            env["VYSTAK_NATS_SUBJECT_PREFIX"] = transport.config.subject_prefix
        return env

    def generate_listener_code(self, transport: Transport) -> GeneratedCode | None:
        # The generated server template's _build_transport_from_env already
        # handles the "nats" branch (see Task 5). Nothing extra to inject.
        return None

    def resolve_address_for(self, agent: Agent, platform: Platform) -> str:
        # Matches NatsTransport.resolve_address.
        prefix = "vystak"
        if platform.transport and platform.transport.config:
            prefix = getattr(platform.transport.config, "subject_prefix", prefix)
        ns = slug(platform.namespace or "default")
        return f"{prefix}.{ns}.agents.{slug(agent.name)}.tasks"
