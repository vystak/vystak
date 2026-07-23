"""HeartbeatPlugin — codegen for the vystak-heartbeat container."""

from __future__ import annotations

import json
from typing import Any

from vystak.providers.base import FileBundle

from vystak_heartbeat.server_template import DOCKERFILE, REQUIREMENTS


def build_bundle(
    *,
    agents_with_heartbeat: list[Any],            # list of Agent
    agent_addresses: dict[str, str],              # canonical_name → /a2a URL
    channel_addresses: dict[str, str],            # canonical_name → http://host:port
    transport_cfg: dict,                          # {"type": "http"|"nats", ...}
    session_store_cfg: dict,                      # {"type": "memory"|"sqlite", ...}
) -> FileBundle:
    routes: dict[str, dict] = {}
    for agent in agents_with_heartbeat:
        if agent.heartbeat is None:
            continue
        target = agent.heartbeat.target_channel
        routes[agent.name] = {
            "canonical": agent.canonical_name,
            "address": agent_addresses[agent.canonical_name],
            "heartbeat": agent.heartbeat.model_dump(mode="json"),
            "delivery": {
                "channel_canonical_name": target,
                "url": channel_addresses.get(target, ""),
            },
        }

    service_config = {
        "transport": transport_cfg,
        "session_store": session_store_cfg,
        "agent_addresses": agent_addresses,
    }

    return FileBundle(
        files={
            "Dockerfile": DOCKERFILE,
            "requirements.txt": REQUIREMENTS,
            "service_config.json": json.dumps(service_config, indent=2),
            "routes.json": json.dumps(routes, indent=2),
        },
        entrypoint="python -m vystak_heartbeat",
    )
