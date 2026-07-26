"""vystak-heartbeat container entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
from pathlib import Path

from vystak.schema.heartbeat import Heartbeat
from vystak.schema.schedule import ScheduledTask, from_heartbeat

from vystak_heartbeat.schedule_store import SqliteScheduleStore
from vystak_heartbeat.schedule_store_pg import PgScheduleStore
from vystak_heartbeat.session_store import (
    HeartbeatSessionStore,
    InMemoryStore,
    SqliteStore,
)
from vystak_heartbeat.task_scheduler import TaskScheduler

logger = logging.getLogger("vystak.heartbeat.main")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _build_transport(cfg: dict):
    """Construct a Transport based on service_config.json transport.type.

    Imports are lazy so import-time errors don't surface during plugin
    codegen (Tasks 11/12 add the matching delivery transports too).
    """
    t = cfg.get("transport", {})
    if t.get("type") == "nats":
        from vystak_transport_nats.transport import NatsTransport
        return NatsTransport(t["url"], routes=cfg.get("agent_addresses", {}))
    from vystak_transport_http.transport import HttpTransport
    return HttpTransport(routes=cfg.get("agent_addresses", {}))


def _build_delivery(cfg: dict, channel_routes: dict):
    t = cfg.get("transport", {})
    if t.get("type") == "nats":
        from vystak_transport_nats.delivery import NatsChannelDelivery
        return NatsChannelDelivery(t["url"])
    from vystak_transport_http.delivery import HttpChannelDelivery
    return HttpChannelDelivery(channel_routes)


def _build_session_store(cfg: dict) -> HeartbeatSessionStore:
    s = cfg.get("session_store", {})
    if s.get("type") == "sqlite":
        return SqliteStore(s["path"])
    return InMemoryStore()


def _build_schedule_store(cfg: dict) -> SqliteScheduleStore | PgScheduleStore:
    """Construct the ScheduleStore from service_config.json's `store` key.

    Default (and only backend the docker provider currently wires) is
    sqlite — see build_bundle's `store_cfg` parameter and
    DockerProvider.apply_scheduler for how a bundle would opt into
    `{"type": "postgres", "dsn": ...}` instead.
    """
    s = cfg.get("store", {})
    if s.get("type") == "postgres":
        return PgScheduleStore(s["dsn"])
    return SqliteScheduleStore(s.get("path", "/data/scheduler.db"))


async def _run() -> None:
    logging.basicConfig(level=os.environ.get("VYSTAK_LOG_LEVEL", "INFO").upper())
    cfg_dir = Path(os.environ.get("VYSTAK_CONFIG_DIR", "/etc/vystak"))
    cfg = _load_json(cfg_dir / "service_config.json")
    routes = _load_json(cfg_dir / "routes.json")

    transport = _build_transport(cfg)
    # All declared channels (not just heartbeat targets) so runtime-created
    # scheduled tasks can deliver to any channel, not only the one wired at
    # apply time for a heartbeat.
    channel_routes = cfg.get("channel_addresses", {})
    delivery = _build_delivery(cfg, channel_routes)
    sessions = _build_session_store(cfg)

    store = _build_schedule_store(cfg)
    await store.connect()

    agent_names: dict[str, str] = {}
    for agent_name, route in routes.items():
        agent_names[route["canonical"]] = agent_name
        declared: list[ScheduledTask] = []
        if "heartbeat" in route:
            # Disabled heartbeats (hb.enabled is False) are still reconciled
            # in — the task carries enabled=False, the store's `due()` skips
            # it, and it stays visible via GET /tasks.
            hb = Heartbeat.model_validate(route["heartbeat"])
            declared.append(from_heartbeat(hb))
        for raw in route.get("schedules", []):
            declared.append(ScheduledTask.model_validate(raw))
        await store.reconcile_declarative(route["canonical"], declared)

    scheduler = TaskScheduler(
        store=store,
        transport=transport,
        delivery=delivery,
        sessions=sessions,
        agent_names=agent_names,
    )
    # start() calls startup_reconcile_next_fires() internally — do not call
    # it again here.
    await scheduler.start()

    import uvicorn

    from vystak_heartbeat.api import build_api

    server = uvicorn.Server(uvicorn.Config(
        build_api(store, scheduler), host="0.0.0.0", port=8081, log_level="warning"))
    api_task = asyncio.create_task(server.serve())

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    server.should_exit = True
    await api_task
    await scheduler.stop()
    await store.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
