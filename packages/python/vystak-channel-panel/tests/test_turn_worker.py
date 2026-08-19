"""Persister worker tests with a fake NATS client."""

import asyncio

import pytest
from vystak_channel_panel.responses_client import PanelStreamEvent
from vystak_channel_panel.turn_worker import run_turn_persister
from vystak_transport_nats.streams import TurnStreamIdle


class FakeNatsClient:
    def __init__(self, events, *, idle=False):
        self._events = events
        self._idle = idle

    async def stream_turn_events(self, subject):
        for seq, ev in enumerate(self._events):
            yield seq, ev
        if self._idle:
            raise TurnStreamIdle(subject)

    async def turn_status(self, agent_name, turn_id):
        # No agent to ask in these tests — a terminal status here preserves
        # the pre-Task-10 idle-timeout persist-partial-and-conclude behavior.
        return "failed"


class FakeNatsClientRaises:
    """Simulates a transient infra failure (e.g. JetStream subscribe error)
    unrelated to the turn's own lifecycle — must NOT be treated like
    TurnStreamIdle or an `error` terminal event."""

    async def stream_turn_events(self, subject):
        raise RuntimeError("jetstream subscribe failed")
        yield  # pragma: no cover — makes this an async generator


class FakeNatsClientCancels:
    """Simulates the task being cancelled mid-stream-read. CancelledError is
    a BaseException, not an Exception, so it is never caught by the
    `except Exception` handlers inside run_turn_persister — it must still
    reach the outer try/finally that pops turn_tasks (Fix 3)."""

    async def stream_turn_events(self, subject):
        raise asyncio.CancelledError()
        yield  # pragma: no cover — makes this an async generator


class FakeRuntime:
    def __init__(self, store, nats_client):
        self.panel_store = store
        self.nats_client = nats_client
        self.turn_tasks = {}
        self.routes = {"time-agent": {"canonical": "time-agent.agents.default"}}

    def monotonic(self):
        return 0.0


@pytest.fixture
async def panel_store(tmp_path):
    from vystak_channel_panel.store import SqlitePanelStore

    s = SqlitePanelStore(tmp_path / "panel.db")
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
async def conversation(panel_store):
    user = await panel_store.create_user("a@example.com", role="admin")
    proj = await panel_store.create_project("P", user.id)
    return await panel_store.create_conversation(proj.id, user.id, "time-agent")


@pytest.mark.asyncio
async def test_persister_writes_row_and_clears_turn(panel_store, conversation):
    # `panel_store` / `conversation` fixtures: connected store + a
    # conversation row — mirror conftest.py's existing fixtures.
    await panel_store.set_active_turn(conversation.id, "t1")
    rt = FakeRuntime(
        panel_store,
        FakeNatsClient(
            [
                PanelStreamEvent(type="token", text="hel"),
                PanelStreamEvent(type="token", text="lo"),
                PanelStreamEvent(type="done", response_id="resp_9"),
            ]
        ),
    )
    await run_turn_persister(rt, conversation.id, "t1", "subj")

    msgs = await panel_store.list_messages(conversation.id)
    assistant = [m for m in msgs if m.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].content == "hello"
    assert assistant[0].turn_id == "t1"
    assert assistant[0].response_id == "resp_9"
    conv = await panel_store.get_conversation(conversation.id)
    assert conv.active_turn_id is None
    assert conv.last_response_id == "resp_9"


@pytest.mark.asyncio
async def test_persister_error_event_persists_partial(panel_store, conversation):
    await panel_store.set_active_turn(conversation.id, "t2")
    rt = FakeRuntime(
        panel_store,
        FakeNatsClient(
            [
                PanelStreamEvent(type="token", text="par"),
                PanelStreamEvent(type="error", text="boom"),
            ]
        ),
    )
    await run_turn_persister(rt, conversation.id, "t2", "subj")
    assistant = [
        m for m in await panel_store.list_messages(conversation.id) if m.role == "assistant"
    ]
    assert len(assistant) == 1
    assert assistant[0].content == "par"
    assert assistant[0].response_id is None
    conv = await panel_store.get_conversation(conversation.id)
    assert conv.active_turn_id is None
    assert conv.last_response_id is None  # untouched on error


@pytest.mark.asyncio
async def test_persister_error_with_no_output_writes_no_row(panel_store, conversation):
    await panel_store.set_active_turn(conversation.id, "t3")
    rt = FakeRuntime(
        panel_store,
        FakeNatsClient(
            [
                PanelStreamEvent(type="error", text="boom"),
            ]
        ),
    )
    await run_turn_persister(rt, conversation.id, "t3", "subj")
    assert [
        m for m in await panel_store.list_messages(conversation.id) if m.role == "assistant"
    ] == []
    assert (await panel_store.get_conversation(conversation.id)).active_turn_id is None


@pytest.mark.asyncio
async def test_persister_idle_timeout_persists_partial(panel_store, conversation):
    await panel_store.set_active_turn(conversation.id, "t4")
    rt = FakeRuntime(
        panel_store, FakeNatsClient([PanelStreamEvent(type="token", text="part")], idle=True)
    )
    await run_turn_persister(rt, conversation.id, "t4", "subj")
    assistant = [
        m for m in await panel_store.list_messages(conversation.id) if m.role == "assistant"
    ]
    assert len(assistant) == 1 and assistant[0].content == "part"
    assert (await panel_store.get_conversation(conversation.id)).active_turn_id is None


@pytest.mark.asyncio
async def test_persister_infra_failure_leaves_turn_active_for_retry(panel_store, conversation):
    await panel_store.set_active_turn(conversation.id, "t5")
    rt = FakeRuntime(panel_store, FakeNatsClientRaises())
    rt.turn_tasks["t5"] = object()

    await run_turn_persister(rt, conversation.id, "t5", "subj")

    assert [
        m for m in await panel_store.list_messages(conversation.id) if m.role == "assistant"
    ] == []
    conv = await panel_store.get_conversation(conversation.id)
    assert conv.active_turn_id == "t5"
    assert "t5" not in rt.turn_tasks


@pytest.mark.asyncio
async def test_persister_cancelled_error_still_pops_task(panel_store, conversation):
    """CancelledError escapes uncaught (nothing here should swallow task
    cancellation) but must still pop turn_tasks and must not clear the
    active turn, since we don't know whether cancellation happened before
    or after any write (Fix 3)."""
    await panel_store.set_active_turn(conversation.id, "t9")
    rt = FakeRuntime(panel_store, FakeNatsClientCancels())
    rt.turn_tasks["t9"] = object()

    with pytest.raises(asyncio.CancelledError):
        await run_turn_persister(rt, conversation.id, "t9", "subj")

    assert "t9" not in rt.turn_tasks
    conv = await panel_store.get_conversation(conversation.id)
    assert conv.active_turn_id == "t9"


class _RaisingAddMessageStore:
    """Wraps a real store; add_message always raises to simulate a
    persist-time store failure (e.g. disk full) after a clean stream
    terminal has already been observed."""

    def __init__(self, inner):
        self._inner = inner

    async def add_message(self, *args, **kwargs):
        raise RuntimeError("disk full")

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.mark.asyncio
async def test_persister_store_failure_after_done_leaves_turn_active(panel_store, conversation):
    """A store failure in the persist block (after a clean `done`) must not
    clear active_turn_id — otherwise JetStream still holds the turn's output
    but nothing will ever retry persisting it (Fix 1)."""
    await panel_store.set_active_turn(conversation.id, "t6")
    rt = FakeRuntime(
        _RaisingAddMessageStore(panel_store),
        FakeNatsClient([PanelStreamEvent(type="done", response_id="resp_6")]),
    )
    rt.turn_tasks["t6"] = object()

    await run_turn_persister(rt, conversation.id, "t6", "subj")

    assert [
        m for m in await panel_store.list_messages(conversation.id) if m.role == "assistant"
    ] == []
    conv = await panel_store.get_conversation(conversation.id)
    assert conv.active_turn_id == "t6"
    assert "t6" not in rt.turn_tasks


@pytest.mark.asyncio
async def test_persister_rescan_skips_duplicate_insert(panel_store, conversation):
    """Simulates a restart replay of a turn that crashed between
    `add_message` and `clear_active_turn`: the assistant row is already
    there, so the rescan must not insert a second one but must still clear
    the active turn (the crashed-half completing) (Fix 2)."""
    await panel_store.set_active_turn(conversation.id, "t7")
    await panel_store.add_message(
        conversation.id, "assistant", "hello", response_id="resp_7", turn_id="t7"
    )
    rt = FakeRuntime(
        panel_store,
        FakeNatsClient([PanelStreamEvent(type="done", response_id="resp_7")]),
    )

    await run_turn_persister(rt, conversation.id, "t7", "subj")

    assistant = [
        m for m in await panel_store.list_messages(conversation.id) if m.role == "assistant"
    ]
    assert len(assistant) == 1
    conv = await panel_store.get_conversation(conversation.id)
    assert conv.active_turn_id is None


def test_turn_subject_for():
    from vystak_channel_panel.nats_client import PanelNatsClient

    entry = {
        "canonical": "time-agent.agents.multi",
        "address": "vystak.multi.agents.time-agent.tasks",
    }
    assert PanelNatsClient.turn_subject_for(entry, "c1", "t1") == "vystak.multi.streams.c1.t1"
