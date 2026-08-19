"""Pytest configuration for vystak-template-langchain-python tests."""

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest


@pytest.fixture
def tmp_agent_dir(tmp_path):
    """Provides a tmp directory with a minimal vystak.yaml."""
    (tmp_path / "vystak.yaml").write_text(
        "name: test-agent\n"
        "framework: langchain-python\n"
        "default_model:\n"
        "  provider:\n"
        "    type: anthropic\n"
        "  model_name: claude-sonnet-4-6\n"
    )
    return tmp_path


@pytest.fixture
def fake_agent():
    """Lightweight stand-in for the Agent schema with only the attrs handlers read.

    Handlers reference `agent.name` for default model strings; future phases will
    add `agent.default_model`, `agent.skills`, etc. Tests can extend by writing to the
    returned namespace.
    """
    return SimpleNamespace(name="weather")


class _JournalTestFakeNatsClient:
    """Fake NATS connection for bridge_factory: records raw publishes (used
    for JSON-RPC acks/errors) and exposes a stub JetStream context."""

    def __init__(self, jetstream: Any) -> None:
        self.published: list[tuple[str, bytes]] = []
        self._jetstream = jetstream

    async def publish(self, subject, payload):  # noqa: ANN001
        self.published.append((subject, payload))

    def jetstream(self):
        return self._jetstream

    async def close(self) -> None:
        return None


class _JournalTestStubJetStream:
    """Stub JetStream context for bridge_factory: no-op stream management,
    records every published raw payload for assertions."""

    def __init__(self) -> None:
        self.published_payloads: list[bytes] = []

    async def add_stream(self, cfg):  # noqa: ANN001
        return None

    async def update_stream(self, cfg):  # noqa: ANN001
        return None

    async def publish(self, subject, payload):  # noqa: ANN001
        self.published_payloads.append(payload)


@pytest.fixture
def bridge_factory(monkeypatch):
    """Builds a NatsHttpBridge wired to a stub NATS connection (records
    published_payloads via a stub JetStream context) and a stub HTTP client
    that replays a caller-supplied list of Responses SSE events.

    ``_ensure_turn_stream`` is monkeypatched to a no-op — the test turn
    subjects (e.g. "s.t1") aren't real ``{base}.streams.{conv}.{turn}``
    subjects, and stream provisioning isn't what this fixture is testing.
    """
    from _vystak.runtime import nats_bridge as nats_bridge_module
    from _vystak.runtime.nats_bridge import NatsHttpBridge

    async def _noop_ensure_turn_stream(js, base):  # noqa: ANN001
        return None

    def _noop_stream_base_of_turn_subject(stream_subject):  # noqa: ANN001
        return stream_subject

    monkeypatch.setattr(nats_bridge_module, "_ensure_turn_stream", _noop_ensure_turn_stream)
    monkeypatch.setattr(
        nats_bridge_module, "_stream_base_of_turn_subject", _noop_stream_base_of_turn_subject
    )

    def _make(
        *,
        journal=None,
        sse_events=None,
        resume_checkpoint_id=None,
        healthz_failures: int = 0,
    ):
        events = sse_events or []
        lines = [f"data: {json.dumps(e)}\n\n" for e in events]
        lines.append("data: [DONE]\n\n")
        sse_bytes = "".join(lines).encode()

        requests: list[dict[str, Any]] = []
        healthz_calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            body: Any = None
            if request.content:
                try:
                    body = json.loads(request.content)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    body = None
            requests.append(
                {"method": request.method, "path": request.url.path, "json": body}
            )
            if request.url.path == "/healthz":
                healthz_calls["n"] += 1
                if healthz_calls["n"] <= healthz_failures:
                    return httpx.Response(503)
                return httpx.Response(200)
            if request.url.path == "/v1/_vystak/checkpoint":
                return httpx.Response(200, json={"checkpoint_id": resume_checkpoint_id})
            return httpx.Response(
                200, content=sse_bytes, headers={"content-type": "text/event-stream"}
            )

        bridge = NatsHttpBridge(
            nats_url="nats://ignored:4222",
            subject="vystak.default.agents.hero.tasks",
            queue_group="agents.hero",
            local_url="http://localhost:8000/a2a",
            local_base="http://localhost:8000",
            journal=journal,
        )
        js = _JournalTestStubJetStream()
        bridge._nc = _JournalTestFakeNatsClient(js)
        bridge._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        bridge.published_payloads = js.published_payloads
        bridge.requests = requests
        return bridge

    return _make
