"""Unit tests for the _agents_needing_scheduler pre-filter helper."""

from vystak.schema.agent import Agent
from vystak.schema.heartbeat import Heartbeat
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.schedule import ScheduledTask
from vystak_cli.commands.apply import _agents_needing_scheduler


def _model():
    return Model(
        name="m",
        provider=Provider(name="anthropic", type="anthropic"),
        model_name="claude-sonnet-4-6",
    )


def _entry(name, *, heartbeat=None, schedules=()):
    agent = Agent(
        name=name,
        framework="langchain-python",
        default_model=_model(),
        heartbeat=heartbeat,
        schedules=list(schedules),
    )
    return {"name": name, "url": "http://x", "agent": agent}


def test_heartbeat_only_agent_included():
    entry = _entry(
        "bot",
        heartbeat=Heartbeat(schedule="*/30 * * * *", target_channel="x.channels.dev"),
    )
    result = _agents_needing_scheduler([entry])
    assert result == [entry]


def test_schedules_only_agent_included():
    entry = _entry("worker", schedules=[ScheduledTask(name="digest", cron="0 9 * * 1")])
    result = _agents_needing_scheduler([entry])
    assert result == [entry]


def test_heartbeat_and_schedules_agent_included():
    entry = _entry(
        "bot",
        heartbeat=Heartbeat(schedule="*/30 * * * *", target_channel="x.channels.dev"),
        schedules=[ScheduledTask(name="digest", cron="0 9 * * 1")],
    )
    result = _agents_needing_scheduler([entry])
    assert result == [entry]


def test_neither_agent_excluded():
    entry = _entry("idle")
    result = _agents_needing_scheduler([entry])
    assert result == []


def test_mixed_list_filters_correctly():
    idle = _entry("idle")
    worker = _entry("worker", schedules=[ScheduledTask(name="d", cron="0 9 * * 1")])
    bot = _entry(
        "bot",
        heartbeat=Heartbeat(schedule="*/30 * * * *", target_channel="x.channels.dev"),
    )
    result = _agents_needing_scheduler([idle, worker, bot])
    assert result == [worker, bot]
