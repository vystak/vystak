"""Unit tests for HeartbeatScheduler — thread resolution + lifecycle hooks.

Cron-loop tests live in this file too, gated on freezegun availability.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from vystak.schema.heartbeat import Heartbeat
from vystak_channel_runtime.heartbeat import HeartbeatScheduler
from vystak_channel_runtime.types import ThreadBinding


def _hb(**overrides) -> Heartbeat:
    base = {
        "schedule": "*/30 * * * *",
        "target_channel": "x.channels.dev",
    }
    base.update(overrides)
    return Heartbeat(**base)


def _runtime() -> MagicMock:
    rt = MagicMock()
    rt.channel_type = "slack"
    rt.handle_event = AsyncMock()
    rt.store = MagicMock()
    rt.store.last_binding_for_agent = AsyncMock(return_value=None)
    return rt


@pytest.mark.asyncio
async def test_scheduler_with_pinned_thread_uses_it():
    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(target_thread="C123"))
    resolved = await sch._resolve_thread()
    assert resolved == "C123"
    rt.store.last_binding_for_agent.assert_not_called()


@pytest.mark.asyncio
async def test_scheduler_without_pinned_thread_consults_store():
    rt = _runtime()
    rt.store.last_binding_for_agent = AsyncMock(
        return_value=ThreadBinding(
            channel_type="slack",
            scope_id="T1",
            thread_id="thread-X",
            agent_name="ops-bot",
        ),
    )
    sch = HeartbeatScheduler(rt, "ops-bot", _hb())
    resolved = await sch._resolve_thread()
    assert resolved == "thread-X"
    rt.store.last_binding_for_agent.assert_awaited_once_with("slack", "ops-bot")


@pytest.mark.asyncio
async def test_scheduler_without_thread_and_empty_store_returns_none():
    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb())
    assert await sch._resolve_thread() is None


@pytest.mark.asyncio
async def test_disabled_scheduler_does_not_start_task():
    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(enabled=False))
    await sch.start()
    assert sch._task is None
    await sch.stop()  # should be a no-op


@pytest.mark.asyncio
async def test_stop_cancels_running_task():
    import asyncio

    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(schedule="* * * * *"))
    await sch.start()
    assert sch._task is not None
    # Give the loop one tick.
    await asyncio.sleep(0)
    await sch.stop()
    assert sch._task.done()
