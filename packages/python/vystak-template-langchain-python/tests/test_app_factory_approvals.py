"""HITL approval-gate wiring: checkpoint route interrupts + tool wrapping
at both `build_graph` call sites (initial build + lifespan MCP-rebuild)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from langchain_core.tools import StructuredTool
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.skill import Skill


def _agent(skills=None):
    return Agent(
        name="weather",
        framework="langchain-python",
        instructions="A weather agent.",
        default_model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-6",
        ),
        skills=skills or [],
    )


def _agent_with_gated_skill():
    return _agent(
        skills=[
            Skill(
                name="ops",
                tools=["dangerous"],
                needs_approval=["dangerous"],
            )
        ]
    )


def _dangerous(x: int) -> str:
    return "ran"


def _make_original_tool(name: str = "dangerous"):
    return StructuredTool.from_function(func=_dangerous, name=name, description="d")


# ---------------------------------------------------------------------------
# Checkpoint route interrupts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_app_checkpoint_route_returns_interrupts():
    """The checkpoint route surfaces snapshot.tasks[*].interrupts values."""
    from _vystak.runtime.app_factory import build_agent_app

    payload = {"kind": "tool_approval", "tool": "dangerous", "args": {"x": 1}, "skill": "ops"}

    class _Interrupt:
        value = payload

    class _Task:
        interrupts = (_Interrupt(),)

    class _Snapshot:
        config = {"configurable": {"checkpoint_id": "ck-1"}}
        next = ("tools",)
        tasks = (_Task(),)

    app = build_agent_app(_agent())
    with TestClient(app) as client:
        app.state.graph.aget_state = AsyncMock(return_value=_Snapshot())
        r = client.get("/v1/_vystak/checkpoint", params={"thread_id": "t1"})
    assert r.status_code == 200
    body = r.json()
    assert body["interrupted"] is True
    assert body["interrupts"] == [payload]


@pytest.mark.asyncio
async def test_app_checkpoint_route_interrupts_defaults_empty_when_no_tasks():
    from _vystak.runtime.app_factory import build_agent_app

    app = build_agent_app(_agent())
    with TestClient(app) as client:
        app.state.graph.aget_state = AsyncMock(
            return_value=SimpleNamespace(config={}, next=())
        )
        r = client.get("/v1/_vystak/checkpoint", params={"thread_id": "t2"})
    assert r.json()["interrupts"] == []


def test_app_checkpoint_route_interrupts_empty_for_unseen_thread():
    from _vystak.runtime.app_factory import build_agent_app

    app = build_agent_app(_agent())
    with TestClient(app) as client:
        r = client.get("/v1/_vystak/checkpoint", params={"thread_id": "never-seen"})
    assert r.json() == {"checkpoint_id": None, "interrupted": False, "interrupts": []}


# ---------------------------------------------------------------------------
# Gated tool wrapped at the initial build_graph call site
# ---------------------------------------------------------------------------


def test_gated_tool_wrapped_at_initial_build(monkeypatch):
    from _vystak.runtime import app_factory

    original_tool = _make_original_tool()
    monkeypatch.setattr(app_factory, "load_user_tools", lambda agent, path: [original_tool])

    captured = {}

    def fake_build_graph(agent, *, prompt, tools, checkpointer, model_name=None):
        captured["tools"] = tools
        return SimpleNamespace(aget_state=AsyncMock(return_value=None))

    monkeypatch.setattr(app_factory, "build_graph", fake_build_graph)

    app_factory.build_agent_app(_agent_with_gated_skill())

    tools = captured["tools"]
    gated = next(t for t in tools if t.name == "dangerous")
    assert gated is not original_tool
    assert gated.name == original_tool.name


# ---------------------------------------------------------------------------
# Gated tool wrapped at the lifespan MCP-rebuild call site
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gated_tool_wrapped_at_lifespan_rebuild(monkeypatch):
    from _vystak.runtime import app_factory

    original_tool = _make_original_tool()
    monkeypatch.setattr(app_factory, "load_user_tools", lambda agent, path: [original_tool])

    mcp_tool = StructuredTool.from_function(
        func=lambda: "mcp", name="mcp_tool", description="m"
    )

    async def fake_attach_mcp_servers(agent):
        return [mcp_tool]

    monkeypatch.setattr(app_factory, "attach_mcp_servers", fake_attach_mcp_servers)

    captured_calls = []

    def fake_build_graph(agent, *, prompt, tools, checkpointer, model_name=None):
        captured_calls.append(tools)
        return SimpleNamespace(aget_state=AsyncMock(return_value=None))

    monkeypatch.setattr(app_factory, "build_graph", fake_build_graph)

    app = app_factory.build_agent_app(_agent_with_gated_skill())
    async with app.router.lifespan_context(app):
        pass

    # First call = initial build, second call = lifespan MCP-rebuild.
    assert len(captured_calls) == 2
    rebuild_tools = captured_calls[1]
    names = {getattr(t, "name", None) for t in rebuild_tools}
    assert "mcp_tool" in names
    gated = next(t for t in rebuild_tools if t.name == "dangerous")
    assert gated is not original_tool
