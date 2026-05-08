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


def test_tool_description_is_card_driven(monkeypatch):
    """Bootstrap fetches the peer's card and folds name + description + skills
    into the @tool docstring so the LLM sees agent-authored guidance."""
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({"weather": {"card_url": "http://w:8000/.well-known/agent.json"}}),
    )

    def fake_fetch(client, url, **kwargs):
        return {
            "name": "weather",
            "description": "A weather specialist.\nMore detail follows.",
            "skills": [
                {"name": "forecast", "description": "Get weather for a city"},
                {"name": "alerts", "description": "Get severe weather alerts"},
            ],
        }

    monkeypatch.setattr(subagents, "_fetch_card_with_retries", fake_fetch)

    agent = SimpleNamespace(subagents=["weather"])
    tools = build_subagent_tools(agent)
    assert len(tools) == 1
    desc = tools[0].description
    assert "weather — A weather specialist." in desc
    assert "forecast: Get weather for a city" in desc
    assert "alerts: Get severe weather alerts" in desc


def test_tool_description_falls_back_to_boilerplate_when_card_unreachable(monkeypatch):
    """Card fetch failure → keep going with local boilerplate."""
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({"unreachable": {"card_url": "http://nope:8000/.well-known/agent.json"}}),
    )
    monkeypatch.setattr(
        subagents, "_fetch_card_with_retries", lambda client, url, **kwargs: None
    )

    agent = SimpleNamespace(subagents=["unreachable"])
    tools = build_subagent_tools(agent)
    assert len(tools) == 1
    assert "unreachable" in tools[0].description


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


# ---------------------------------------------------------------------------
# NATS dispatch path
# ---------------------------------------------------------------------------


class _FakeNatsReply:
    def __init__(self, data: bytes) -> None:
        self.data = data


class _FakeNatsClient:
    def __init__(self) -> None:
        self.is_closed = False
        self.requests: list[tuple[str, bytes, float]] = []
        self.reply_bytes: bytes | None = None
        self.raise_on_request: Exception | None = None

    async def request(self, subject, payload, timeout):  # noqa: ANN001
        self.requests.append((subject, payload, timeout))
        if self.raise_on_request is not None:
            raise self.raise_on_request
        return _FakeNatsReply(self.reply_bytes or b"{}")

    async def close(self) -> None:
        self.is_closed = True


def _patch_nats(monkeypatch, fake: _FakeNatsClient) -> None:
    import nats

    async def _fake_connect(url, *args, **kwargs):  # noqa: ANN001
        return fake

    monkeypatch.setattr(nats, "connect", _fake_connect)


def test_nats_path_returns_empty_when_url_unset(monkeypatch):
    """NATS transport but no broker URL → log + skip rather than crash."""
    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "nats")
    monkeypatch.delenv("VYSTAK_NATS_URL", raising=False)
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({"weather": {"address": "vystak.default.agents.weather.tasks"}}),
    )
    agent = SimpleNamespace(subagents=["weather"])
    assert build_subagent_tools(agent) == []


def test_nats_path_skips_subagent_without_address(monkeypatch):
    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "nats")
    monkeypatch.setenv("VYSTAK_NATS_URL", "nats://broker:4222")
    monkeypatch.setenv("VYSTAK_ROUTES_JSON", "{}")
    agent = SimpleNamespace(subagents=["weather"])
    assert build_subagent_tools(agent) == []


def test_nats_path_uses_address_directly_as_subject(monkeypatch):
    """The route's `address` field IS the NATS subject (no URL parsing)."""
    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "nats")
    monkeypatch.setenv("VYSTAK_NATS_URL", "nats://broker:4222")
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({
            "weather-agent": {
                "address": "vystak-nats.multi-nats.agents.weather-agent.tasks",
            },
        }),
    )
    agent = SimpleNamespace(subagents=["weather-agent"])
    tools = build_subagent_tools(agent)
    assert len(tools) == 1
    assert tools[0].name == "ask_weather_agent"


@pytest.mark.asyncio
async def test_nats_subagent_tool_publishes_message_send_envelope(monkeypatch):
    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "nats")
    monkeypatch.setenv("VYSTAK_NATS_URL", "nats://broker:4222")
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({
            "weather": {"address": "vystak.default.agents.weather.tasks"},
        }),
    )

    fake = _FakeNatsClient()
    fake.reply_bytes = json.dumps({
        "jsonrpc": "2.0",
        "id": "x",
        "result": {
            "status": {
                "state": "completed",
                "message": {"parts": [{"text": "17C and clear"}]},
            },
        },
    }).encode()
    _patch_nats(monkeypatch, fake)

    agent = SimpleNamespace(subagents=["weather"])
    tools = build_subagent_tools(agent)
    out = await tools[0].ainvoke({"query": "weather in tokyo?"})

    assert out == "17C and clear"
    assert len(fake.requests) == 1
    subject, payload, timeout = fake.requests[0]
    assert subject == "vystak.default.agents.weather.tasks"
    assert timeout == 60
    body = json.loads(payload)
    assert body["jsonrpc"] == "2.0"
    assert body["method"] == "message/send"
    msg = body["params"]["message"]
    assert msg["role"] == "user"
    assert msg["parts"][0]["text"] == "weather in tokyo?"
    # Connection was closed after the call.
    assert fake.is_closed is True


@pytest.mark.asyncio
async def test_nats_subagent_tool_returns_error_message_on_jsonrpc_error(monkeypatch):
    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "nats")
    monkeypatch.setenv("VYSTAK_NATS_URL", "nats://broker:4222")
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({"weather": {"address": "vystak.default.agents.weather.tasks"}}),
    )
    fake = _FakeNatsClient()
    fake.reply_bytes = json.dumps({
        "jsonrpc": "2.0", "id": "x",
        "error": {"code": -32603, "message": "agent crashed"},
    }).encode()
    _patch_nats(monkeypatch, fake)

    agent = SimpleNamespace(subagents=["weather"])
    tools = build_subagent_tools(agent)
    out = await tools[0].ainvoke({"query": "?"})
    assert "weather error" in out
    assert "agent crashed" in out


@pytest.mark.asyncio
async def test_nats_subagent_tool_returns_error_on_timeout(monkeypatch):
    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "nats")
    monkeypatch.setenv("VYSTAK_NATS_URL", "nats://broker:4222")
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({"weather": {"address": "vystak.default.agents.weather.tasks"}}),
    )
    fake = _FakeNatsClient()
    fake.raise_on_request = TimeoutError("no responders")
    _patch_nats(monkeypatch, fake)

    agent = SimpleNamespace(subagents=["weather"])
    tools = build_subagent_tools(agent)
    out = await tools[0].ainvoke({"query": "?"})
    assert "weather error" in out
    assert "no responders" in out


@pytest.mark.asyncio
async def test_nats_subagent_tool_handles_invalid_json_reply(monkeypatch):
    monkeypatch.setenv("VYSTAK_TRANSPORT_TYPE", "nats")
    monkeypatch.setenv("VYSTAK_NATS_URL", "nats://broker:4222")
    monkeypatch.setenv(
        "VYSTAK_ROUTES_JSON",
        json.dumps({"weather": {"address": "vystak.default.agents.weather.tasks"}}),
    )
    fake = _FakeNatsClient()
    fake.reply_bytes = b"not-json"
    _patch_nats(monkeypatch, fake)

    agent = SimpleNamespace(subagents=["weather"])
    tools = build_subagent_tools(agent)
    out = await tools[0].ainvoke({"query": "?"})
    assert "weather error" in out
    assert "invalid reply" in out
