"""Transport wiring helpers for the Docker provider.

Provides:
- ``get_transport_plugin(type)`` — factory that returns an instantiated
  ``TransportPlugin`` for the given transport type string.
- ``build_peer_routes(agents, plugin, platform)`` — builds the
  ``{short_name: {canonical, address}}`` map for a list of agents.
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


def get_transport_plugin(transport_type: str) -> TransportPlugin:
    """Return an instantiated ``TransportPlugin`` for *transport_type*.

    Currently only ``"http"`` is registered.  Plan B will add ``"nats"`` here.

    Raises ``KeyError`` for unknown transport types.
    """
    from vystak_transport_http import HttpTransportPlugin

    _REGISTRY: dict[str, type] = {
        "http": HttpTransportPlugin,
    }

    try:
        cls = _REGISTRY[transport_type]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY))
        raise KeyError(
            f"Unknown transport type {transport_type!r}. Known types: {known}"
        ) from None

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
            },
            ...
        }

    The *address* is obtained by calling ``plugin.resolve_address_for`` so
    that the correct transport addressing scheme is used for each platform.
    """
    routes: dict[str, dict[str, str]] = {}
    for agent in agents:
        routes[agent.name] = {
            "canonical": agent.canonical_name,
            "address": plugin.resolve_address_for(agent, platform),
        }
    return routes


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
