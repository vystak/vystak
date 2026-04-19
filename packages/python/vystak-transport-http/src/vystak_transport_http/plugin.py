"""HttpTransportPlugin — registers the HTTP transport with providers."""

from __future__ import annotations

from vystak.providers.base import GeneratedCode, TransportPlugin
from vystak.schema import Platform, Transport


class HttpTransportPlugin(TransportPlugin):
    """HTTP transport plugin. No broker to provision; listener handled by
    the generated FastAPI app already."""

    type = "http"

    def build_provision_nodes(self, transport: Transport, platform: Platform):
        return []

    def generate_env_contract(
        self, transport: Transport, context: dict
    ) -> dict[str, str]:
        return {"VYSTAK_TRANSPORT_TYPE": "http"}

    def generate_listener_code(self, transport: Transport) -> GeneratedCode | None:
        return None
