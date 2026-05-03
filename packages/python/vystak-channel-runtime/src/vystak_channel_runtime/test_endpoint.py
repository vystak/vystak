"""Synthetic event dispatch endpoint — gated by VYSTAK_TEST_EVENTS env var.

`fastapi` is an OPTIONAL dependency of `vystak-channel-runtime`. Channels
that don't need the test endpoint (Discord gateway-mode, Slack Socket Mode)
shouldn't carry FastAPI in their container image. Install via
`pip install vystak-channel-runtime[test-endpoint]` to enable.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.types import InboundEvent

if TYPE_CHECKING:
    from fastapi import FastAPI


def is_test_endpoint_enabled() -> bool:
    return os.environ.get("VYSTAK_TEST_EVENTS") == "1"


def build_test_app(runtime: ChannelRuntime) -> FastAPI:
    """Build a small FastAPI app exposing /test/event for synthetic dispatch.

    Raises ImportError if fastapi isn't installed — install the
    `test-endpoint` extra to enable.
    """
    try:
        from fastapi import FastAPI
    except ImportError as exc:
        raise ImportError(
            "fastapi is required for build_test_app. Install it via "
            "`pip install vystak-channel-runtime[test-endpoint]`."
        ) from exc

    app = FastAPI(title="vystak-channel-runtime test endpoint")

    @app.post("/test/event")
    async def post_event(event: InboundEvent) -> dict:
        await runtime.handle_event(event.model_dump())
        return {"status": "dispatched"}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
