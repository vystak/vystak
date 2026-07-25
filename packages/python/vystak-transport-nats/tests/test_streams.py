"""Tests for JetStream turn-stream helpers."""

import json

import pytest
from vystak_transport_nats.streams import (
    TurnStreamIdle,
    ensure_stream,
    is_terminal_event,
    read_turn_events,
    stream_base,
    stream_name_for_base,
    turn_subject,
)


def test_stream_base_from_tasks_subject():
    assert stream_base("vystak.multi.agents.time-agent.tasks") == "vystak.multi"
    assert stream_base("vystak-nats.multi-nats.agents.a.tasks") == "vystak-nats.multi-nats"


def test_stream_base_rejects_non_tasks_subject():
    with pytest.raises(ValueError):
        stream_base("not-a-subject")


def test_stream_name_for_base():
    assert stream_name_for_base("vystak.multi") == "vystak-multi-streams"


def test_turn_subject():
    assert turn_subject("vystak.multi", "conv1", "turnA") == "vystak.multi.streams.conv1.turnA"


def test_is_terminal_event():
    assert is_terminal_event({"seq": 3, "event": {"type": "response.completed"}})
    assert is_terminal_event({"seq": 3, "event": {"type": "response.failed"}})
    assert not is_terminal_event({"seq": 0, "event": {"type": "response.created"}})
    assert not is_terminal_event({"seq": 0})


class FakeJS:
    def __init__(self, add_error: Exception | None = None):
        self.add_calls: list = []
        self.update_calls: list = []
        self._add_error = add_error

    async def add_stream(self, cfg):
        self.add_calls.append(cfg)
        if self._add_error:
            raise self._add_error

    async def update_stream(self, cfg):
        self.update_calls.append(cfg)


@pytest.mark.asyncio
async def test_ensure_stream_adds():
    js = FakeJS()
    await ensure_stream(js, "vystak.multi")
    assert len(js.add_calls) == 1
    cfg = js.add_calls[0]
    assert cfg.name == "vystak-multi-streams"
    assert cfg.subjects == ["vystak.multi.streams.>"]
    assert js.update_calls == []


@pytest.mark.asyncio
async def test_ensure_stream_falls_back_to_update_when_exists():
    js = FakeJS(add_error=RuntimeError("stream name already in use"))
    await ensure_stream(js, "vystak.multi")
    assert len(js.update_calls) == 1


class FakeMsg:
    def __init__(self, payload: dict):
        self.data = json.dumps(payload).encode()


class FakeSub:
    def __init__(self, payloads: list[dict], *, then_hang: bool = False):
        self._payloads = list(payloads)
        self._then_hang = then_hang
        self.unsubscribed = False

    async def next_msg(self, timeout: float):
        if self._payloads:
            return FakeMsg(self._payloads.pop(0))
        if self._then_hang:
            import nats.errors

            raise nats.errors.TimeoutError
        raise AssertionError("no more messages")

    async def unsubscribe(self):
        self.unsubscribed = True


class FakeNC:
    def __init__(self, sub: FakeSub):
        self._sub = sub
        self.subscribed_subject: str | None = None

    def jetstream(self):
        return self

    async def subscribe(self, subject, ordered_consumer=False):
        assert ordered_consumer is True
        self.subscribed_subject = subject
        return self._sub


@pytest.mark.asyncio
async def test_read_turn_events_stops_at_terminal():
    sub = FakeSub(
        [
            {"seq": 0, "event": {"type": "response.created"}},
            {"seq": 1, "event": {"type": "response.output_text.delta", "delta": "hi"}},
            {"seq": 2, "event": {"type": "response.completed", "response": {"id": "r1"}}},
            {"seq": 99, "event": {"type": "should-not-be-read"}},
        ]
    )
    nc = FakeNC(sub)
    got = [p async for p in read_turn_events(nc, "vystak.multi.streams.c.t")]
    assert [p["seq"] for p in got] == [0, 1, 2]
    assert nc.subscribed_subject == "vystak.multi.streams.c.t"
    assert sub.unsubscribed


@pytest.mark.asyncio
async def test_read_turn_events_idle_timeout():
    sub = FakeSub([{"seq": 0, "event": {"type": "response.created"}}], then_hang=True)
    nc = FakeNC(sub)
    gen = read_turn_events(nc, "s.streams.c.t", idle_timeout_s=0.01)
    assert (await gen.__anext__())["seq"] == 0
    with pytest.raises(TurnStreamIdle):
        await gen.__anext__()
    assert sub.unsubscribed
