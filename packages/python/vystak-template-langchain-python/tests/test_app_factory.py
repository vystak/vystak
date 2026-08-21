"""build_agent_app integration test — TestClient hits all routes.

Also tests A2A handler model dispatch helpers:
  pick_model_for_turn, persist_model_choice.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from _vystak.runtime.app_factory import (
    build_agent_app,
    persist_model_choice,
    pick_model_for_turn,
)
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers for model-dispatch tests
# ---------------------------------------------------------------------------

def _model(name: str):
    return SimpleNamespace(
        name=name, model_name="x",
        provider=SimpleNamespace(type="anthropic"),
        parameters={},
    )


def _agent_multi(default_name: str, extra_names: list):
    return SimpleNamespace(
        default_model=_model(default_name),
        models=[_model(n) for n in extra_names],
    )


@pytest.mark.asyncio
async def test_pick_uses_session_stored_when_present():
    sessions = AsyncMock()
    sessions.get_model = AsyncMock(return_value="haiku")
    chosen = await pick_model_for_turn(
        _agent_multi("opus", ["haiku", "sonnet"]),
        sessions=sessions,
        session_id="t1",
        override="sonnet",
    )
    assert chosen == "haiku"


@pytest.mark.asyncio
async def test_pick_uses_override_when_no_session_stored():
    sessions = AsyncMock()
    sessions.get_model = AsyncMock(return_value=None)
    chosen = await pick_model_for_turn(
        _agent_multi("opus", ["haiku"]),
        sessions=sessions,
        session_id="t1",
        override="haiku",
    )
    assert chosen == "haiku"


@pytest.mark.asyncio
async def test_pick_falls_back_to_default_when_no_inputs():
    sessions = AsyncMock()
    sessions.get_model = AsyncMock(return_value=None)
    chosen = await pick_model_for_turn(
        _agent_multi("opus", ["haiku"]),
        sessions=sessions,
        session_id="t1",
        override=None,
    )
    assert chosen == "opus"


@pytest.mark.asyncio
async def test_persist_writes_only_when_no_session_stored():
    sessions = AsyncMock()
    sessions.get_model = AsyncMock(return_value=None)
    sessions.set_model = AsyncMock()
    await persist_model_choice(sessions=sessions, session_id="t1", chosen="haiku")
    sessions.set_model.assert_awaited_once_with("t1", "haiku")


@pytest.mark.asyncio
async def test_persist_skips_when_session_already_has_one():
    sessions = AsyncMock()
    sessions.get_model = AsyncMock(return_value="haiku")
    sessions.set_model = AsyncMock()
    await persist_model_choice(sessions=sessions, session_id="t1", chosen="haiku")
    sessions.set_model.assert_not_called()


def _agent():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    return Agent(
        name="weather",
        framework="langchain-python",
        instructions="A weather agent.",
        default_model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-6",
        ),
    )


def test_app_exposes_agent_card():
    app = build_agent_app(_agent())
    client = TestClient(app)
    r = client.get("/.well-known/agent.json")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "weather"


def test_app_exposes_v1_models():
    app = build_agent_app(_agent())
    client = TestClient(app)
    r = client.get("/v1/models")
    assert r.status_code == 200
    body = r.json()
    assert any(m["id"] == "vystak/weather" for m in body["data"])


def test_app_healthz():
    app = build_agent_app(_agent())
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200


def test_app_chat_completions_route_exists():
    app = build_agent_app(_agent())
    routes = [r.path for r in app.routes]
    assert "/v1/chat/completions" in routes
    assert "/v1/responses" in routes
    assert "/v1/responses/{response_id}" in routes
    assert "/a2a" in routes


def test_app_resume_route_exists_and_is_not_on_agent_card():
    app = build_agent_app(_agent())
    routes = [r.path for r in app.routes]
    assert "/v1/_vystak/resume" in routes

    client = TestClient(app)
    card = client.get("/.well-known/agent.json").json()
    card_text = str(card)
    assert "_vystak/resume" not in card_text


def test_app_resume_requires_thread_id():
    app = build_agent_app(_agent())
    client = TestClient(app)
    r = client.post("/v1/_vystak/resume", json={})
    assert r.status_code == 400


def test_app_checkpoint_route_exists_and_is_not_on_agent_card():
    app = build_agent_app(_agent())
    routes = [r.path for r in app.routes]
    assert "/v1/_vystak/checkpoint" in routes

    client = TestClient(app)
    card = client.get("/.well-known/agent.json").json()
    assert "_vystak/checkpoint" not in str(card)


def test_app_checkpoint_route_returns_null_for_unseen_thread():
    app = build_agent_app(_agent())
    with TestClient(app) as client:
        r = client.get("/v1/_vystak/checkpoint", params={"thread_id": "never-seen"})
    assert r.status_code == 200
    assert r.json() == {"checkpoint_id": None, "interrupted": False, "interrupts": []}


def test_app_checkpoint_route_reflects_a_stored_checkpoint():
    """Exercises the id-extraction branch (`snapshot.config` non-empty)
    directly against a fake graph, without a real LLM round-trip — mirrors
    how `_run_detached`'s SSE consumption is tested against fakes rather
    than a live model."""
    from _vystak.runtime.app_factory import build_agent_app

    app = build_agent_app(_agent())
    with TestClient(app) as client:
        app.state.graph.aget_state = AsyncMock(
            return_value=SimpleNamespace(
                config={"configurable": {"checkpoint_id": "ck-9"}}, next=()
            )
        )
        r = client.get("/v1/_vystak/checkpoint", params={"thread_id": "resp_ck_1"})
    assert r.status_code == 200
    assert r.json() == {"checkpoint_id": "ck-9", "interrupted": False, "interrupts": []}


def test_app_checkpoint_route_reports_interrupted_when_graph_is_parked():
    from _vystak.runtime.app_factory import build_agent_app

    app = build_agent_app(_agent())
    with TestClient(app) as client:
        app.state.graph.aget_state = AsyncMock(
            return_value=SimpleNamespace(config={}, next=("approve",))
        )
        r = client.get("/v1/_vystak/checkpoint", params={"thread_id": "resp_ck_2"})
    assert r.status_code == 200
    assert r.json() == {"checkpoint_id": None, "interrupted": True, "interrupts": []}


def test_app_builds_with_sqlite_sessions_config():
    """Agent with sessions: sqlite must build without TypeError.

    `build_checkpointer` returns a `_LazyCheckpointer` for sqlite/postgres
    engines because their savers are async-only context managers. LangGraph's
    compile() rejects `_LazyCheckpointer` as not a `BaseCheckpointSaver`. The
    fix builds the graph with checkpointer=None initially and swaps in the
    resolved saver during the FastAPI lifespan startup.
    """
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak.schema.service import Sqlite

    agent = Agent(
        name="test",
        framework="langchain-python",
        instructions="x",
        default_model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-6",
        ),
        sessions=Sqlite(name="sessions"),
    )
    # This should NOT raise TypeError("Invalid checkpointer provided").
    app = build_agent_app(agent)
    assert app is not None
    # The graph compiled (we used checkpointer=None for the lazy case).
    routes = [r.path for r in app.routes]
    assert "/healthz" in routes


def test_lifespan_wires_checkpoint_observer_onto_state():
    """`build_checkpointer` is always lazy (durable-by-default, Task 1), so
    the `is_lazy` branch in the lifespan always runs and always creates a
    `CheckpointObserver`, regardless of whether the agent declares
    `sessions`. This asserts that invariant directly rather than assuming
    it — the Responses stream's checkpoint markers depend on it.
    """
    app = build_agent_app(_agent())
    with TestClient(app):
        assert hasattr(app.state, "checkpoint_observer")
        from _vystak.runtime.store import CheckpointObserver

        assert isinstance(app.state.checkpoint_observer, CheckpointObserver)
