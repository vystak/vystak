"""Codegen tests for the heartbeat plugin."""

import json
from types import SimpleNamespace

from vystak.schema.heartbeat import Heartbeat
from vystak.schema.schedule import ScheduledTask
from vystak_heartbeat.plugin import build_bundle


def _agent(
    name: str,
    canonical: str,
    heartbeat: Heartbeat | None = None,
    schedules: tuple = (),
):
    return SimpleNamespace(
        name=name, canonical_name=canonical, heartbeat=heartbeat,
        schedules=list(schedules),
    )


def test_routes_json_includes_heartbeat_and_delivery():
    a = _agent(
        "bot", "bot.agents.dev",
        Heartbeat(schedule="*/30 * * * *", target_channel="x.channels.dev"),
    )
    out = build_bundle(
        agents_with_schedules=[a],
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
    out = build_bundle(
        agents_with_schedules=[],
        agent_addresses={},
        channel_addresses={},
        transport_cfg={"type": "http"},
        session_store_cfg={"type": "memory"},
    )
    assert "python -m vystak_heartbeat" in out.files["Dockerfile"]


def test_service_config_includes_transport_and_session_store():
    out = build_bundle(
        agents_with_schedules=[],
        agent_addresses={},
        channel_addresses={},
        transport_cfg={"type": "nats", "url": "nats://x:4222"},
        session_store_cfg={"type": "sqlite", "path": "/data/heartbeat.db"},
    )
    cfg = json.loads(out.files["service_config.json"])
    assert cfg["transport"]["type"] == "nats"
    assert cfg["session_store"]["path"] == "/data/heartbeat.db"


def test_schedules_only_agent_route_has_schedules_and_no_delivery():
    a = _agent(
        "worker", "worker.agents.dev",
        schedules=(ScheduledTask(name="digest", cron="0 9 * * 1"),),
    )
    out = build_bundle(
        agents_with_schedules=[a],
        agent_addresses={"worker.agents.dev": "http://vystak-worker:8000/a2a"},
        channel_addresses={"x.channels.dev": "http://vystak-channel-x:9999"},
        transport_cfg={"type": "http"},
        session_store_cfg={"type": "memory"},
    )
    routes = json.loads(out.files["routes.json"])
    assert "worker" in routes
    assert routes["worker"]["schedules"][0]["name"] == "digest"
    assert "heartbeat" not in routes["worker"]
    assert "delivery" not in routes["worker"]


def test_agent_with_heartbeat_and_schedules_has_both():
    a = _agent(
        "bot", "bot.agents.dev",
        Heartbeat(schedule="*/30 * * * *", target_channel="x.channels.dev"),
        schedules=(ScheduledTask(name="digest", cron="0 9 * * 1"),),
    )
    out = build_bundle(
        agents_with_schedules=[a],
        agent_addresses={"bot.agents.dev": "http://vystak-bot:8000/a2a"},
        channel_addresses={"x.channels.dev": "http://vystak-channel-x:9999"},
        transport_cfg={"type": "http"},
        session_store_cfg={"type": "memory"},
    )
    routes = json.loads(out.files["routes.json"])
    assert routes["bot"]["heartbeat"]["schedule"] == "*/30 * * * *"
    assert routes["bot"]["delivery"]["url"] == "http://vystak-channel-x:9999"
    assert routes["bot"]["schedules"][0]["name"] == "digest"


def test_agent_with_neither_heartbeat_nor_schedules_excluded():
    a = _agent("idle", "idle.agents.dev")
    out = build_bundle(
        agents_with_schedules=[a],
        agent_addresses={"idle.agents.dev": "http://vystak-idle:8000/a2a"},
        channel_addresses={},
        transport_cfg={"type": "http"},
        session_store_cfg={"type": "memory"},
    )
    routes = json.loads(out.files["routes.json"])
    assert routes == {}


def test_service_config_includes_store_and_channel_addresses():
    out = build_bundle(
        agents_with_schedules=[],
        agent_addresses={},
        channel_addresses={"x.channels.dev": "http://vystak-channel-x:9999"},
        transport_cfg={"type": "http"},
        session_store_cfg={"type": "memory"},
    )
    cfg = json.loads(out.files["service_config.json"])
    assert cfg["store"] == {"type": "sqlite", "path": "/data/scheduler.db"}
    assert cfg["channel_addresses"] == {"x.channels.dev": "http://vystak-channel-x:9999"}


def test_requirements_includes_fastapi_and_uvicorn():
    out = build_bundle(
        agents_with_schedules=[],
        agent_addresses={},
        channel_addresses={},
        transport_cfg={"type": "http"},
        session_store_cfg={"type": "memory"},
    )
    assert "fastapi" in out.files["requirements.txt"]
    assert "uvicorn" in out.files["requirements.txt"]


def test_store_cfg_override_lands_in_service_config():
    out = build_bundle(
        agents_with_schedules=[],
        agent_addresses={},
        channel_addresses={},
        transport_cfg={"type": "http"},
        session_store_cfg={"type": "memory"},
        store_cfg={"type": "postgres", "dsn": "postgresql://scheduler:testpass@db:5432/sched"},
    )
    cfg = json.loads(out.files["service_config.json"])
    assert cfg["store"] == {"type": "postgres", "dsn": "postgresql://scheduler:testpass@db:5432/sched"}
