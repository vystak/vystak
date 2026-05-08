"""Transport wiring helpers for the Docker provider.

Provides:
- ``get_transport_plugin(type)`` — factory that returns an instantiated
  ``TransportPlugin`` for the given transport type string.
- ``build_peer_routes(agents, plugin, platform)`` — builds the
  ``{short_name: {canonical, address, card_url}}`` map for a list of agents.
- ``build_routes_json(agents, plugin, platform)`` — serialises the map to a
  JSON string suitable for injection as ``VYSTAK_ROUTES_JSON``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vystak.providers.base import TransportPlugin
    from vystak.schema.agent import Agent
    from vystak.schema.platform import Platform


def _build_transport_plugin_registry() -> dict[str, type]:
    """Build the transport-type → plugin-class registry.

    Imports are done lazily inside the function so the docker provider package
    doesn't hard-import every optional transport package at module load time.
    """
    from vystak_transport_http import HttpTransportPlugin
    from vystak_transport_nats import NatsTransportPlugin

    return {
        "http": HttpTransportPlugin,
        "nats": NatsTransportPlugin,
    }


_TRANSPORT_PLUGINS: dict[str, type] = _build_transport_plugin_registry()


def get_transport_plugin(transport_type: str) -> TransportPlugin:
    """Return an instantiated ``TransportPlugin`` for *transport_type*.

    Supported types: ``"http"``, ``"nats"``.

    Raises ``KeyError`` for unknown transport types.
    """
    try:
        cls = _TRANSPORT_PLUGINS[transport_type]
    except KeyError:
        known = ", ".join(sorted(_TRANSPORT_PLUGINS))
        raise KeyError(f"Unknown transport type {transport_type!r}. Known types: {known}") from None

    return cls()


def build_peer_routes(
    agents: list[Agent],
    plugin: TransportPlugin,
    platform: Platform,
) -> dict[str, dict[str, str]]:
    """Build the peer-route map for *agents*.

    Returns a dict keyed by agent *short name* (not canonical name):

    .. code-block:: python

        {
            "agent-a": {
                "canonical": "agent-a.agents.default",
                "address": "http://vystak-agent-a:8000/a2a",
                "card_url": "http://vystak-agent-a:8000/.well-known/agent.json",
            },
            ...
        }

    ``address`` is the JSON-RPC endpoint (kept for back-compat with the
    legacy hand-rolled httpx subagent client). ``card_url`` is the agent
    card URL the new a2a-sdk client resolves before calling
    ``send_message``. The card URL is derived from ``address`` by replacing
    the trailing ``/a2a`` with ``/.well-known/agent.json``.
    """
    routes: dict[str, dict[str, str]] = {}
    for agent in agents:
        address = plugin.resolve_address_for(agent, platform)
        card_url = _derive_card_url(address)
        routes[agent.name] = {
            "canonical": agent.canonical_name,
            "address": address,
            "card_url": card_url,
        }
    return routes


def _derive_card_url(address: str) -> str:
    """Convert a transport address to the agent-card URL.

    For HTTP this is `http://host:port/a2a` -> `http://host:port/.well-known/agent.json`.
    NAT-backed addresses (`nats://...`) don't have a card URL; we still emit
    the suffix-stripped form so the field is always present, but a NATS
    consumer is expected to resolve cards out-of-band.
    """
    return address.rstrip("/").removesuffix("/a2a") + "/.well-known/agent.json"


def build_routes_json(
    agents: list[Agent],
    plugin: TransportPlugin,
    platform: Platform,
) -> str:
    """Serialise ``build_peer_routes`` output to a compact JSON string.

    This is the value injected as ``VYSTAK_ROUTES_JSON`` into each container's
    environment.
    """
    return json.dumps(build_peer_routes(agents, plugin, platform), separators=(",", ":"))
