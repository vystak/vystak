"""HeartbeatScheduler v2 — uses Transport + ChannelDelivery."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from vystak.schema.heartbeat import Heartbeat
from vystak_channel_runtime.heartbeat import (
    DEFAULT_PROMPT,
    is_heartbeat_ok,
)

from vystak_heartbeat.session_store import HeartbeatSessionStore

logger = logging.getLogger("vystak.heartbeat.scheduler")


class HeartbeatScheduler:
    def __init__(
        self,
        *,
        agent_name: str,
        agent_canonical: str,
        channel_canonical: str,
        heartbeat: Heartbeat,
        transport,                                 # duck-typed: send_task
        delivery,                                  # duck-typed: deliver
        sessions: HeartbeatSessionStore,
    ) -> None:
        self.agent_name = agent_name
        self.agent_canonical = agent_canonical
        self.channel_canonical = channel_canonical
        self.hb = heartbeat
        self.transport = transport
        self.delivery = delivery
        self.sessions = sessions
        self._task: asyncio.Task | None = None
        self._busy: bool = False

    async def start(self) -> None:
        if not self.hb.enabled:
            return
        self._task = asyncio.create_task(self._run(), name=f"hb-{self.agent_name}")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("scheduler task exited with error on stop")

    async def _resolve_thread(self) -> str | None:
        # No last-binding lookup in v2 — heartbeat service has no
        # ChannelStore. If `target_thread` is unset, skip.
        return self.hb.target_thread

    async def _fire(self) -> None:
        if self.hb.skip_when_busy and self._busy:
            logger.info("heartbeat.skipped agent=%s reason=busy", self.agent_name)
            return
        thread_id = await self._resolve_thread()
        if thread_id is None:
            logger.debug("heartbeat.skipped agent=%s reason=no-thread", self.agent_name)
            return

        if self.hb.isolated_session:
            session_id = f"__heartbeat__{int(time.time())}_{secrets.token_hex(4)}"
        else:
            session_id = thread_id

        stored = await self.sessions.get_model(session_id)
        request_model = stored or self.hb.model

        self._busy = True
        try:
            logger.info(
                "heartbeat.fired agent=%s thread=%s",
                self.agent_name, thread_id,
            )
            reply = await self._call_agent(session_id, request_model)
            chosen = (getattr(reply, "metadata", None) or {}).get("model_resolved")
            if chosen and stored is None:
                await self.sessions.set_model(session_id, chosen)

            if is_heartbeat_ok(reply.text or "", self.hb.ack_max_chars):
                logger.info("heartbeat.acked agent=%s thread=%s",
                            self.agent_name, thread_id)
                return

            await self._deliver(thread_id, reply.text or "")
        finally:
            self._busy = False

    async def _call_agent(self, session_id: str, request_model: str | None):
        """Invoke the agent via Transport. Wrapped in its own method so
        tests can stub the Transport surface without depending on the
        real A2AMessage/AgentRef shapes."""
        # The plan's exact call uses vystak.transport AgentRef + A2AMessage.
        # We pass them as kwargs — the test mocks send_task entirely, so
        # the precise shape only matters in production.
        return await self.transport.send_task(
            self.agent_canonical,
            self.hb.prompt or DEFAULT_PROMPT,
            metadata={
                "heartbeat": True,
                "model_override": request_model,
                "session_id": session_id,
            },
            timeout=120,
        )

    async def _deliver(self, thread_id: str, text: str) -> None:
        await self.delivery.deliver(
            self.channel_canonical,
            thread_id=thread_id,
            text=text,
            metadata={
                "heartbeat": True,
                "agent": self.agent_name,
                "fired_at": datetime.utcnow().isoformat() + "Z",
            },
        )

    async def _run(self) -> None:
        try:
            tz = ZoneInfo(self.hb.timezone)
        except Exception:
            logger.exception("invalid timezone %s — disabling scheduler %s",
                             self.hb.timezone, self.agent_name)
            return
        cron = croniter(self.hb.schedule, datetime.now(tz))
        while True:
            try:
                next_at = cron.get_next(datetime)
            except Exception:
                logger.exception("cron error agent=%s — sleeping 60s",
                                 self.agent_name)
                await asyncio.sleep(60)
                continue
            delay = max(0.0, (next_at - datetime.now(tz)).total_seconds())
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise
            try:
                await self._fire()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("fire failed agent=%s", self.agent_name)
