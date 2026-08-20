"""PanelChannelRuntime — FastAPI control-panel API on the channel lifecycle."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import uvicorn
from fastapi import FastAPI
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.types import AgentReply, InboundEvent, SkipEvent

from vystak_channel_panel.plugin import DEFAULT_DB_PATH
from vystak_channel_panel.responses_client import ResponsesClient
from vystak_channel_panel.store import SqlitePanelStore

logger = logging.getLogger("vystak.channel.panel")


class PanelChannelRuntime(ChannelRuntime):
    """Serves the panel REST + SSE API.

    Unlike chat/slack, requests do not flow through handle_event — the
    FastAPI routes call the panel store + ResponsesClient directly (the
    A2A pipeline's request/reply bridge can't represent an SSE response).
    ChannelRuntime is still the base for lifecycle, config, store, and
    delivery-receiver plumbing.
    """

    def __init__(
        self,
        *,
        panel_store: SqlitePanelStore | None = None,
        responses_client: ResponsesClient | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.panel_store = panel_store or SqlitePanelStore(
            self.config.get("db_path", DEFAULT_DB_PATH)
        )
        self.responses_client = responses_client or ResponsesClient()
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._owns_store = panel_store is None

        self.transport_type = self.config.get("transport_type", "http")
        self.nats_client = None
        if self.transport_type == "nats":
            from vystak_channel_panel.nats_client import PanelNatsClient

            self.nats_client = PanelNatsClient(
                os.environ.get("VYSTAK_NATS_URL", "nats://vystak-nats:4222"),
                idle_timeout_s=float(self.config.get("turn_idle_timeout_s", 120.0)),
            )
        self.turn_tasks: dict[str, asyncio.Task] = {}

    def monotonic(self) -> float:
        """Deadline clock for `run_turn_persister` — a thin seam so tests
        can inject a fake clock (see `persister_harness` in conftest.py)."""
        return time.monotonic()

    # --- ChannelRuntime abstract hooks (unused request path) --------------

    def parse_event(self, raw_event: Any) -> InboundEvent:
        raise SkipEvent("panel does not use the handle_event pipeline")

    async def post_reply(self, event: InboundEvent, route: str, reply: AgentReply) -> None:
        return None

    async def deliver_message(self, thread_id: str, text: str, metadata: dict) -> None:
        # TODO(heartbeat): no push surface yet; heartbeat delivery would
        # append to a conversation once the panel grows one per heartbeat.
        logger.warning(
            "panel deliver_message: no push mechanism; thread_id=%s text_len=%d",
            thread_id,
            len(text),
        )

    async def _start_delivery_receiver(self) -> None:
        @self._app.post("/deliver")
        async def _deliver(payload: dict):
            await self._on_inbound_delivery(payload)
            return {"ok": True}

    async def _stop_delivery_receiver(self) -> None:
        return None

    # --- turn persistence (NATS transport only) ----------------------------

    def spawn_persister(self, conv_id: str, turn_id: str, subject: str) -> None:
        from vystak_channel_panel.turn_worker import run_turn_persister

        task = asyncio.create_task(run_turn_persister(self, conv_id, turn_id, subject))
        self.turn_tasks[turn_id] = task

    async def _resume_active_turns(self) -> None:
        """Re-attach persisters for turns that were in flight when the panel
        last stopped — JetStream replay-from-0 rebuilds the accumulator."""
        if self.nats_client is None:
            return
        from vystak_channel_panel.nats_client import PanelNatsClient

        for conv in await self.panel_store.list_active_turns():
            route = self.routes.get(conv.agent_name)
            if route is None or not conv.active_turn_id:
                continue
            subject = PanelNatsClient.turn_subject_for(route, conv.id, conv.active_turn_id)
            self.spawn_persister(conv.id, conv.active_turn_id, subject)

    # --- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        from vystak_channel_panel.app import build_app

        if self._owns_store:
            await self.panel_store.connect()
        self._app = build_app(self)
        port = int(self.config.get("port", 8080))
        cfg = uvicorn.Config(self._app, host="0.0.0.0", port=port, log_level="info")
        self._server = uvicorn.Server(cfg)
        await self._start_delivery_receiver()
        await self._resume_active_turns()
        await self._server.serve()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._owns_store:
            await self.panel_store.close()
