"""build_agent_app integration test — TestClient hits all routes."""

from _vystak.runtime.app_factory import build_agent_app
from fastapi.testclient import TestClient


def _agent():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    return Agent(
        name="weather",
        instructions="A weather agent.",
        model=Model(
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
        instructions="x",
        model=Model(
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
