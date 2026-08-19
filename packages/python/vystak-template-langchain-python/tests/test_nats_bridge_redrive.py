import json

import httpx
import pytest
from _vystak.runtime.nats_bridge import MAX_REDRIVE_ATTEMPTS
from _vystak.runtime.turn_journal import InMemoryTurnJournal


@pytest.mark.asyncio
async def test_rewind_targets_the_resumed_checkpoint(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {"input": "hi"})
    await journal.set_thread_id("t1", "resp_1")
    await journal.record_boundary("t1", "ck-1", 3)
    await journal.record_boundary("t1", "ck-2", 8)
    await journal.set_last_seq("t1", 12)

    # LangGraph will resume from ck-1, not the last boundary we observed.
    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-1")
    await bridge.redrive_unfinished()

    first = json.loads(bridge.published_payloads[0])
    assert first["seq"] == 13
    assert first["event"] == {"type": "vystak.turn.rewind", "to_seq": 3}


@pytest.mark.asyncio
async def test_falls_back_to_boundary_seq_when_checkpoint_unknown(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_thread_id("t1", "resp_1")
    await journal.record_boundary("t1", "ck-2", 8)
    await journal.set_last_seq("t1", 12)

    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-unknown")
    await bridge.redrive_unfinished()

    assert json.loads(bridge.published_payloads[0])["event"]["to_seq"] == 8


@pytest.mark.asyncio
async def test_parked_turns_are_not_redriven(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_status("t1", "parked")
    bridge = bridge_factory(journal=journal)
    assert await bridge.redrive_unfinished() == 0
    assert bridge.published_payloads == []


@pytest.mark.asyncio
async def test_attempts_cap_fails_the_turn(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_last_seq("t1", 5)
    for _ in range(MAX_REDRIVE_ATTEMPTS):
        await journal.bump_attempts("t1")

    bridge = bridge_factory(journal=journal)
    await bridge.redrive_unfinished()

    assert (await journal.get("t1")).status == "failed"
    published = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert published == ["response.failed"]


@pytest.mark.asyncio
async def test_attempts_increment_on_redrive(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_thread_id("t1", "resp_1")
    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-1")
    await bridge.redrive_unfinished()
    assert (await journal.get("t1")).attempts == 1


@pytest.mark.asyncio
async def test_turn_with_no_thread_id_fails_immediately_without_a_rewind(bridge_factory):
    # A turn that crashed before `response.created` ever arrived has no
    # thread_id — there is nothing the resume endpoint can drive. It should
    # be failed on the spot, without wasting a rewind marker on a resume
    # that's guaranteed to be impossible.
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_last_seq("t1", 5)

    bridge = bridge_factory(journal=journal)
    await bridge.redrive_unfinished()

    assert (await journal.get("t1")).status == "failed"
    published = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert published == ["response.failed"]


# ---------------------------------------------------------------------------
# Fix 1: the sweep must wait for the local server to be accepting
# connections before hitting /v1/_vystak/checkpoint or /v1/_vystak/resume.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_until_ready_retries_until_healthz_is_200(bridge_factory):
    bridge = bridge_factory(healthz_failures=2)
    ready = await bridge._wait_until_ready(timeout=1.0, interval=0.01)
    assert ready is True
    healthz_calls = [r for r in bridge.requests if r["path"] == "/healthz"]
    assert len(healthz_calls) >= 3


@pytest.mark.asyncio
async def test_wait_until_ready_times_out_when_server_never_comes_up(bridge_factory):
    bridge = bridge_factory(healthz_failures=10_000)
    ready = await bridge._wait_until_ready(timeout=0.05, interval=0.01)
    assert ready is False


@pytest.mark.asyncio
async def test_redrive_after_ready_skips_the_sweep_when_never_ready(bridge_factory, monkeypatch):
    bridge = bridge_factory(journal=InMemoryTurnJournal())
    called = {"n": 0}

    async def _never_ready(**kwargs):
        return False

    async def _fake_redrive():
        called["n"] += 1
        return 0

    monkeypatch.setattr(bridge, "_wait_until_ready", _never_ready)
    monkeypatch.setattr(bridge, "redrive_unfinished", _fake_redrive)

    await bridge._redrive_after_ready()
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_redrive_after_ready_sweeps_once_the_server_is_ready(bridge_factory, monkeypatch):
    bridge = bridge_factory(journal=InMemoryTurnJournal())
    called = {"n": 0}

    async def _ready(**kwargs):
        return True

    async def _fake_redrive():
        called["n"] += 1
        return 0

    monkeypatch.setattr(bridge, "_wait_until_ready", _ready)
    monkeypatch.setattr(bridge, "redrive_unfinished", _fake_redrive)

    await bridge._redrive_after_ready()
    assert called["n"] == 1


# ---------------------------------------------------------------------------
# Fix 2: resume_stream always re-emits response.created for the resumed
# thread. It's a duplicate (drop it) only when the rewind target kept the
# original; when the rewind discarded everything (to_seq < 0) the re-emitted
# copy is the only one consumers will ever see (publish it).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_response_created_dropped_when_original_survives_rewind(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_thread_id("t1", "resp_1")
    await journal.record_boundary("t1", "ck-1", 3)  # to_seq will be 3, >= 0
    await journal.set_last_seq("t1", 12)

    bridge = bridge_factory(
        journal=journal,
        resume_checkpoint_id="ck-1",
        sse_events=[
            {"type": "response.created", "response": {"id": "resp_1"}},
            {"type": "response.completed", "response": {"id": "resp_1"}},
        ],
    )
    await bridge.redrive_unfinished()

    published_types = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert published_types == ["vystak.turn.rewind", "response.completed"]


@pytest.mark.asyncio
async def test_response_created_kept_when_rewind_discards_everything(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_thread_id("t1", "resp_1")
    await journal.set_last_seq("t1", 12)  # no boundary ever recorded -> to_seq falls back to -1

    bridge = bridge_factory(
        journal=journal,
        resume_checkpoint_id="ck-unknown",
        sse_events=[
            {"type": "response.created", "response": {"id": "resp_1"}},
            {"type": "response.completed", "response": {"id": "resp_1"}},
        ],
    )
    await bridge.redrive_unfinished()

    published_types = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert published_types == [
        "vystak.turn.rewind",
        "response.created",
        "response.completed",
    ]


# ---------------------------------------------------------------------------
# Fix 3: one turn erroring mid-redrive must not abort the sweep of the rest.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_turn_erroring_does_not_abort_the_sweep(bridge_factory, monkeypatch):
    from _vystak.runtime import nats_bridge as nats_bridge_module

    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_thread_id("t1", "resp_1")
    await journal.create("t2", "s.t2", {})
    await journal.set_thread_id("t2", "resp_2")

    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-1")

    async def _boom_for_t1(js, base):  # noqa: ANN001
        if base == "s.t1":
            raise RuntimeError("boom")
        return None

    monkeypatch.setattr(nats_bridge_module, "_ensure_turn_stream", _boom_for_t1)

    count = await bridge.redrive_unfinished()

    assert count == 1  # t1 raised, t2 was still swept
    t1 = await journal.get("t1")
    t2 = await journal.get("t2")
    assert t1.status == "running"  # left eligible for the next restart's sweep
    assert t1.attempts == 1
    assert t2.attempts == 1
    published = [json.loads(p)["event"]["type"] for p in bridge.published_payloads]
    assert published == ["vystak.turn.rewind"]  # only t2's rewind marker


# ---------------------------------------------------------------------------
# Fix 4: seq continuity across the rewind, and the resume request actually
# targets the right endpoints with the right thread_id.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resumed_stream_seq_continues_after_the_rewind_marker(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_thread_id("t1", "resp_1")
    await journal.record_boundary("t1", "ck-1", 3)
    await journal.set_last_seq("t1", 12)

    bridge = bridge_factory(
        journal=journal,
        resume_checkpoint_id="ck-1",
        sse_events=[
            {"type": "response.created", "response": {"id": "resp_1"}},
            {"type": "response.output_text.delta", "delta": "x"},
        ],
    )
    await bridge.redrive_unfinished()

    payloads = [json.loads(p) for p in bridge.published_payloads]
    assert payloads[0]["seq"] == 13
    assert payloads[0]["event"]["type"] == "vystak.turn.rewind"
    # response.created is suppressed (to_seq=3 >= 0); the next thing
    # actually published is the delta, and it must land right after the
    # rewind marker's seq, with no gap.
    assert payloads[1]["seq"] == 14
    assert payloads[1]["event"]["type"] == "response.output_text.delta"


@pytest.mark.asyncio
async def test_redrive_hits_checkpoint_then_resume_with_the_right_thread_id(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("t1", "s.t1", {})
    await journal.set_thread_id("t1", "resp_1")
    await journal.set_last_seq("t1", 12)

    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-1")
    await bridge.redrive_unfinished()

    checkpoint_req = next(r for r in bridge.requests if r["path"] == "/v1/_vystak/checkpoint")
    assert checkpoint_req["method"] == "GET"

    resume_req = next(r for r in bridge.requests if r["path"] == "/v1/_vystak/resume")
    assert resume_req["method"] == "POST"
    assert resume_req["json"] == {"thread_id": "resp_1"}


# ---------------------------------------------------------------------------
# Follow-up fix: the readiness-gated sweep can lag up to _wait_until_ready's
# timeout behind subscribe(). Without a snapshot, a `responses/createDetached`
# that arrives right after subscribe would create a `running` journal row the
# delayed sweep could then pick up while `_run_detached` is concurrently
# handling it live — both paths publishing into the same stream_subject and
# writing last_seq/status for the same turn_id. `start()` snapshots the set
# of `running` turn_ids *before* subscribing; the sweep only ever touches
# turn_ids in that snapshot.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redrive_unfinished_skips_turns_outside_the_orphan_snapshot(bridge_factory):
    journal = InMemoryTurnJournal()
    await journal.create("orphan", "s.orphan", {})
    await journal.set_thread_id("orphan", "resp_orphan")
    await journal.create("live", "s.live", {})
    await journal.set_thread_id("live", "resp_live")

    bridge = bridge_factory(journal=journal, resume_checkpoint_id="ck-1")
    # Simulate what `start()` does before subscribing: snapshot only the
    # pre-existing "orphan" row. "live" was (hypothetically) created by a
    # message that arrived after subscribe and must never be swept.
    bridge._orphaned_turn_ids = {"orphan"}

    count = await bridge.redrive_unfinished()

    assert count == 1
    assert (await journal.get("orphan")).attempts == 1
    assert (await journal.get("live")).attempts == 0
    assert (await journal.get("live")).status == "running"


@pytest.mark.asyncio
async def test_orphan_snapshot_via_real_start_excludes_post_subscribe_turns(monkeypatch):
    """Drives the real start() -> snapshot -> subscribe -> background-sweep
    seam (not just redrive_unfinished() in isolation): a pre-existing orphan
    gets swept, a turn "created" during the subscribe call (simulating a
    message arriving the instant subscribe opens) does not.
    """
    import nats
    from _vystak.runtime.nats_bridge import NatsHttpBridge

    journal = InMemoryTurnJournal()
    await journal.create(
        "orphan", "vystak.default.agents.hero.streams.conv1.orphan", {}
    )
    await journal.set_thread_id("orphan", "resp_orphan")

    class _FakeSub:
        async def unsubscribe(self) -> None:
            return None

    class _FakeJetStream:
        def __init__(self) -> None:
            self.published: list[bytes] = []

        async def add_stream(self, cfg):  # noqa: ANN001
            return None

        async def update_stream(self, cfg):  # noqa: ANN001
            return None

        async def publish(self, subject, payload):  # noqa: ANN001
            self.published.append(payload)

    js = _FakeJetStream()

    class _FakeNc:
        async def subscribe(self, subject, queue=None, cb=None):  # noqa: ANN001
            # A fresh inbound createDetached, arriving the instant this
            # process starts listening — strictly after the pre-subscribe
            # snapshot was taken.
            await journal.create(
                "live", "vystak.default.agents.hero.streams.conv1.live", {}
            )
            await journal.set_thread_id("live", "resp_live")
            return _FakeSub()

        def jetstream(self):
            return js

        async def close(self) -> None:
            return None

    async def _fake_connect(url, *args, **kwargs):  # noqa: ANN001
        return _FakeNc()

    monkeypatch.setattr(nats, "connect", _fake_connect)

    checkpoint_thread_ids: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":
            return httpx.Response(200)
        if request.url.path == "/v1/_vystak/checkpoint":
            checkpoint_thread_ids.append(request.url.params.get("thread_id"))
            return httpx.Response(200, json={"checkpoint_id": None})
        return httpx.Response(
            200, content=b"data: [DONE]\n\n", headers={"content-type": "text/event-stream"}
        )

    _real_async_client = httpx.AsyncClient

    def _fake_async_client(*args, **kwargs):  # noqa: ANN002, ANN003
        return _real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client)

    bridge = NatsHttpBridge(
        nats_url="nats://ignored:4222",
        subject="vystak.default.agents.hero.tasks",
        queue_group="agents.hero",
        local_url="http://localhost:8000/a2a",
        local_base="http://localhost:8000",
        journal=journal,
    )
    await bridge.start()
    assert bridge._redrive_task is not None
    await bridge._redrive_task  # drive the background sweep to completion

    orphan = await journal.get("orphan")
    live = await journal.get("live")

    assert orphan.attempts == 1  # pre-existing orphan: swept
    assert live.attempts == 0  # created after subscribe: never swept
    assert live.status == "running"
    # The sweep only ever looked up the pre-existing turn's checkpoint.
    assert checkpoint_thread_ids == ["resp_orphan"]

    await bridge.stop()
