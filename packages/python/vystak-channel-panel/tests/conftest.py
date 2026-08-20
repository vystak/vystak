"""Shared fixtures for panel channel API tests."""

import json as _json
from types import SimpleNamespace

import httpx
import pytest
from vystak_channel_panel.responses_client import PanelStreamEvent, ResponsesClient
from vystak_channel_panel.store import SqlitePanelStore
from vystak_transport_nats.streams import TurnStreamIdle

SERVICE_TOKEN = "test-service-token"

ROUTES = {
    "weather-agent": {
        "canonical": "weather-agent.agents.default",
        "address": "http://vystak-weather-agent:8000/a2a",
    },
    "time-agent": {
        "canonical": "time-agent.agents.default",
        "address": "http://vystak-time-agent:8000/a2a",
    },
}


@pytest.fixture
async def panel_rt(tmp_path, monkeypatch):
    from vystak_channel_panel.runtime import PanelChannelRuntime
    from vystak_channel_runtime.store import MemoryChannelStore

    monkeypatch.setenv("PANEL_SERVICE_TOKEN", SERVICE_TOKEN)
    panel_store = SqlitePanelStore(tmp_path / "panel.db")
    await panel_store.connect()
    rt = PanelChannelRuntime(
        config={"channel_type": "panel", "port": 8080},
        routes=ROUTES,
        store=MemoryChannelStore(),
        panel_store=panel_store,
        responses_client=ResponsesClient(),
    )
    yield rt
    await panel_store.close()


@pytest.fixture
async def api(panel_rt):
    from vystak_channel_panel.app import build_app

    app = build_app(panel_rt)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://panel",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    ) as client:
        yield client


@pytest.fixture
def persister_harness():
    """Builds a fake `rt` for `run_turn_persister` (Task 10): each attach of
    `nats_client.stream_turn_events` yields one configured batch of events
    then raises `TurnStreamIdle`; `nats_client.turn_status` returns (or
    raises) the configured status; `rt.monotonic()` is driven by an
    injectable clock; `panel_store` records what got persisted/cleared.

    `turn_status` may be a single value/exception (returned/raised on every
    call, the original behavior) or a list — each call consumes the next
    entry, holding on the last one once exhausted — for scripting
    interleavings like "confirmed parked, then a few unreachable polls, then
    running again"."""

    class Harness:
        def __init__(self, *, event_batches, turn_status, clock=None):
            self.reattach_count = 0
            self.persisted_rows: list[dict] = []
            self.cleared_active_turn = False
            self._event_batches = event_batches
            self._turn_status = turn_status
            self._status_calls = 0
            self._clock = list(clock) if clock is not None else None
            self._clock_calls = 0

            harness = self

            class FakeNatsClient:
                async def stream_turn_events(self_nc, subject):
                    idx = harness.reattach_count
                    harness.reattach_count += 1
                    batch = (
                        harness._event_batches[idx]
                        if idx < len(harness._event_batches)
                        else []
                    )
                    for seq, item in enumerate(batch):
                        kind, *rest = item
                        if kind == "done":
                            ev = PanelStreamEvent(
                                type="done", response_id=rest[0] if rest else ""
                            )
                        elif kind == "token":
                            ev = PanelStreamEvent(type="token", text=rest[0] if rest else "")
                        elif kind == "error":
                            ev = PanelStreamEvent(type="error", text=rest[0] if rest else "")
                        else:
                            ev = PanelStreamEvent(type=kind)
                        yield seq, ev
                    raise TurnStreamIdle(subject)

                async def turn_status(self_nc, agent_name, turn_id):
                    ts = harness._turn_status
                    if isinstance(ts, list):
                        idx = min(harness._status_calls, len(ts) - 1)
                        harness._status_calls += 1
                        item = ts[idx]
                    else:
                        item = ts
                    if isinstance(item, BaseException):
                        raise item
                    return item

            class FakePanelStore:
                async def get_conversation(self_ps, conv_id):
                    return SimpleNamespace(id=conv_id, agent_name="echo-agent")

                async def get_message_by_turn_id(self_ps, conv_id, turn_id):
                    return None

                async def add_message(
                    self_ps, conv_id, role, content, *, response_id=None,
                    parts=None, turn_id=None,
                ):
                    harness.persisted_rows.append({
                        "conv_id": conv_id,
                        "role": role,
                        "content": content,
                        "response_id": response_id,
                        "parts": parts,
                        "turn_id": turn_id,
                    })

                async def update_conversation(self_ps, conv_id, *, last_response_id=None):
                    return None

                async def clear_active_turn(self_ps, conv_id, turn_id):
                    harness.cleared_active_turn = True
                    return True

            class FakeRt:
                def __init__(self_rt):
                    self_rt.nats_client = FakeNatsClient()
                    self_rt.panel_store = FakePanelStore()
                    self_rt.routes = {"echo-agent": {"canonical": "echo-agent.agents.default"}}
                    self_rt.turn_tasks = {}

                def monotonic(self_rt):
                    if harness._clock is None:
                        return 0.0
                    idx = min(harness._clock_calls, len(harness._clock) - 1)
                    harness._clock_calls += 1
                    return harness._clock[idx]

            self.rt = FakeRt()

    return Harness


@pytest.fixture
def sse_proxy_harness():
    """Drives `_proxy_turn` (the NATS SSE proxy) directly against a scripted
    batch of raw Responses-API-shaped event dicts — the same shape the real
    agent stream sends over the wire. Each dict is run through
    `translate_responses_event` (mirroring what `PanelNatsClient.stream_turn_events`
    does internally) before being handed to the proxy as `(seq, PanelStreamEvent)`
    pairs, so a scripted `vystak.turn.rewind` event exercises the real
    translate -> accumulate -> replay path end to end. `collect()` parses the
    proxy's `data: ...` SSE lines back into dicts for assertions."""
    from vystak_channel_panel.routes_messages import _proxy_turn
    from vystak_channel_panel.turn_stream import translate_responses_event

    class Harness:
        def __init__(self, *, events):
            self._events = events

        async def collect(self):
            events = self._events

            class FakeNatsClient:
                async def stream_turn_events(self_nc, subject):
                    pending_calls: dict = {}
                    for seq, data in events:
                        ev = translate_responses_event(data, pending_calls)
                        if ev is not None:
                            yield seq, ev

            rt = SimpleNamespace(nats_client=FakeNatsClient())
            frames = []
            async for chunk in _proxy_turn(rt, "subject", "turn-1", "title"):
                for line in chunk.splitlines():
                    if line.startswith("data: "):
                        frames.append(_json.loads(line[6:]))
            return frames

    def make(*, events):
        return Harness(events=events)

    return make


@pytest.fixture
async def panel_app_harness(tmp_path, monkeypatch):
    """Builds a real panel FastAPI app (same `build_app` every route test
    drives) plus a fake `nats_client` for the approval endpoint's NATS
    branch. Unlike `api`/`panel_rt`, this is a factory — each call spins up
    its own store/app/user so tests can pick `transport="nats"` and script
    `resume_detached`'s outcome (`resume_error` -> RuntimeError) per call.

    `h.create_conversation`/`h.set_active_turn` are thin async wrappers over
    the same HTTP setup/store calls `_ready()` and `set_active_turn` do in
    the sibling routes tests, just packaged so `test_approval_endpoint.py`
    doesn't have to repeat them."""
    from types import SimpleNamespace

    from vystak_channel_panel.app import build_app
    from vystak_channel_panel.runtime import PanelChannelRuntime
    from vystak_channel_runtime.store import MemoryChannelStore

    monkeypatch.setenv("PANEL_SERVICE_TOKEN", SERVICE_TOKEN)

    routes = dict(ROUTES)
    routes["durable-agent"] = {
        "canonical": "durable-agent.agents.default",
        "address": "http://vystak-durable-agent:8000/a2a",
    }

    class FakeResumeNatsClient:
        """Mirrors PanelNatsClient.resume_detached's public surface without
        touching JetStream."""

        def __init__(
            self, *, resume_error: str | None = None, resume_timeout: bool = False
        ):
            self.resume_calls: list[tuple[str, str, dict]] = []
            self._resume_error = resume_error
            self._resume_timeout = resume_timeout

        async def resume_detached(self, agent_name: str, turn_id: str, resume: dict) -> None:
            self.resume_calls.append((agent_name, turn_id, resume))
            if self._resume_timeout:
                raise TimeoutError("NATS request timed out")
            if self._resume_error:
                raise RuntimeError(self._resume_error)

    class Harness:
        def __init__(self, *, panel_store, rt, client, user_email: str):
            self.panel_store = panel_store
            self.rt = rt
            self.client = client
            self.user_email = user_email
            self.auth_headers = {"X-Panel-User": user_email}
            self.nats_client = rt.nats_client

        async def create_conversation(self, *, agent: str) -> SimpleNamespace:
            boot = await self.client.get("/api/bootstrap", headers=self.auth_headers)
            pid = boot.json()["default_project_id"]
            resp = await self.client.post(
                f"/api/projects/{pid}/conversations",
                json={"agent_name": agent},
                headers=self.auth_headers,
            )
            return SimpleNamespace(**resp.json()["conversation"])

        async def set_active_turn(self, conv_id: str, turn_id: str) -> None:
            await self.panel_store.set_active_turn(conv_id, turn_id)

        async def aclose(self) -> None:
            await self.client.aclose()
            await self.panel_store.close()

    harnesses: list[Harness] = []

    async def factory(
        *,
        transport: str = "nats",
        resume_error: str | None = None,
        resume_timeout: bool = False,
    ) -> Harness:
        panel_store = SqlitePanelStore(tmp_path / f"panel-{len(harnesses)}.db")
        await panel_store.connect()
        rt = PanelChannelRuntime(
            config={"channel_type": "panel", "port": 8080},
            routes=routes,
            store=MemoryChannelStore(),
            panel_store=panel_store,
            responses_client=ResponsesClient(),
        )
        if transport == "nats":
            rt.nats_client = FakeResumeNatsClient(
                resume_error=resume_error, resume_timeout=resume_timeout
            )
        app = build_app(rt)
        asgi_transport = httpx.ASGITransport(app=app)
        client = httpx.AsyncClient(
            transport=asgi_transport,
            base_url="http://panel",
            headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
        )
        user_email = "o@example.com"
        await client.post(
            "/api/setup",
            json={"email": user_email, "name": "O", "image": ""},
            headers={"X-Panel-User": user_email},
        )
        h = Harness(panel_store=panel_store, rt=rt, client=client, user_email=user_email)
        harnesses.append(h)
        return h

    yield factory

    for h in harnesses:
        await h.aclose()
