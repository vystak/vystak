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

from vystak_heartbeat.scheduler import HeartbeatScheduler
from vystak_heartbeat.session_store import (
    HeartbeatSessionStore,
    InMemoryStore,
    SqliteStore,
)

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


async def _run() -> None:
    logging.basicConfig(level=os.environ.get("VYSTAK_LOG_LEVEL", "INFO").upper())
    cfg_dir = Path(os.environ.get("VYSTAK_CONFIG_DIR", "/etc/vystak"))
    cfg = _load_json(cfg_dir / "service_config.json")
    routes = _load_json(cfg_dir / "routes.json")

    transport = _build_transport(cfg)
    channel_routes = {
        r["delivery"]["channel_canonical_name"]: r["delivery"].get("url", "")
        for r in routes.values() if "delivery" in r
    }
    delivery = _build_delivery(cfg, channel_routes)
    sessions = _build_session_store(cfg)

    schedulers: list[HeartbeatScheduler] = []
    for agent_name, route in routes.items():
        if "heartbeat" not in route:
            continue
        hb = Heartbeat.model_validate(route["heartbeat"])
        if not hb.enabled:
            continue
        schedulers.append(HeartbeatScheduler(
            agent_name=agent_name,
            agent_canonical=route["canonical"],
            channel_canonical=route["delivery"]["channel_canonical_name"],
            heartbeat=hb,
            transport=transport,
            delivery=delivery,
            sessions=sessions,
        ))

    for s in schedulers:
        await s.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    for s in schedulers:
        await s.stop()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
