"""TaskScheduler — the unified store-driven scheduling loop.

Replaces the per-agent `HeartbeatScheduler` asyncio loops (one per declared
heartbeat) with a single loop driven by `SqliteScheduleStore`. Every
scheduled task — whether compiled from a declarative `Heartbeat` via
`vystak.schema.schedule.from_heartbeat` or created at runtime by an agent
through the RPC surface — is a row in that one store; this loop polls for
due rows, fires them through Transport + delivery, and reschedules.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import UTC, datetime

from vystak.transport.types import A2AMessage, AgentRef
from vystak_channel_runtime.delivery import DeliveryRequest
from vystak_channel_runtime.heartbeat import DEFAULT_PROMPT, is_heartbeat_ok

from vystak_heartbeat.firing import classify_startup, compute_next_fire
from vystak_heartbeat.schedule_store import SqliteScheduleStore, StoredTask
from vystak_heartbeat.session_store import HeartbeatSessionStore

logger = logging.getLogger("vystak.heartbeat.task_scheduler")


class TaskScheduler:
    """Polls `SqliteScheduleStore` for due tasks and fires them.

    One instance serves every agent's scheduled tasks — there is no more
    one-loop-per-agent. `_fire_due`/`_fire_one` are split so unit tests can
    drive fire semantics (`_fire_one`) and scheduling-advance semantics
    (`_fire_due`) independently and deterministically.
    """

    POLL_CAP_S = 60.0  # never sleep longer than this without re-checking the store

    def __init__(
        self,
        *,
        store: SqliteScheduleStore,
        transport,
        delivery,
        sessions: HeartbeatSessionStore,
        agent_names: dict[str, str],
    ) -> None:
        self._store = store
        self._transport = transport
        self._delivery = delivery
        self._sessions = sessions
        self._agent_names = agent_names
        self._busy: set[str] = set()  # StoredTask.id currently firing
        self._fire_tasks: set[asyncio.Task] = set()
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    def wake(self) -> None:
        """API writes call this to short-circuit the poll sleep."""
        self._wake.set()

    async def startup_reconcile_next_fires(self) -> None:
        """Classify every active row's next fire on process start.

        Recurring tasks are always recomputed strictly from now (never
        replayed). One-shots within `GRACE_WINDOW_S` of their `at` fire on
        the next loop pass; older ones are marked missed instead of firing.
        """
        now = datetime.now(UTC)
        for rec in await self._store.list(status="active"):
            action, nxt = classify_startup(rec.task, rec.next_fire_at, now)
            if action == "schedule":
                await self._store.set_next_fire(rec.id, nxt)
            elif action == "fire-now":
                await self._store.set_next_fire(rec.id, now)
            else:
                await self._store.mark_missed(rec.id)

    async def _backfill_next_fires(self, now: datetime) -> None:
        """Give newly created rows (`next_fire_at IS NULL`) a first fire time.

        Runtime tasks created between polls land with no `next_fire_at` —
        only `startup_reconcile_next_fires` and this backfill ever populate
        it for the first time.
        """
        for rec in await self._store.list(status="active"):
            if rec.next_fire_at is not None:
                continue
            if rec.id in self._busy:
                # A dispatched one-shot has its next_fire_at deliberately
                # cleared by _fire_due while _fire_one is still in flight
                # (status stays 'active' until record_fire) — that NULL must
                # not be mistaken for "never scheduled" and resurrected here,
                # or an overlapping loop pass double-fires it (or, when
                # skip_when_busy, tight-polls until the fire completes).
                continue
            nxt = compute_next_fire(rec.task, now)
            if nxt is not None:
                await self._store.set_next_fire(rec.id, nxt)

    async def _fire_due(self, now: datetime) -> None:
        """Spawn a fire for every due row, advancing `next_fire_at` first.

        `next_fire_at` is advanced (or cleared, for one-shots) BEFORE the
        fire completes so a slow fire can't cause the same row to be
        double-triggered by the next poll pass.
        """
        for rec in await self._store.due(now):
            if rec.task.skip_when_busy and rec.id in self._busy:
                logger.info(
                    "scheduled_task.skipped agent=%s task=%s reason=busy",
                    rec.agent_canonical,
                    rec.task.name,
                )
                # "Skip this tick" semantics: advance the row exactly as if
                # it had fired so the poll loop doesn't busy-wait on it for
                # the duration of the in-flight fire. A one-shot marked busy
                # is currently firing — leave it alone; its own in-flight
                # `_fire_one` will complete it.
                if rec.task.at is None:
                    await self._store.set_next_fire(rec.id, compute_next_fire(rec.task, now))
                continue
            fire_task = asyncio.create_task(self._fire_one(rec))
            self._fire_tasks.add(fire_task)
            fire_task.add_done_callback(self._fire_tasks.discard)
            if rec.task.at is not None:
                await self._store.set_next_fire(rec.id, None)
            else:
                await self._store.set_next_fire(rec.id, compute_next_fire(rec.task, now))

    async def _fire_one(self, rec: StoredTask) -> None:
        """Fire a single task: call the agent, maybe deliver, record result.

        Model-stickiness (the `sessions.get_model`/`set_model` dance around
        `model_override`) is ported verbatim from the old
        `HeartbeatScheduler._fire`: the first resolved model for a session
        is remembered so subsequent fires on that same session keep using it
        even if the task's declared `model` changes.
        """
        self._busy.add(rec.id)
        try:
            task = rec.task
            prompt = task.prompt
            if prompt is None:
                prompt = (
                    DEFAULT_PROMPT
                    if task.name == "heartbeat"
                    else f"Scheduled task '{task.name}' fired."
                )

            if task.isolated_session:
                session_id = f"__scheduled__{int(time.time())}_{secrets.token_hex(4)}"
            else:
                session_id = task.target_thread or task.name

            stored_model = await self._sessions.get_model(session_id)
            request_model = stored_model or task.model

            logger.info(
                "scheduled_task.fired agent=%s task=%s session=%s",
                rec.agent_canonical,
                task.name,
                session_id,
            )
            reply = await self._transport.send_task(
                AgentRef(canonical_name=rec.agent_canonical),
                A2AMessage.from_text(prompt, correlation_id=session_id),
                metadata={
                    "scheduled_task": task.name,
                    "model_override": request_model,
                    "session_id": session_id,
                },
                timeout=120,
            )
            text = reply.text or ""
            chosen = (getattr(reply, "metadata", None) or {}).get("model_resolved")
            if chosen and stored_model is None:
                await self._sessions.set_model(session_id, chosen)

            suppressed = task.ack_max_chars is not None and is_heartbeat_ok(
                text, task.ack_max_chars
            )

            # record_fire must run before delivery is attempted: a deliver()
            # failure must never orphan a one-shot as permanently "active"
            # (its next_fire_at was already cleared by _fire_due) nor risk
            # it re-firing after a restart. Losing a notification is
            # acceptable; re-running a one-shot is not.
            await self._store.record_fire(
                rec.id,
                datetime.now(UTC),
                text[:1000],
                completed=task.at is not None,
            )

            if not suppressed and task.target_channel and task.target_thread:
                try:
                    await self._delivery.deliver(
                        task.target_channel,
                        DeliveryRequest(
                            thread_id=task.target_thread,
                            text=text,
                            metadata={
                                "scheduled_task": task.name,
                                "agent": self._agent_names.get(
                                    rec.agent_canonical, rec.agent_canonical
                                ),
                                "fired_at": datetime.now(UTC).isoformat(),
                            },
                        ),
                    )
                except Exception:
                    logger.exception(
                        "delivery failed task=%s agent=%s", task.name, rec.agent_canonical
                    )
        except Exception:
            logger.exception(
                "scheduled_task.fire_failed agent=%s task=%s",
                rec.agent_canonical,
                rec.task.name,
            )
        finally:
            self._busy.discard(rec.id)

    async def _run(self) -> None:
        while True:
            now = datetime.now(UTC)
            await self._backfill_next_fires(now)
            await self._fire_due(now)
            nxt = await self._store.min_next_fire()
            delay = (
                self.POLL_CAP_S
                if nxt is None
                else min(self.POLL_CAP_S, max(0.0, (nxt - now).total_seconds()))
            )
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
                self._wake.clear()
            except TimeoutError:
                pass

    async def start(self) -> None:
        if self._task is not None:
            return
        await self.startup_reconcile_next_fires()
        self._task = asyncio.create_task(self._run(), name="task-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("task scheduler exited with error on stop")
        self._task = None
        if self._fire_tasks:
            await asyncio.gather(*self._fire_tasks, return_exceptions=True)
