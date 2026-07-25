"""Persister worker tests with a fake NATS client."""

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


class FakeRuntime:
    def __init__(self, store, nats_client):
        self.panel_store = store
        self.nats_client = nats_client
        self.turn_tasks = {}


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


def test_turn_subject_for():
    from vystak_channel_panel.nats_client import PanelNatsClient

    entry = {
        "canonical": "time-agent.agents.multi",
        "address": "vystak.multi.agents.time-agent.tasks",
    }
    assert PanelNatsClient.turn_subject_for(entry, "c1", "t1") == "vystak.multi.streams.c1.t1"
