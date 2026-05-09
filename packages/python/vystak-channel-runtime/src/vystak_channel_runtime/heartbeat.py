"""Heartbeat scheduler — fires periodic synthetic turns through the runtime
pipeline.

See docs/superpowers/specs/2026-05-09-heartbeat-design.md for design.
"""

from __future__ import annotations

import asyncio
import logging

from vystak.schema.heartbeat import Heartbeat

logger = logging.getLogger("vystak.channel.runtime.heartbeat")

HEARTBEAT_OK = "HEARTBEAT_OK"

DEFAULT_PROMPT = (
    "Read HEARTBEAT.md if it exists in your workspace. Follow it strictly. "
    "If nothing needs attention, reply with only HEARTBEAT_OK. "
    "Otherwise, reply with a short message describing what needs attention "
    "— do not include HEARTBEAT_OK in that case."
)


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
            # Task may have exited with an error (e.g. NotImplementedError from
            # the _run stub in Task 6). Log and absorb — stop()'s contract is
            # "task is no longer running", not "propagate task exit reason".
            logger.exception("heartbeat scheduler task exited with error on stop")

    async def _resolve_thread(self) -> str | None:
        if self.config.target_thread:
            return self.config.target_thread
        binding = await self.runtime.store.last_binding_for_agent(
            self.runtime.channel_type, self.agent_name,
        )
        return binding.thread_id if binding else None

    async def _run(self) -> None:
        # Implemented in Task 7.
        raise NotImplementedError
