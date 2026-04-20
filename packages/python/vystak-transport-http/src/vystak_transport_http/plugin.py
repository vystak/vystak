"""HttpTransportPlugin — registers the HTTP transport with providers."""

from __future__ import annotations

from vystak.providers.base import GeneratedCode, TransportPlugin
from vystak.schema import Platform, Transport
from vystak.schema.agent import Agent
from vystak.transport.naming import slug


class HttpTransportPlugin(TransportPlugin):
    """HTTP transport plugin. No broker to provision; listener handled by
    the generated FastAPI app already."""

    type = "http"

    def build_provision_nodes(self, transport: Transport, platform: Platform):
        return []

    def generate_env_contract(self, transport: Transport, context: dict) -> dict[str, str]:
        return {"VYSTAK_TRANSPORT_TYPE": "http"}

    def generate_listener_code(self, transport: Transport) -> GeneratedCode | None:
        return None

    def resolve_address_for(self, agent: Agent, platform: Platform) -> str:
        """Return the Docker-style DNS URL for an agent.

        Matches the Docker provider's container naming (`vystak-{agent_name}`)
        since that's what DockerAgentNode actually creates and what Docker's
        network DNS resolves on the shared vystak-net. Namespace is not
        encoded in the URL because the container name is namespace-flat today
        — v1 deployments are single-namespace per Docker host.

        Azure providers override this (or use their own plugin) since the
        ingress hostname isn't derivable from the name alone.
        """
        port = agent.port or 8000
        return f"http://vystak-{slug(agent.name)}:{port}/a2a"
