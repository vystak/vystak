"""Streaming message endpoint — fake ResponsesClient, no network."""

import json

from vystak_channel_panel.responses_client import PanelStreamEvent


def as_user(email: str) -> dict:
    return {"X-Panel-User": email}


class FakeResponsesClient:
    def __init__(self, events, capture=None):
        self._events = events
        self.capture = capture if capture is not None else {}

    async def stream_message(
        self, base_url, text, *, previous_response_id, user_id=None, project_id=None
    ):
        self.capture.update(
            base_url=base_url, text=text,
            previous_response_id=previous_response_id,
            user_id=user_id, project_id=project_id,
        )
        for ev in self._events:
            yield ev


def _parse_sse(payload: str) -> list[dict]:
    out = []
    for line in payload.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


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


async def test_stream_persists_and_replies(api, panel_rt):
    owner, pid, cid = await _ready(api)
    fake = FakeResponsesClient([
        PanelStreamEvent(type="token", text="Hel"),
        PanelStreamEvent(type="token", text="lo"),
        PanelStreamEvent(type="done", response_id="resp_42"),
    ])
    panel_rt.responses_client = fake

    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "What is the weather in Kyiv today?"},
        headers=as_user(owner),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    assert [e["type"] for e in events] == ["delta", "delta", "done"]
    assert events[-1]["response_id"] == "resp_42"
    assert events[-1]["title"] == "What is the weather in Kyiv today?"

    # base_url derived from routes.json with /a2a stripped; ids threaded
    assert fake.capture["base_url"] == "http://vystak-weather-agent:8000"
    assert fake.capture["previous_response_id"] is None
    assert fake.capture["project_id"] == pid
    assert fake.capture["user_id"] == (
        await api.get("/api/bootstrap", headers=as_user(owner))
    ).json()["user"]["id"]

    # persistence: user + assistant rows, last_response_id set
    msgs = (
        await api.get(
            f"/api/conversations/{cid}/messages", headers=as_user(owner)
        )
    ).json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "What is the weather in Kyiv today?"),
        ("assistant", "Hello"),
    ]
    conv = (
        await api.get(
            f"/api/projects/{pid}/conversations", headers=as_user(owner)
        )
    ).json()["conversations"][0]
    assert conv["last_response_id"] == "resp_42"

    # second turn passes previous_response_id
    panel_rt.responses_client = FakeResponsesClient(
        [PanelStreamEvent(type="done", response_id="resp_42")],
        capture=fake.capture,
    )
    await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "and tomorrow?"},
        headers=as_user(owner),
    )
    assert fake.capture["previous_response_id"] == "resp_42"


async def test_agent_error_keeps_user_message(api, panel_rt):
    owner, pid, cid = await _ready(api)
    panel_rt.responses_client = FakeResponsesClient([
        PanelStreamEvent(type="error", text="agent unreachable: boom"),
    ])
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "hello?"},
        headers=as_user(owner),
    )
    events = _parse_sse(resp.text)
    assert events[-1]["type"] == "error"
    msgs = (
        await api.get(
            f"/api/conversations/{cid}/messages", headers=as_user(owner)
        )
    ).json()["messages"]
    assert [(m["role"]) for m in msgs] == ["user"]


async def test_truncated_stream_still_persists_streamed_text(api, panel_rt):
    """Agent stream ends with no terminal event (only `data: [DONE]`).
    The text the user already watched stream must not vanish on reload."""
    owner, pid, cid = await _ready(api)
    panel_rt.responses_client = FakeResponsesClient([
        PanelStreamEvent(type="token", text="par"),
        PanelStreamEvent(type="token", text="tial"),
    ])
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "hello?"},
        headers=as_user(owner),
    )
    assert [e["type"] for e in _parse_sse(resp.text)] == ["delta", "delta", "done"]
    msgs = (
        await api.get(
            f"/api/conversations/{cid}/messages", headers=as_user(owner)
        )
    ).json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "hello?"),
        ("assistant", "partial"),
    ]


async def test_empty_response_id_does_not_clobber_last_response_id(api, panel_rt):
    """A malformed done event with no response id (response_id defaults to
    "") must not overwrite a previously-stored last_response_id with "".

    COALESCE only guards against SQL NULL, not empty string — if the empty
    id were passed straight through, the next turn would send
    previous_response_id="" and the agent would silently start a brand-new
    thread, losing all prior context (see routes_messages.py `done` branch).
    """
    owner, pid, cid = await _ready(api)

    # First turn: agent replies with a good response id.
    panel_rt.responses_client = FakeResponsesClient([
        PanelStreamEvent(type="done", response_id="resp_good"),
    ])
    await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "first"},
        headers=as_user(owner),
    )
    conv = (
        await api.get(
            f"/api/projects/{pid}/conversations", headers=as_user(owner)
        )
    ).json()["conversations"][0]
    assert conv["last_response_id"] == "resp_good"

    # Second turn: agent's terminal event carries no response id.
    panel_rt.responses_client = FakeResponsesClient([
        PanelStreamEvent(type="done"),
    ])
    await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "second"},
        headers=as_user(owner),
    )
    conv = (
        await api.get(
            f"/api/projects/{pid}/conversations", headers=as_user(owner)
        )
    ).json()["conversations"][0]
    assert conv["last_response_id"] == "resp_good"


async def test_empty_text_rejected(api):
    owner, pid, cid = await _ready(api)
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "   "},
        headers=as_user(owner),
    )
    assert resp.status_code == 422


async def test_stream_requires_conversation_access(api, panel_rt):
    owner, pid, cid = await _ready(api)
    # Assert the invite lands: if it silently failed, the 403 below would come
    # from current_user's "not invited" check instead of project access, and
    # this test would stop pinning conversation authorization at all.
    invited = await api.post(
        "/api/users", json={"email": "s@example.com"}, headers=as_user(owner)
    )
    assert invited.status_code == 200

    fake = FakeResponsesClient([PanelStreamEvent(type="done", response_id="resp_x")])
    panel_rt.responses_client = fake

    # stranger (invited to the panel, but not a member of this project)
    # cannot post into the owner's conversation
    deny = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "sneaky"},
        headers=as_user("s@example.com"),
    )
    assert deny.status_code == 403

    # denial short-circuits before the agent is ever called...
    assert fake.capture == {}
    # ...and before the user's message is persisted
    msgs = (
        await api.get(
            f"/api/conversations/{cid}/messages", headers=as_user(owner)
        )
    ).json()["messages"]
    assert msgs == []


async def test_stream_unknown_conversation_404(api):
    owner, pid, cid = await _ready(api)
    resp = await api.post(
        "/api/conversations/nope/messages",
        json={"text": "hi"},
        headers=as_user(owner),
    )
    assert resp.status_code == 404
    # Pins the 404 to require_conversation_access's own check, not FastAPI's
    # default "route not found" 404 (which a missing route would also
    # satisfy) — see test_unknown_conversation_404 in
    # test_api_conversations.py for the precedent.
    assert resp.json()["detail"] == "unknown conversation"
