"""A2AAgentClient.resume_turn / NatsAgentClient.resume_turn -- Task 11.

Deviation from the original brief's `-> str`: both return an `AgentReply`-
shaped result (`.text` + `.pending_approval`) so a caller can uniformly
detect a resumed run parking AGAIN on a second gated tool ("chaining")
without a second return shape. See docstrings on the implementations in
`agent_client.py`.
"""

import json

import httpx
import pytest
from vystak_channel_runtime.agent_client import A2AAgentClient, NatsAgentClient
from vystak_channel_runtime.types import AgentReply

pytestmark = pytest.mark.asyncio

PAYLOAD_2 = {"kind": "tool_approval", "tool": "delete_db", "args": {"table": "x"}, "skill": "ops"}


class _FakeStreamResponse:
    def __init__(self, status_code: int, lines: list[str] | None = None):
        self.status_code = status_code
        self._lines = lines or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeGetResponse:
    def __init__(self, json_body: dict):
        self._json = json_body

    def raise_for_status(self):
        return None

    def json(self):
        return self._json


# ---------------------------------------------------------------------------
# A2AAgentClient
# ---------------------------------------------------------------------------


async def test_resume_turn_concatenates_deltas_on_completion(monkeypatch):
    calls: dict[str, dict] = {}

    def fake_stream(self, method, url, *, json, timeout):
        calls["method"] = method
        calls["url"] = url
        calls["body"] = json
        lines = [
            'data: {"type":"response.output_text.delta","delta":"All "}',
            'data: {"type":"response.output_text.delta","delta":"done."}',
            'data: {"type":"response.completed"}',
            "data: [DONE]",
        ]
        return _FakeStreamResponse(200, lines=lines)

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)

    client = A2AAgentClient()
    client._known_bases["t1"] = "http://hero:8000"

    result = await client.resume_turn("t1", {"approved": True, "decided_by": "@x", "note": None})

    assert isinstance(result, AgentReply)
    assert result.text == "All done."
    assert result.pending_approval is None
    assert calls["method"] == "POST"
    assert calls["url"] == "http://hero:8000/v1/_vystak/resume"
    assert calls["body"] == {
        "thread_id": "t1",
        "resume": {"approved": True, "decided_by": "@x", "note": None},
    }


async def test_resume_turn_raises_without_known_base():
    client = A2AAgentClient()
    with pytest.raises(RuntimeError):
        await client.resume_turn("unknown-thread", {"approved": True})


async def test_send_turn_aliases_pending_approval_marker_thread_id(monkeypatch):
    """The `approval_pending` marker's thread_id (executor.py's
    `context.task_id`) is a DIFFERENT string than the contextId the channel
    sent as `thread_id` to send_turn -- resume_turn is later called with the
    marker's thread_id, so send_turn must alias it to the same base or
    resume_turn can never find it (see agent_client.py's send_turn
    docstring comment)."""
    marker = json.dumps({
        "kind": "approval_pending",
        "payload": {"tool": "restart_service", "args": {}},
        "thread_id": "task-99",
    })

    async def fake_post(self, url, *, json, timeout):
        class _Resp:
            status_code = 200

            def json(self_inner):
                return {
                    "result": {
                        "status": {
                            "state": "input-required",
                            "message": {"parts": [{"text": marker}]},
                        }
                    }
                }

        return _Resp()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    client = A2AAgentClient()
    reply = await client.send_turn("http://hero:8000", text="do it", thread_id="C1:1.0")

    assert reply.pending_approval == {
        "payload": {"tool": "restart_service", "args": {}},
        "thread_id": "task-99",
    }
    # Resuming with the MARKER's thread_id (not the conversation thread_id
    # send_turn was originally called with) must resolve to the same base.
    assert client._known_bases["task-99"] == "http://hero:8000"


async def test_resume_turn_chains_on_second_park(monkeypatch):
    """Stream ends with no terminal event; checkpoint says interrupted again
    -- resume_turn must surface pending_approval rather than raising."""

    def fake_stream(self, method, url, *, json, timeout):
        lines = ['data: {"type":"response.output_text.delta","delta":"partial"}']
        return _FakeStreamResponse(200, lines=lines)

    async def fake_get(self, url, *, params, timeout):
        assert url == "http://hero:8000/v1/_vystak/checkpoint"
        assert params == {"thread_id": "t1"}
        return _FakeGetResponse({"interrupted": True, "interrupts": [PAYLOAD_2]})

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    client = A2AAgentClient()
    client._known_bases["t1"] = "http://hero:8000"

    result = await client.resume_turn("t1", {"approved": True})

    assert result.text == "partial"
    assert result.pending_approval == {"payload": PAYLOAD_2, "thread_id": "t1"}
    assert result.finish_reason == "approval_pending"


async def test_resume_turn_raises_when_truncated_and_not_interrupted(monkeypatch):
    def fake_stream(self, method, url, *, json, timeout):
        return _FakeStreamResponse(200, lines=[])

    async def fake_get(self, url, *, params, timeout):
        return _FakeGetResponse({"interrupted": False, "interrupts": []})

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    client = A2AAgentClient()
    client._known_bases["t1"] = "http://hero:8000"

    with pytest.raises(RuntimeError):
        await client.resume_turn("t1", {"approved": True})


# ---------------------------------------------------------------------------
# NatsAgentClient
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

    async def request(self, subject: str, payload: bytes, timeout: float):
        self.requests.append((subject, payload, timeout))
        if self.raise_on_request is not None:
            raise self.raise_on_request
        return _FakeNatsReply(self.reply_bytes or b"{}")

    async def close(self) -> None:
        self.is_closed = True


def _patch_nats_connect(monkeypatch, fake_client: _FakeNatsClient) -> None:
    import nats

    async def _fake_connect(url, *args, **kwargs):  # noqa: ANN001
        return fake_client

    monkeypatch.setattr(nats, "connect", _fake_connect)


async def test_nats_resume_turn_sends_resume_thread_envelope(monkeypatch):
    fake = _FakeNatsClient()
    fake.reply_bytes = json.dumps({
        "jsonrpc": "2.0",
        "id": "x",
        "result": {"text": "done", "pending_approval": None},
    }).encode()
    _patch_nats_connect(monkeypatch, fake)

    client = NatsAgentClient("nats://localhost:4222")
    client._known_subjects["t1"] = "vystak.default.agents.hero.tasks"

    result = await client.resume_turn(
        "t1", {"approved": True, "decided_by": "@x", "note": None}
    )

    assert isinstance(result, AgentReply)
    assert result.text == "done"
    assert result.pending_approval is None
    assert len(fake.requests) == 1
    subject, payload, _timeout = fake.requests[0]
    assert subject == "vystak.default.agents.hero.tasks"
    body = json.loads(payload)
    assert body["method"] == "responses/resumeThread"
    assert body["params"] == {
        "thread_id": "t1",
        "resume": {"approved": True, "decided_by": "@x", "note": None},
    }


async def test_nats_resume_turn_chains_on_second_park(monkeypatch):
    fake = _FakeNatsClient()
    fake.reply_bytes = json.dumps({
        "jsonrpc": "2.0",
        "id": "x",
        "result": {
            "text": "partial",
            "pending_approval": {"payload": PAYLOAD_2, "thread_id": "t1"},
        },
    }).encode()
    _patch_nats_connect(monkeypatch, fake)

    client = NatsAgentClient("nats://localhost:4222")
    client._known_subjects["t1"] = "vystak.default.agents.hero.tasks"

    result = await client.resume_turn("t1", {"approved": True})

    assert result.text == "partial"
    assert result.pending_approval == {"payload": PAYLOAD_2, "thread_id": "t1"}
    assert result.finish_reason == "approval_pending"


async def test_nats_resume_turn_raises_on_error_reply(monkeypatch):
    fake = _FakeNatsClient()
    fake.reply_bytes = json.dumps({
        "jsonrpc": "2.0",
        "id": "x",
        "error": {"code": -32000, "message": "turn is not parked"},
    }).encode()
    _patch_nats_connect(monkeypatch, fake)

    client = NatsAgentClient("nats://localhost:4222")
    client._known_subjects["t1"] = "vystak.default.agents.hero.tasks"

    with pytest.raises(RuntimeError, match="turn is not parked"):
        await client.resume_turn("t1", {"approved": True})


async def test_nats_resume_turn_raises_without_known_subject():
    client = NatsAgentClient("nats://localhost:4222")
    with pytest.raises(RuntimeError):
        await client.resume_turn("unknown-thread", {"approved": True})
