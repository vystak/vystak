"""Approval endpoint (both transports) + PanelNatsClient.resume_detached."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from vystak_channel_panel.nats_client import PanelNatsClient
from vystak_channel_panel.responses_client import PanelStreamEvent

# --- PanelNatsClient.resume_detached ---------------------------------------


class _FakeNc:
    """Fakes the raw nats.py client's `.request` — mirrors how turn_status
    is exercised elsewhere in this package (via turn_worker's fakes), just
    scoped directly at the PanelNatsClient level since there's no existing
    dedicated nats_client test module to mirror."""

    def __init__(self, reply_body: dict | None = None, *, raises: Exception | None = None):
        self._reply_body = reply_body
        self._raises = raises
        self.requests: list[tuple[str, dict, float]] = []

    async def request(self, subject, payload, timeout):
        self.requests.append((subject, json.loads(payload), timeout))
        if self._raises is not None:
            raise self._raises
        return SimpleNamespace(data=json.dumps(self._reply_body).encode())


def _wire_fake_nc(client: PanelNatsClient, fake_nc: _FakeNc, subject: str = "subj") -> None:
    async def fake_connection():
        return fake_nc

    client._transport.nats_connection = fake_connection
    client._transport.resolve_address = lambda name: subject


async def test_resume_detached_success():
    client = PanelNatsClient("nats://fake:4222")
    fake_nc = _FakeNc({"result": {"turn_id": "t1"}})
    _wire_fake_nc(client, fake_nc, subject="vystak.default.agents.durable-agent.tasks")

    resume = {"approved": True, "decided_by": "u@example.com", "note": None}
    result = await client.resume_detached("durable-agent", "t1", resume)
    assert result is None

    subject, payload, _timeout = fake_nc.requests[0]
    assert subject == "vystak.default.agents.durable-agent.tasks"
    assert payload["method"] == "responses/resumeDetached"
    assert payload["params"] == {"turn_id": "t1", "resume": resume}


async def test_resume_detached_raises_on_jsonrpc_error():
    client = PanelNatsClient("nats://fake:4222")
    fake_nc = _FakeNc({"error": {"code": -32602, "message": "turn is not parked"}})
    _wire_fake_nc(client, fake_nc)

    with pytest.raises(RuntimeError, match="turn is not parked"):
        await client.resume_detached(
            "durable-agent", "t1",
            {"approved": False, "decided_by": "u@example.com", "note": "no"},
        )


async def test_resume_detached_wraps_timeout_error():
    """A broker-level timeout is distinct from a JSON-RPC error ("already
    resolved"): the turn's real state is unknown, not conflicting, so it
    must surface as `TimeoutError` (mirroring `turn_status`'s own wrapping)
    rather than being silently swallowed or misrepresented as a
    RuntimeError."""
    client = PanelNatsClient("nats://fake:4222")
    fake_nc = _FakeNc(raises=TimeoutError("no responders"))
    _wire_fake_nc(client, fake_nc, subject="vystak.default.agents.durable-agent.tasks")

    with pytest.raises(TimeoutError, match="responses/resumeDetached"):
        await client.resume_detached(
            "durable-agent", "t1",
            {"approved": True, "decided_by": "u@example.com", "note": None},
        )


# --- POST /api/conversations/{conv_id}/approval — NATS transport -----------


async def test_approval_resumes_parked_turn_nats(panel_app_harness):
    h = await panel_app_harness(transport="nats")
    conv = await h.create_conversation(agent="durable-agent")
    await h.set_active_turn(conv.id, "t1")

    resp = await h.client.post(
        f"/api/conversations/{conv.id}/approval",
        json={"turn_id": "t1", "approved": True, "note": None},
        headers=h.auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert h.nats_client.resume_calls == [
        ("durable-agent", "t1",
         {"approved": True, "decided_by": h.user_email, "note": None}),
    ]


async def test_approval_conflict_when_already_resolved(panel_app_harness):
    h = await panel_app_harness(transport="nats", resume_error="turn is not parked")
    conv = await h.create_conversation(agent="durable-agent")
    await h.set_active_turn(conv.id, "t1")

    resp = await h.client.post(
        f"/api/conversations/{conv.id}/approval",
        json={"turn_id": "t1", "approved": False, "note": "no"},
        headers=h.auth_headers,
    )
    assert resp.status_code == 409
    assert "not parked" in resp.json()["detail"]


async def test_approval_timeout_maps_to_503_nats(panel_app_harness):
    h = await panel_app_harness(transport="nats", resume_timeout=True)
    conv = await h.create_conversation(agent="durable-agent")
    await h.set_active_turn(conv.id, "t1")

    resp = await h.client.post(
        f"/api/conversations/{conv.id}/approval",
        json={"turn_id": "t1", "approved": True, "note": None},
        headers=h.auth_headers,
    )
    assert resp.status_code == 503

    # A timeout is not a resolution — the turn must stay parked so the
    # user can retry the exact same approval POST.
    boot = await h.client.get("/api/bootstrap", headers=h.auth_headers)
    pid = boot.json()["default_project_id"]
    listed = await h.client.get(
        f"/api/projects/{pid}/conversations", headers=h.auth_headers,
    )
    assert listed.json()["conversations"][0]["active_turn_id"] == "t1"


async def test_approval_rejects_mismatched_turn(panel_app_harness):
    h = await panel_app_harness(transport="nats")
    conv = await h.create_conversation(agent="durable-agent")
    await h.set_active_turn(conv.id, "other-turn")

    resp = await h.client.post(
        f"/api/conversations/{conv.id}/approval",
        json={"turn_id": "t1", "approved": True, "note": None},
        headers=h.auth_headers,
    )
    assert resp.status_code == 422


async def test_approval_unknown_conversation_404(panel_app_harness):
    h = await panel_app_harness(transport="nats")
    resp = await h.client.post(
        "/api/conversations/nope/approval",
        json={"turn_id": "t1", "approved": True, "note": None},
        headers=h.auth_headers,
    )
    assert resp.status_code == 404


# --- HTTP-transport park handling in post_message + approval route ---------


def as_user(email: str) -> dict:
    return {"X-Panel-User": email}


def _parse_sse(payload: str) -> list[dict]:
    out = []
    for line in payload.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


class FakeResponsesClientHttp:
    """Fakes ResponsesClient's full HTTP surface: stream_message,
    get_checkpoint, resume_stream — scripted per call via mutable attributes
    so a test can drive one conversation through park -> approval -> resume
    (and every failure mode along the way)."""

    def __init__(self):
        self._stream_events: list[PanelStreamEvent] = []
        self._created_response_id: str | None = None
        self._checkpoint: dict | None = None
        self._resume_events: list[PanelStreamEvent] = []
        self._resume_raises: Exception | None = None
        self.checkpoint_calls: list[tuple[str, str]] = []
        self.resume_calls: list[tuple[str, str, dict]] = []

    async def stream_message(
        self, base_url, text, *, previous_response_id, user_id=None,
        project_id=None, on_response_id=None,
    ):
        if on_response_id is not None and self._created_response_id:
            on_response_id(self._created_response_id)
        for ev in self._stream_events:
            yield ev

    async def get_checkpoint(self, base_url, thread_id):
        self.checkpoint_calls.append((base_url, thread_id))
        return self._checkpoint

    async def resume_stream(self, base_url, thread_id, resume):
        self.resume_calls.append((base_url, thread_id, resume))
        # A real httpx stream suspends at least once before its first byte
        # arrives — without this await, the two-concurrent-POSTs test would
        # pass even if the in-flight guard claimed rt.turn_tasks only AFTER
        # connecting (a real race a synchronous fake can't expose).
        await asyncio.sleep(0)
        if self._resume_raises is not None:
            raise self._resume_raises
        for ev in self._resume_events:
            yield ev


async def _ready(api):
    await api.post(
        "/api/setup",
        json={"email": "o@example.com", "name": "O", "image": ""},
        headers=as_user("o@example.com"),
    )
    boot = await api.get("/api/bootstrap", headers=as_user("o@example.com"))
    pid = boot.json()["default_project_id"]
    cid = (
        await api.post(
            f"/api/projects/{pid}/conversations",
            json={"agent_name": "weather-agent"},
            headers=as_user("o@example.com"),
        )
    ).json()["conversation"]["id"]
    return "o@example.com", pid, cid


APPROVAL_PAYLOAD = {
    "kind": "tool_approval", "tool": "restart_service",
    "args": {"name": "web"}, "skill": "ops",
}


def _capture_tasks(monkeypatch) -> list[asyncio.Task]:
    """Monkeypatches routes_approvals.asyncio.create_task to record every
    background resume task spawned, so a test can `await` it instead of
    racing the background loop."""
    import vystak_channel_panel.routes_approvals as routes_approvals

    tasks: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def capturing_create_task(coro, *a, **kw):
        task = real_create_task(coro, *a, **kw)
        tasks.append(task)
        return task

    monkeypatch.setattr(routes_approvals.asyncio, "create_task", capturing_create_task)
    return tasks


async def test_http_park_emits_approval_frame_and_persists_pending_part(api, panel_rt):
    owner, pid, cid = await _ready(api)
    fake = FakeResponsesClientHttp()
    panel_rt.responses_client = fake

    # First turn: establishes last_response_id so the checkpoint probe below
    # has a thread id to ask about.
    fake._stream_events = [PanelStreamEvent(type="done", response_id="resp_1")]
    await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "restart the web service"},
        headers=as_user(owner),
    )

    # Second turn: the agent parks mid-run — stream ends with no terminal
    # event, and the checkpoint probe reports interrupted.
    fake._stream_events = [PanelStreamEvent(type="token", text="working ")]
    fake._checkpoint = {
        "checkpoint_id": "ckpt_1",
        "interrupted": True,
        "interrupts": [APPROVAL_PAYLOAD],
    }
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "go ahead"},
        headers=as_user(owner),
    )
    assert resp.status_code == 200
    frames = _parse_sse(resp.text)
    assert [f["type"] for f in frames] == ["delta", "approval"]
    approval = frames[-1]
    assert approval["tool_name"] == "restart_service"
    assert approval["input"] == {"name": "web"}
    assert approval["turn_id"] == "resp_1"
    assert fake.checkpoint_calls == [("http://vystak-weather-agent:8000", "resp_1")]

    conv = (
        await api.get(
            f"/api/projects/{pid}/conversations", headers=as_user(owner)
        )
    ).json()["conversations"][0]
    assert conv["active_turn_id"] == "resp_1"

    msgs = (
        await api.get(f"/api/conversations/{cid}/messages", headers=as_user(owner))
    ).json()["messages"]
    pending = msgs[-1]["parts"][-1]
    assert pending["type"] == "tool"
    assert pending["state"] == "approval-requested"
    assert pending["tool_name"] == "restart_service"


async def test_http_first_turn_park_captures_thread_id(api, panel_rt):
    """Important-1 regression: a conversation's very first message parking
    must still surface — there is no `last_response_id` yet, so the probe
    has to fall back to the id captured off `response.created`."""
    owner, pid, cid = await _ready(api)
    fake = FakeResponsesClientHttp()
    panel_rt.responses_client = fake

    fake._created_response_id = "resp_new"
    fake._stream_events = [PanelStreamEvent(type="token", text="working ")]
    fake._checkpoint = {
        "checkpoint_id": "ckpt_1",
        "interrupted": True,
        "interrupts": [APPROVAL_PAYLOAD],
    }

    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "restart the web service"},
        headers=as_user(owner),
    )
    assert resp.status_code == 200
    frames = _parse_sse(resp.text)
    assert [f["type"] for f in frames] == ["delta", "approval"]
    assert frames[-1]["turn_id"] == "resp_new"
    assert fake.checkpoint_calls == [("http://vystak-weather-agent:8000", "resp_new")]

    conv = (
        await api.get(
            f"/api/projects/{pid}/conversations", headers=as_user(owner)
        )
    ).json()["conversations"][0]
    assert conv["active_turn_id"] == "resp_new"
    assert conv["last_response_id"] == "resp_new"

    # The approval route now works off that captured thread id.
    fake._resume_events = [PanelStreamEvent(type="done", response_id="resp_final")]
    approval_resp = await api.post(
        f"/api/conversations/{cid}/approval",
        json={"turn_id": "resp_new", "approved": True, "note": None},
        headers=as_user(owner),
    )
    assert approval_resp.status_code == 200


async def test_http_approval_resumes_persists_continuation_and_resolves_pending_part(
    api, panel_rt, monkeypatch
):
    owner, pid, cid = await _ready(api)
    fake = FakeResponsesClientHttp()
    panel_rt.responses_client = fake

    await panel_rt.panel_store.update_conversation(cid, last_response_id="resp_1")
    await panel_rt.panel_store.set_active_turn(cid, "resp_1")
    pending = await panel_rt.panel_store.add_message(
        cid, "assistant", "",
        parts=[{
            "type": "tool", "state": "approval-requested",
            "tool_call_id": "approval:restart_service",
            "tool_name": "restart_service",
            "input": json.dumps({"name": "web"}),
            "output": "", "is_error": False,
        }],
        turn_id="resp_1",
    )

    tasks = _capture_tasks(monkeypatch)

    fake._resume_events = [
        PanelStreamEvent(type="token", text="restarted."),
        PanelStreamEvent(type="done", response_id="resp_2"),
    ]

    resp = await api.post(
        f"/api/conversations/{cid}/approval",
        json={"turn_id": "resp_1", "approved": True, "note": None},
        headers=as_user(owner),
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    for t in tasks:
        await t

    assert fake.resume_calls == [
        ("http://vystak-weather-agent:8000", "resp_1",
         {"approved": True, "decided_by": owner, "note": None}),
    ]

    msgs = (
        await api.get(f"/api/conversations/{cid}/messages", headers=as_user(owner))
    ).json()["messages"]
    assert msgs[-1]["role"] == "assistant"
    assert msgs[-1]["content"] == "restarted."
    assert msgs[-1]["response_id"] == "resp_2"

    # Minor-4: the parked message's pending part must no longer read as a
    # live approve/reject control.
    resolved = next(m for m in msgs if m["id"] == pending.id)
    assert resolved["parts"][0]["state"] == "resolved"

    conv = (
        await api.get(
            f"/api/projects/{pid}/conversations", headers=as_user(owner)
        )
    ).json()["conversations"][0]
    assert conv["last_response_id"] == "resp_2"
    assert conv["active_turn_id"] is None
    assert "resp_1" not in panel_rt.turn_tasks


async def test_http_approval_unreachable_agent_502_and_stays_parked(api, panel_rt):
    """Critical-1: a resume that can't even connect must surface as a real
    failure response, and must NOT clear active_turn_id — the agent is
    still parked, so the user has to be able to retry the same POST."""
    owner, pid, cid = await _ready(api)
    fake = FakeResponsesClientHttp()
    panel_rt.responses_client = fake

    await panel_rt.panel_store.update_conversation(cid, last_response_id="resp_1")
    await panel_rt.panel_store.set_active_turn(cid, "resp_1")

    fake._resume_raises = RuntimeError("connection refused")

    resp = await api.post(
        f"/api/conversations/{cid}/approval",
        json={"turn_id": "resp_1", "approved": True, "note": None},
        headers=as_user(owner),
    )
    assert resp.status_code == 502

    conv = (
        await api.get(
            f"/api/projects/{pid}/conversations", headers=as_user(owner)
        )
    ).json()["conversations"][0]
    assert conv["active_turn_id"] == "resp_1"
    assert "resp_1" not in panel_rt.turn_tasks

    # No continuation message written for a resume that never started.
    msgs = (
        await api.get(f"/api/conversations/{cid}/messages", headers=as_user(owner))
    ).json()["messages"]
    assert msgs == []


async def test_http_approval_error_event_leaves_turn_parked(api, panel_rt, monkeypatch):
    """A translated `error` event as the FIRST event is a 502 (previous
    test); this covers one arriving mid-stream instead — active_turn_id
    must still be left set so retry works, but partial output is saved."""
    owner, pid, cid = await _ready(api)
    fake = FakeResponsesClientHttp()
    panel_rt.responses_client = fake

    await panel_rt.panel_store.update_conversation(cid, last_response_id="resp_1")
    await panel_rt.panel_store.set_active_turn(cid, "resp_1")

    tasks = _capture_tasks(monkeypatch)
    fake._resume_events = [
        PanelStreamEvent(type="token", text="partial"),
        PanelStreamEvent(type="error", text="agent unreachable: boom"),
    ]

    resp = await api.post(
        f"/api/conversations/{cid}/approval",
        json={"turn_id": "resp_1", "approved": True, "note": None},
        headers=as_user(owner),
    )
    assert resp.status_code == 200
    for t in tasks:
        await t

    conv = (
        await api.get(
            f"/api/projects/{pid}/conversations", headers=as_user(owner)
        )
    ).json()["conversations"][0]
    assert conv["active_turn_id"] == "resp_1"

    msgs = (
        await api.get(f"/api/conversations/{cid}/messages", headers=as_user(owner))
    ).json()["messages"]
    assert msgs[-1]["content"] == "partial"


async def test_http_approval_second_park_persists_pending_and_stays_parked(
    api, panel_rt, monkeypatch
):
    """Critical-1(d): the resumed continuation itself interrupts again on a
    second gated tool — the raw /v1/_vystak/resume SSE just ends with no
    terminal event, same shape as a truncated stream, so this must be
    resolved with the same checkpoint probe as a first-time park, not read
    as either a silent success or a lost failure."""
    owner, pid, cid = await _ready(api)
    fake = FakeResponsesClientHttp()
    panel_rt.responses_client = fake

    await panel_rt.panel_store.update_conversation(cid, last_response_id="resp_1")
    await panel_rt.panel_store.set_active_turn(cid, "resp_1")

    tasks = _capture_tasks(monkeypatch)
    fake._resume_events = [PanelStreamEvent(type="token", text="restarting, now deploying ")]
    fake._checkpoint = {
        "checkpoint_id": "ckpt_2",
        "interrupted": True,
        "interrupts": [
            {"kind": "tool_approval", "tool": "deploy_service",
             "args": {"name": "web"}, "skill": "ops"},
        ],
    }

    resp = await api.post(
        f"/api/conversations/{cid}/approval",
        json={"turn_id": "resp_1", "approved": True, "note": None},
        headers=as_user(owner),
    )
    assert resp.status_code == 200
    for t in tasks:
        await t

    assert fake.checkpoint_calls == [("http://vystak-weather-agent:8000", "resp_1")]

    conv = (
        await api.get(
            f"/api/projects/{pid}/conversations", headers=as_user(owner)
        )
    ).json()["conversations"][0]
    # Still parked — same turn_id, not cleared.
    assert conv["active_turn_id"] == "resp_1"

    msgs = (
        await api.get(f"/api/conversations/{cid}/messages", headers=as_user(owner))
    ).json()["messages"]
    pending = msgs[-1]["parts"][-1]
    assert pending["state"] == "approval-requested"
    assert pending["tool_name"] == "deploy_service"


async def test_http_approval_concurrent_posts_one_wins(api, panel_rt, monkeypatch):
    """Important-2: first-decision-wins. Two concurrent approval POSTs for
    the same turn must not both spawn a resume — one 200s, the other 409s,
    and exactly one continuation gets persisted."""
    owner, pid, cid = await _ready(api)
    fake = FakeResponsesClientHttp()
    panel_rt.responses_client = fake

    await panel_rt.panel_store.update_conversation(cid, last_response_id="resp_1")
    await panel_rt.panel_store.set_active_turn(cid, "resp_1")

    tasks = _capture_tasks(monkeypatch)
    fake._resume_events = [PanelStreamEvent(type="done", response_id="resp_2")]

    async def post():
        return await api.post(
            f"/api/conversations/{cid}/approval",
            json={"turn_id": "resp_1", "approved": True, "note": None},
            headers=as_user(owner),
        )

    r1, r2 = await asyncio.gather(post(), post())
    codes = sorted([r1.status_code, r2.status_code])
    assert codes == [200, 409]

    conflict = r1 if r1.status_code == 409 else r2
    assert "already in progress" in conflict.json()["detail"]

    for t in tasks:
        await t

    assert len(fake.resume_calls) == 1

    msgs = (
        await api.get(f"/api/conversations/{cid}/messages", headers=as_user(owner))
    ).json()["messages"]
    assert len([m for m in msgs if m["role"] == "assistant"]) == 1
