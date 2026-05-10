"""Tests for v2 HeartbeatScheduler (transport + delivery)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from vystak.schema.heartbeat import Heartbeat
from vystak_heartbeat.scheduler import HeartbeatScheduler
from vystak_heartbeat.session_store import InMemoryStore


def _hb(**overrides) -> Heartbeat:
    base = {"schedule": "*/30 * * * *", "target_channel": "x.channels.dev"}
    base.update(overrides)
    return Heartbeat(**base)


def _scheduler(**deps):
    base = dict(
        agent_name="bot",
        agent_canonical="bot.agents.dev",
        channel_canonical="x.channels.dev",
        heartbeat=_hb(target_thread="C1"),
        transport=AsyncMock(),
        delivery=AsyncMock(),
        sessions=InMemoryStore(),
    )
    base.update(deps)
    return HeartbeatScheduler(**base)


def _reply(text: str, model_resolved: str | None = None):
    return SimpleNamespace(
        text=text,
        metadata={"model_resolved": model_resolved} if model_resolved else {},
    )


@pytest.mark.asyncio
async def test_fire_calls_transport_with_metadata():
    sch = _scheduler()
    sch.transport.send_task = AsyncMock(return_value=_reply("hi", "haiku"))
    await sch._fire()
    sch.transport.send_task.assert_awaited_once()
    md = sch.transport.send_task.await_args.kwargs.get("metadata") \
         or sch.transport.send_task.await_args.args[2]
    assert md["heartbeat"] is True
    assert md["session_id"]


@pytest.mark.asyncio
async def test_fire_delivers_alert_when_not_ok():
    sch = _scheduler()
    sch.transport.send_task = AsyncMock(
        return_value=_reply("alert!", "haiku"),
    )
    await sch._fire()
    sch.delivery.deliver.assert_awaited_once()


@pytest.mark.asyncio
async def test_fire_skips_delivery_when_heartbeat_ok():
    sch = _scheduler()
    sch.transport.send_task = AsyncMock(
        return_value=_reply("HEARTBEAT_OK", "haiku"),
    )
    await sch._fire()
    sch.delivery.deliver.assert_not_called()


@pytest.mark.asyncio
async def test_fire_persists_model_on_first_resolve():
    sessions = InMemoryStore()
    sch = _scheduler(
        heartbeat=_hb(target_thread="C1", isolated_session=False, model="opus"),
        sessions=sessions,
    )
    sch.transport.send_task = AsyncMock(
        return_value=_reply("alert", "haiku"),
    )
    await sch._fire()
    assert await sessions.get_model("C1") == "haiku"


@pytest.mark.asyncio
async def test_fire_does_not_overwrite_stored_model():
    sessions = InMemoryStore()
    await sessions.set_model("C1", "haiku")
    sch = _scheduler(
        heartbeat=_hb(target_thread="C1", isolated_session=False),
        sessions=sessions,
    )
    sch.transport.send_task = AsyncMock(
        return_value=_reply("alert", "sonnet"),
    )
    await sch._fire()
    assert await sessions.get_model("C1") == "haiku"


@pytest.mark.asyncio
async def test_skip_when_busy():
    sch = _scheduler()
    sch._busy = True
    await sch._fire()
    sch.transport.send_task.assert_not_called()


@pytest.mark.asyncio
async def test_busy_resets_on_transport_error():
    sch = _scheduler()
    sch.transport.send_task = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        await sch._fire()
    assert sch._busy is False


@pytest.mark.asyncio
async def test_no_thread_skips_silently():
    sch = _scheduler(heartbeat=_hb())  # no target_thread
    await sch._fire()
    sch.transport.send_task.assert_not_called()
