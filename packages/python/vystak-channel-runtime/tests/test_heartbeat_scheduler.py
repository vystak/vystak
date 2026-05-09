"""Unit tests for HeartbeatScheduler — thread resolution + lifecycle hooks.

Cron-loop tests live in this file too, gated on freezegun availability.
"""

from __future__ import annotations

import asyncio
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
    rt._handle_synthetic_event = AsyncMock()
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
    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(schedule="* * * * *"))
    await sch.start()
    assert sch._task is not None
    # Give the loop one tick.
    await asyncio.sleep(0)
    await sch.stop()
    assert sch._task.done()


@pytest.mark.asyncio
async def test_fire_with_no_thread_skips_silently():
    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb())
    await sch._fire()
    rt._handle_synthetic_event.assert_not_called()


@pytest.mark.asyncio
async def test_fire_with_pinned_thread_dispatches_event():
    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(target_thread="C123"))
    await sch._fire()
    rt._handle_synthetic_event.assert_awaited_once()
    raw = rt._handle_synthetic_event.await_args.args[0]
    assert raw.user_id == "__heartbeat__"
    assert raw.metadata["heartbeat"] is True
    assert raw.metadata["deliver_thread"] == "C123"
    assert raw.metadata["ack_max_chars"] == 300


@pytest.mark.asyncio
async def test_fire_isolated_session_uses_synthetic_thread():
    rt = _runtime()
    sch = HeartbeatScheduler(
        rt, "ops-bot", _hb(target_thread="C123", isolated_session=True),
    )
    await sch._fire()
    raw = rt._handle_synthetic_event.await_args.args[0]
    assert raw.thread_id is not None
    assert raw.thread_id.startswith("__heartbeat__")
    assert raw.scope_id.startswith("__heartbeat__")


@pytest.mark.asyncio
async def test_fire_non_isolated_uses_real_thread():
    rt = _runtime()
    sch = HeartbeatScheduler(
        rt, "ops-bot", _hb(target_thread="C123", isolated_session=False),
    )
    await sch._fire()
    raw = rt._handle_synthetic_event.await_args.args[0]
    assert raw.thread_id == "C123"
    assert raw.scope_id == "C123"


@pytest.mark.asyncio
async def test_fire_uses_default_prompt_when_unset():
    from vystak_channel_runtime.heartbeat import DEFAULT_PROMPT

    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(target_thread="C123"))
    await sch._fire()
    raw = rt._handle_synthetic_event.await_args.args[0]
    assert raw.text == DEFAULT_PROMPT


@pytest.mark.asyncio
async def test_fire_uses_custom_prompt_when_set():
    rt = _runtime()
    sch = HeartbeatScheduler(
        rt, "ops-bot", _hb(target_thread="C123", prompt="Custom prompt"),
    )
    await sch._fire()
    raw = rt._handle_synthetic_event.await_args.args[0]
    assert raw.text == "Custom prompt"


@pytest.mark.asyncio
async def test_skip_when_busy_drops_overlapping_fire():
    """If a previous fire is still running, skip the next one."""
    rt = _runtime()
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(target_thread="C123"))
    sch._busy = True  # simulate in-flight previous fire
    await sch._fire()
    rt._handle_synthetic_event.assert_not_called()


@pytest.mark.asyncio
async def test_busy_flag_resets_after_handle_event_raises():
    """Exception in _handle_synthetic_event must not leave _busy stuck."""
    rt = _runtime()
    rt._handle_synthetic_event = AsyncMock(side_effect=RuntimeError("boom"))
    sch = HeartbeatScheduler(rt, "ops-bot", _hb(target_thread="C123"))
    with pytest.raises(RuntimeError):
        await sch._fire()
    assert sch._busy is False
