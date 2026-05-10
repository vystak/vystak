"""Codegen tests for the heartbeat plugin."""

import json
from types import SimpleNamespace

from vystak.schema.heartbeat import Heartbeat
from vystak_heartbeat.plugin import generate_code


def _agent(name: str, canonical: str, heartbeat: Heartbeat | None = None):
    return SimpleNamespace(
        name=name, canonical_name=canonical, heartbeat=heartbeat,
    )


def test_routes_json_includes_heartbeat_and_delivery():
    a = _agent(
        "bot", "bot.agents.dev",
        Heartbeat(schedule="*/30 * * * *", target_channel="x.channels.dev"),
    )
    out = generate_code(
        agents_with_heartbeat=[a],
        agent_addresses={"bot.agents.dev": "http://vystak-bot:8000/a2a"},
        channel_addresses={"x.channels.dev": "http://vystak-channel-x:9999"},
        transport_cfg={"type": "http"},
        session_store_cfg={"type": "memory"},
    )
    routes = json.loads(out.files["routes.json"])
    assert "bot" in routes
    assert routes["bot"]["heartbeat"]["schedule"] == "*/30 * * * *"
    assert routes["bot"]["delivery"]["url"] == "http://vystak-channel-x:9999"


def test_dockerfile_uses_python_module():
    out = generate_code(
        agents_with_heartbeat=[],
        agent_addresses={},
        channel_addresses={},
        transport_cfg={"type": "http"},
        session_store_cfg={"type": "memory"},
    )
    assert "python -m vystak_heartbeat" in out.files["Dockerfile"]


def test_service_config_includes_transport_and_session_store():
    out = generate_code(
        agents_with_heartbeat=[],
        agent_addresses={},
        channel_addresses={},
        transport_cfg={"type": "nats", "url": "nats://x:4222"},
        session_store_cfg={"type": "sqlite", "path": "/data/heartbeat.db"},
    )
    cfg = json.loads(out.files["service_config.json"])
    assert cfg["transport"]["type"] == "nats"
    assert cfg["session_store"]["path"] == "/data/heartbeat.db"
