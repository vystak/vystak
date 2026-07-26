"""HeartbeatPlugin — codegen for the vystak-heartbeat container."""

from __future__ import annotations

import json
from typing import Any

from vystak.providers.base import FileBundle

from vystak_heartbeat.server_template import DOCKERFILE, REQUIREMENTS


def build_bundle(
    *,
    agents_with_schedules: list[Any],              # list of Agent
    agent_addresses: dict[str, str],              # canonical_name → /a2a URL
    channel_addresses: dict[str, str],            # canonical_name → http://host:port
    transport_cfg: dict,                          # {"type": "http"|"nats", ...}
    session_store_cfg: dict,                      # {"type": "memory"|"sqlite", ...}
    store_cfg: dict | None = None,                # ScheduleStore config; see below
) -> FileBundle:
    agents = agents_with_schedules

    routes: dict[str, dict] = {}
    for agent in agents:
        has_heartbeat = agent.heartbeat is not None
        schedules = list(agent.schedules or [])
        if not has_heartbeat and not schedules:
            continue
        route: dict[str, Any] = {
            "canonical": agent.canonical_name,
            "address": agent_addresses[agent.canonical_name],
            "schedules": [t.model_dump(mode="json") for t in schedules],
        }
        if has_heartbeat:
            target = agent.heartbeat.target_channel
            route["heartbeat"] = agent.heartbeat.model_dump(mode="json")
            route["delivery"] = {
                "channel_canonical_name": target,
                "url": channel_addresses.get(target, ""),
            }
        routes[agent.name] = route

    service_config = {
        "transport": transport_cfg,
        "session_store": session_store_cfg,
        "agent_addresses": agent_addresses,
        "channel_addresses": channel_addresses,
        # ScheduleStore backend for scheduled tasks (distinct from
        # session_store above, which is the heartbeat conversation store).
        # Defaults to sqlite; callers pass
        # {"type": "postgres", "dsn": "postgresql://..."} to opt into
        # PgScheduleStore instead — see __main__._build_schedule_store.
        "store": store_cfg or {"type": "sqlite", "path": "/data/scheduler.db"},
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
