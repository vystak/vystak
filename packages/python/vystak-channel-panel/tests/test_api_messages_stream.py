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


async def test_empty_text_rejected(api):
    owner, pid, cid = await _ready(api)
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "   "},
        headers=as_user(owner),
    )
    assert resp.status_code == 422
