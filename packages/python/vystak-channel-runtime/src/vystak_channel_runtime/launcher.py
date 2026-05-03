"""Launcher helpers for channel containers' __main__.py entrypoints."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal

from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.store import make_channel_store


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
    """Build the runtime and run its event loop until SIGTERM/SIGINT."""
    logging.basicConfig(
        level=os.environ.get("VYSTAK_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
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

    starter = asyncio.create_task(rt.start())
    waiter = asyncio.create_task(stop_event.wait())
    done, pending = await asyncio.wait(
        {starter, waiter}, return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()
    await rt.stop()
