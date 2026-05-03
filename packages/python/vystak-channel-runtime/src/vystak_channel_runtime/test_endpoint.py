"""Synthetic event dispatch endpoint — gated by VYSTAK_TEST_EVENTS env var."""

from __future__ import annotations

import os

from fastapi import FastAPI

from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.types import InboundEvent


def is_test_endpoint_enabled() -> bool:
    return os.environ.get("VYSTAK_TEST_EVENTS") == "1"


def build_test_app(runtime: ChannelRuntime) -> FastAPI:
    """Build a small FastAPI app exposing /test/event for synthetic dispatch."""
    app = FastAPI(title="vystak-channel-runtime test endpoint")

    @app.post("/test/event")
    async def post_event(event: InboundEvent) -> dict:
        await runtime.handle_event(event.model_dump())
        return {"status": "dispatched"}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
