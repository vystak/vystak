"""Heartbeat scheduler — fires periodic synthetic turns through the runtime
pipeline.

See docs/superpowers/specs/2026-05-09-heartbeat-design.md for design.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from vystak.schema.heartbeat import Heartbeat

from vystak_channel_runtime.types import InboundEvent

logger = logging.getLogger("vystak.channel.runtime.heartbeat")

HEARTBEAT_OK = "HEARTBEAT_OK"

DEFAULT_PROMPT = (
    "Read HEARTBEAT.md if it exists in your workspace. Follow it strictly. "
    "If nothing needs attention, reply with only HEARTBEAT_OK. "
    "Otherwise, reply with a short message describing what needs attention "
    "— do not include HEARTBEAT_OK in that case."
)


def enrich_routes_with_heartbeat(
    channel,
    resolved_routes: dict[str, dict],
) -> dict[str, dict]:
    """Add `heartbeat` blocks to route entries, copied from each agent's
    declared `heartbeat` config.

    Channel plugins call this from `generate_code` so that the channel
    container's `routes.json` carries the per-agent heartbeat config that
    `ChannelRuntime._heartbeat_for_route` reads at startup.
    """
    agent_by_name = {a.name: a for a in channel.agents}
    enriched: dict[str, dict] = {}
    for agent_name, route in resolved_routes.items():
        entry = dict(route)
        agent = agent_by_name.get(agent_name)
        if agent is not None and agent.heartbeat is not None:
            entry["heartbeat"] = agent.heartbeat.model_dump(mode="json")
        enriched[agent_name] = entry
    return enriched


def is_heartbeat_ok(text: str, max_chars: int) -> bool:
    """Return True iff `text` should be treated as a silent heartbeat ack.

    Rules (matches OpenClaw's behaviour):

    * Whitespace-only / empty text → False (do not silently swallow real bugs).
    * Stripped text longer than `max_chars` → False (always deliver long replies).
    * Otherwise → True iff `HEARTBEAT_OK` appears anywhere in the text.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if len(stripped) > max_chars:
        return False
    return HEARTBEAT_OK in stripped


class HeartbeatScheduler:
    """Per-(channel, agent) scheduler. Owned by ChannelRuntime."""

    def __init__(self, runtime, agent_name: str, config: Heartbeat) -> None:
        self.runtime = runtime
        self.agent_name = agent_name
        self.config = config
        self._task: asyncio.Task | None = None
        self._busy: bool = False

    async def start(self) -> None:
        if not self.config.enabled:
            return
        self._task = asyncio.create_task(
            self._run(), name=f"hb-{self.agent_name}",
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:
            # Defensive — stop()'s contract is "task is no longer running",
            # not "propagate task exit reason". Real loop errors are caught
            # and logged inside _run; this is a last-resort safety net.
            logger.exception("heartbeat scheduler task exited with error on stop")

    async def _resolve_thread(self) -> str | None:
        if self.config.target_thread is not None:
            return self.config.target_thread
        binding = await self.runtime.store.last_binding_for_agent(
            self.runtime.channel_type, self.agent_name,
        )
        return binding.thread_id if binding else None

    async def _fire(self) -> None:
        if self.config.skip_when_busy and self._busy:
            logger.info(
                "heartbeat.skipped agent=%s reason=busy", self.agent_name,
            )
            return
        thread_id = await self._resolve_thread()
        if thread_id is None:
            logger.debug(
                "heartbeat.skipped agent=%s reason=no-thread", self.agent_name,
            )
            return

        if self.config.isolated_session:
            synthetic = (
                f"__heartbeat__{int(time.time())}_{secrets.token_hex(4)}"
            )
            session_scope = synthetic
            session_thread = synthetic
        else:
            session_scope = thread_id
            session_thread = thread_id

        event = InboundEvent(
            channel_type=self.runtime.channel_type,
            scope_id=session_scope,
            thread_id=session_thread,
            user_id="__heartbeat__",
            text=self.config.prompt or DEFAULT_PROMPT,
            is_dm=False,
            mentions_bot=True,
            metadata={
                "heartbeat": True,
                "ack_max_chars": self.config.ack_max_chars,
                "deliver_scope": thread_id,
                "deliver_thread": thread_id,
            },
        )

        self._busy = True
        try:
            logger.info(
                "heartbeat.fired agent=%s thread=%s",
                self.agent_name, thread_id,
            )
            await self.runtime._handle_synthetic_event(event)
        finally:
            self._busy = False

    async def _run(self) -> None:
        try:
            tz = ZoneInfo(self.config.timezone)
        except Exception:
            logger.exception(
                "heartbeat invalid timezone=%s — disabling scheduler %s",
                self.config.timezone, self.agent_name,
            )
            return
        cron = croniter(self.config.schedule, datetime.now(tz))
        while True:
            try:
                next_at = cron.get_next(datetime)
            except Exception:
                logger.exception(
                    "heartbeat cron error agent=%s — sleeping 60s",
                    self.agent_name,
                )
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
                logger.exception(
                    "heartbeat.fired_failed agent=%s", self.agent_name,
                )
