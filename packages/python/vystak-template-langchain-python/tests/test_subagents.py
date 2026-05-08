"""build_subagent_tools — generates ask_<name> tools that call peers via a2a-sdk."""

import json
from types import SimpleNamespace

import pytest
from _vystak.runtime import subagents
from _vystak.runtime.subagents import build_subagent_tools
from a2a.types import (
    Message,
    Part,
    Role,
    StreamResponse,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)


def test_no_subagents_returns_empty_list():
    agent = SimpleNamespace(subagents=[])
    assert build_subagent_tools(agent) == []


def test_subagent_without_route_is_skipped(monkeypatch):
    monkeypatch.setenv("VYSTAK_ROUTES_JSON", "{}")
    agent = SimpleNamespace(subagents=["weather"])
    assert build_subagent_tools(agent) == []


def test_card_url_field_takes_precedence(monkeypatch):
    """`card_url` is the new shape; provider should emit it directly."""
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({
            "weather": {"card_url": "http://w:8000/.well-known/agent.json"},
        }),
    )
    agent = SimpleNamespace(subagents=["weather"])
    tools = build_subagent_tools(agent)
    assert len(tools) == 1
    assert tools[0].name == "ask_weather"


def test_card_url_derived_from_address(monkeypatch):
    """Legacy routes only had `address` (RPC URL); the helper derives card_url."""
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({"weather": {"address": "http://w:8000/a2a"}}),
    )
    agent = SimpleNamespace(subagents=["weather"])
    tools = build_subagent_tools(agent)
    assert len(tools) == 1


def test_subagent_name_with_hyphen_is_sanitized(monkeypatch):
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({"data-agent": {"card_url": "http://d:8000/.well-known/agent.json"}}),
    )
    agent = SimpleNamespace(subagents=["data-agent"])
    tools = build_subagent_tools(agent)
    assert tools[0].name == "ask_data_agent"


class FakeClient:
    """Minimal stand-in for a2a-sdk's Client that yields canned events."""

    def __init__(self, events):
        self._events = events
        self.closed = False
        self.last_request = None

    async def send_message(self, request):  # noqa: ANN001
        self.last_request = request
        for ev in self._events:
            yield ev

    async def close(self):
        self.closed = True


def _make_task_event(text: str) -> StreamResponse:
    """Build a StreamResponse whose task carries `text` in status.message."""
    msg = Message(role=Role.ROLE_AGENT, message_id="m-1", parts=[Part(text=text)])
    task = Task(
        id="t-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED, message=msg),
    )
    sr = StreamResponse()
    sr.task.CopyFrom(task)
    return sr


def _make_message_event(text: str) -> StreamResponse:
    msg = Message(role=Role.ROLE_AGENT, message_id="m-1", parts=[Part(text=text)])
    sr = StreamResponse()
    sr.message.CopyFrom(msg)
    return sr


def _make_status_update_event(text: str, state=TaskState.TASK_STATE_COMPLETED) -> StreamResponse:
    """Real servers stream Task → status_update(working) → status_update(completed-with-message)."""
    msg = Message(role=Role.ROLE_AGENT, message_id="m-1", parts=[Part(text=text)])
    update = TaskStatusUpdateEvent(
        task_id="t-1",
        context_id="ctx-1",
        status=TaskStatus(state=state, message=msg),
    )
    sr = StreamResponse()
    sr.status_update.CopyFrom(update)
    return sr


@pytest.mark.asyncio
async def test_subagent_tool_returns_task_status_text(monkeypatch):
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({"weather": {"card_url": "http://w:8000/.well-known/agent.json"}}),
    )
    fake_client = FakeClient([_make_task_event("the answer is 42")])
    captured: dict[str, str] = {}

    async def fake_create_client(*, agent, relative_card_path=None):  # noqa: ANN001
        captured["agent"] = agent
        captured["relative_card_path"] = relative_card_path
        return fake_client

    monkeypatch.setattr(subagents, "create_client", fake_create_client)

    agent = SimpleNamespace(subagents=["weather"])
    tools = build_subagent_tools(agent)
    out = await tools[0].ainvoke({"query": "what is the weather?"})

    assert out == "the answer is 42"
    assert fake_client.closed is True
    # The query made it onto the wire as a TextPart.
    assert fake_client.last_request.message.parts[0].text == "what is the weather?"
    # Verify URL was split correctly so the SDK doesn't double up the path.
    assert captured["agent"] == "http://w:8000"
    assert captured["relative_card_path"] == "/.well-known/agent.json"


@pytest.mark.asyncio
async def test_subagent_tool_returns_status_update_completion_text(monkeypatch):
    """Real servers stream Task(submitted) -> status_update(working) ->
    status_update(completed-with-message). The tool must read the LAST
    status_update and ignore the empty intermediate ones."""
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({"weather": {"card_url": "http://w:8000/.well-known/agent.json"}}),
    )

    # Initial Task event (no message), then a working status (no message),
    # then a completed status with the actual reply.
    initial_task = StreamResponse()
    initial_task.task.CopyFrom(Task(id="t-1", context_id="ctx-1",
                                    status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED)))
    working = _make_status_update_event("", state=TaskState.TASK_STATE_WORKING)
    # Override: working state should have no message, simulate that.
    working.status_update.status.ClearField("message")
    final = _make_status_update_event("17C and clear", state=TaskState.TASK_STATE_COMPLETED)

    fake_client = FakeClient([initial_task, working, final])

    async def fake_create_client(*, agent, relative_card_path=None):  # noqa: ANN001
        return fake_client

    monkeypatch.setattr(subagents, "create_client", fake_create_client)

    agent = SimpleNamespace(subagents=["weather"])
    tools = build_subagent_tools(agent)
    out = await tools[0].ainvoke({"query": "weather?"})

    assert out == "17C and clear"


@pytest.mark.asyncio
async def test_subagent_tool_returns_message_event_text(monkeypatch):
    """Some servers reply with a Message event (not wrapped in a Task)."""
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({"weather": {"card_url": "http://w:8000/.well-known/agent.json"}}),
    )
    fake_client = FakeClient([_make_message_event("hello")])

    async def fake_create_client(*, agent, relative_card_path=None):  # noqa: ANN001
        return fake_client

    monkeypatch.setattr(subagents, "create_client", fake_create_client)

    agent = SimpleNamespace(subagents=["weather"])
    tools = build_subagent_tools(agent)
    out = await tools[0].ainvoke({"query": "hi"})

    assert out == "hello"


@pytest.mark.asyncio
async def test_subagent_tool_swallows_client_errors(monkeypatch):
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({"weather": {"card_url": "http://w:8000/.well-known/agent.json"}}),
    )

    async def fake_create_client(*, agent, relative_card_path=None):  # noqa: ANN001
        raise RuntimeError("connection refused")

    monkeypatch.setattr(subagents, "create_client", fake_create_client)

    agent = SimpleNamespace(subagents=["weather"])
    tools = build_subagent_tools(agent)
    out = await tools[0].ainvoke({"query": "hi"})
    assert "weather error" in out
    assert "connection refused" in out
