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
