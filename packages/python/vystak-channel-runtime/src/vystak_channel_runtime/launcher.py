"""Launcher helpers for channel containers' __main__.py entrypoints."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal

from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.store import make_channel_store
from vystak_channel_runtime.telemetry import init_telemetry
from vystak_channel_runtime.test_endpoint import is_test_endpoint_enabled

logger = logging.getLogger("vystak.channel.runtime.launcher")


def build_runtime(
    runtime_cls: type[ChannelRuntime],
    config: dict,
    routes: dict,
) -> ChannelRuntime:
    """Construct a ChannelRuntime from configs (no I/O loop)."""
    store = make_channel_store(config.get("state"))
    return runtime_cls(config=config, routes=routes, store=store)


def launch(
    runtime_cls: type[ChannelRuntime],
    config: dict,
    routes: dict,
) -> None:
    """Build the runtime and run its event loop until SIGTERM/SIGINT.

    When `VYSTAK_TEST_EVENTS=1` is set in the environment, also spawns a
    sidecar uvicorn that exposes /test/event for synthetic dispatch (port
    from `VYSTAK_TEST_EVENTS_PORT`, default 8765). Requires the
    `test-endpoint` extra.

    Also bootstraps OTel telemetry early so httpx auto-instrumentation
    catches outbound A2A calls; the chat channel's FastAPI build also
    wires server-span generation. No-op when OTEL_EXPORTER_OTLP_ENDPOINT
    is unset.
    """
    logging.basicConfig(
        level=os.environ.get("VYSTAK_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Init telemetry once at process start. Channels without a FastAPI
    # app (Slack, Discord) still benefit from HTTPX instrumentation +
    # NATS-side traceparent injection in NatsAgentClient.
    init_telemetry(
        service_name=os.environ.get(
            "OTEL_SERVICE_NAME",
            f"vystak-channel-{config.get('channel_type', 'unknown')}",
        ),
    )
    rt = build_runtime(runtime_cls, config=config, routes=routes)
    asyncio.run(_run(rt))


async def _run(rt: ChannelRuntime) -> None:
    stop_event = asyncio.Event()

    def _stop(*_):
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            # Windows / non-main-thread fallback: add_signal_handler raises NotImplementedError.
            loop.add_signal_handler(sig, _stop)

    tasks: set[asyncio.Task] = set()
    starter = asyncio.create_task(rt.start(), name="runtime.start")
    tasks.add(starter)

    test_server = None
    if is_test_endpoint_enabled():
        test_server = _start_test_endpoint(rt)
        if test_server is not None:
            tasks.add(test_server)

    waiter = asyncio.create_task(stop_event.wait(), name="stop_event.wait")
    tasks.add(waiter)

    done, pending = await asyncio.wait(
        tasks, return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()
    await rt.stop()


def _start_test_endpoint(rt: ChannelRuntime) -> asyncio.Task | None:
    """Spawn a sidecar uvicorn for /test/event. Returns None on missing deps."""
    try:
        import uvicorn

        from vystak_channel_runtime.test_endpoint import build_test_app
    except ImportError:
        logger.warning(
            "VYSTAK_TEST_EVENTS=1 set but fastapi/uvicorn not installed; "
            "install vystak-channel-runtime[test-endpoint] to enable.",
        )
        return None

    app = build_test_app(rt)
    port = int(os.environ.get("VYSTAK_TEST_EVENTS_PORT", "8765"))
    cfg = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    logger.info("test endpoint enabled on :%d", port)
    return asyncio.create_task(server.serve(), name="test-endpoint.serve")
