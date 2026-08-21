"""Streaming message endpoint — fake ResponsesClient, no network."""

import json
from pathlib import Path

from vystak_channel_panel.responses_client import PanelStreamEvent

FIXTURE_PATH = (
    Path(__file__).resolve().parents[4]
    / "packages" / "typescript" / "vystak-panel" / "tests" / "fixtures"
    / "panel-sse.txt"
)


def as_user(email: str) -> dict:
    return {"X-Panel-User": email}


class FakeResponsesClient:
    def __init__(self, events, capture=None):
        self._events = events
        self.capture = capture if capture is not None else {}

    async def stream_message(
        self, base_url, text, *, previous_response_id, user_id=None,
        project_id=None, on_response_id=None,
    ):
        self.capture.update(
            base_url=base_url, text=text,
            previous_response_id=previous_response_id,
            user_id=user_id, project_id=project_id,
        )
        for ev in self._events:
            yield ev


class FakeResponsesClientRaisesMidStream:
    def __init__(self, events, exc, capture=None):
        self._events = events
        self._exc = exc
        self.capture = capture if capture is not None else {}

    async def stream_message(
        self, base_url, text, *, previous_response_id, user_id=None,
        project_id=None, on_response_id=None,
    ):
        self.capture.update(
            base_url=base_url, text=text,
            previous_response_id=previous_response_id,
            user_id=user_id, project_id=project_id,
        )
        for ev in self._events:
            yield ev
        raise self._exc


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


async def test_agent_error_after_deltas_persists_partial_text(api, panel_rt):
    """Mid-stream error arriving after some deltas must not discard the text
    the user already watched stream in — the same failure mode the
    truncated-stream branch below it was written to prevent, but reached via
    the error path instead of a silently-ended stream."""
    owner, pid, cid = await _ready(api)
    panel_rt.responses_client = FakeResponsesClient([
        PanelStreamEvent(type="token", text="par"),
        PanelStreamEvent(type="token", text="tial"),
        PanelStreamEvent(type="error", text="agent unreachable: boom"),
    ])
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "hello?"},
        headers=as_user(owner),
    )
    events = _parse_sse(resp.text)
    assert [e["type"] for e in events] == ["delta", "delta", "error"]
    msgs = (
        await api.get(
            f"/api/conversations/{cid}/messages", headers=as_user(owner)
        )
    ).json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "hello?"),
        ("assistant", "partial"),
    ]
    # No response id was confirmed — last_response_id must stay untouched.
    conv = (
        await api.get(
            f"/api/projects/{pid}/conversations", headers=as_user(owner)
        )
    ).json()["conversations"][0]
    assert conv["last_response_id"] is None


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


async def test_dropped_connection_persists_partial_text(api, panel_rt):
    """Agent connection drops mid-stream — an exception escapes
    stream_message rather than an `error` event being yielded. The text
    the user already watched stream in must survive a reload, the same
    failure mode the `error` branch above guards against, but reached via
    the outer exception handler instead."""
    owner, pid, cid = await _ready(api)
    panel_rt.responses_client = FakeResponsesClientRaisesMidStream(
        [
            PanelStreamEvent(type="token", text="par"),
            PanelStreamEvent(type="token", text="tial"),
        ],
        RuntimeError("connection reset"),
    )
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "hello?"},
        headers=as_user(owner),
    )
    events = _parse_sse(resp.text)
    assert [e["type"] for e in events] == ["delta", "delta", "error"]
    msgs = (
        await api.get(
            f"/api/conversations/{cid}/messages", headers=as_user(owner)
        )
    ).json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "hello?"),
        ("assistant", "partial"),
    ]


async def test_tool_call_persists_and_forwards_on_done(api, panel_rt):
    """Done branch: a completed tool call between two bursts of text must be
    forwarded live as typed SSE and persisted as ordered `parts` sitting
    between the two text parts — not merged or reordered — while `content`
    keeps carrying only the flattened text, unaffected by the tool call."""
    owner, pid, cid = await _ready(api)
    panel_rt.responses_client = FakeResponsesClient([
        PanelStreamEvent(type="token", text="Let me check. "),
        PanelStreamEvent(
            type="tool_call", tool_call_id="call_1", tool_name="get_weather",
            arguments='{"city": "Kyiv"}',
        ),
        PanelStreamEvent(
            type="tool_result", tool_call_id="call_1",
            output='{"tempC": 21}', is_error=False,
        ),
        PanelStreamEvent(type="token", text="It's 21C."),
        PanelStreamEvent(type="done", response_id="resp_42"),
    ])
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "weather?"},
        headers=as_user(owner),
    )
    events = _parse_sse(resp.text)
    assert [e["type"] for e in events] == [
        "delta", "tool_call", "tool_result", "delta", "done",
    ]
    assert events[1] == {
        "type": "tool_call", "tool_call_id": "call_1",
        "tool_name": "get_weather", "arguments": '{"city": "Kyiv"}',
    }
    assert events[2] == {
        "type": "tool_result", "tool_call_id": "call_1",
        "output": '{"tempC": 21}', "is_error": False,
    }

    msgs = (
        await api.get(
            f"/api/conversations/{cid}/messages", headers=as_user(owner)
        )
    ).json()["messages"]
    assistant = msgs[-1]
    assert assistant["content"] == "Let me check. It's 21C."
    assert assistant["parts"] == [
        {"type": "text", "text": "Let me check. "},
        {
            "type": "tool", "tool_call_id": "call_1", "tool_name": "get_weather",
            "input": '{"city": "Kyiv"}', "output": '{"tempC": 21}',
            "is_error": False,
        },
        {"type": "text", "text": "It's 21C."},
    ]


async def test_tool_call_persists_on_error_branch(api, panel_rt):
    """Error branch: the same completed tool call must survive a mid-stream
    error alongside the text, not just the text (see the module-level note
    on the `error` branch in routes_messages.py — this is the failure mode
    it was written to prevent, now extended to tool parts)."""
    owner, pid, cid = await _ready(api)
    panel_rt.responses_client = FakeResponsesClient([
        PanelStreamEvent(type="token", text="Checking. "),
        PanelStreamEvent(
            type="tool_call", tool_call_id="call_1", tool_name="get_weather",
            arguments='{"city": "Kyiv"}',
        ),
        PanelStreamEvent(
            type="tool_result", tool_call_id="call_1",
            output='{"tempC": 21}', is_error=False,
        ),
        PanelStreamEvent(type="error", text="agent unreachable: boom"),
    ])
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "weather?"},
        headers=as_user(owner),
    )
    events = _parse_sse(resp.text)
    assert [e["type"] for e in events] == [
        "delta", "tool_call", "tool_result", "error",
    ]
    msgs = (
        await api.get(
            f"/api/conversations/{cid}/messages", headers=as_user(owner)
        )
    ).json()["messages"]
    assistant = msgs[-1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "Checking. "
    assert assistant["parts"] == [
        {"type": "text", "text": "Checking. "},
        {
            "type": "tool", "tool_call_id": "call_1", "tool_name": "get_weather",
            "input": '{"city": "Kyiv"}', "output": '{"tempC": 21}',
            "is_error": False,
        },
    ]


async def test_tool_call_persists_on_truncated_stream(api, panel_rt):
    """Post-loop truncated-stream branch: the agent stream ends with only
    `data: [DONE]` (no response.completed/failed), so ResponsesClient
    yields no terminal event — the completed tool call must still survive,
    not just the text (see the truncated-stream test above)."""
    owner, pid, cid = await _ready(api)
    panel_rt.responses_client = FakeResponsesClient([
        PanelStreamEvent(type="token", text="Checking. "),
        PanelStreamEvent(
            type="tool_call", tool_call_id="call_1", tool_name="get_weather",
            arguments='{"city": "Kyiv"}',
        ),
        PanelStreamEvent(
            type="tool_result", tool_call_id="call_1",
            output='{"tempC": 21}', is_error=False,
        ),
    ])
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "weather?"},
        headers=as_user(owner),
    )
    events = _parse_sse(resp.text)
    assert [e["type"] for e in events] == [
        "delta", "tool_call", "tool_result", "done",
    ]
    msgs = (
        await api.get(
            f"/api/conversations/{cid}/messages", headers=as_user(owner)
        )
    ).json()["messages"]
    assistant = msgs[-1]
    assert assistant["content"] == "Checking. "
    assert assistant["parts"] == [
        {"type": "text", "text": "Checking. "},
        {
            "type": "tool", "tool_call_id": "call_1", "tool_name": "get_weather",
            "input": '{"city": "Kyiv"}', "output": '{"tempC": 21}',
            "is_error": False,
        },
    ]


async def test_tool_call_persists_on_dropped_connection(api, panel_rt):
    """Outer-exception branch: the agent connection drops mid-stream (an
    exception escapes stream_message rather than an `error` event being
    yielded) — the completed tool call must still survive, not just the
    text (see test_dropped_connection_persists_partial_text above)."""
    owner, pid, cid = await _ready(api)
    panel_rt.responses_client = FakeResponsesClientRaisesMidStream(
        [
            PanelStreamEvent(type="token", text="Checking. "),
            PanelStreamEvent(
                type="tool_call", tool_call_id="call_1", tool_name="get_weather",
                arguments='{"city": "Kyiv"}',
            ),
            PanelStreamEvent(
                type="tool_result", tool_call_id="call_1",
                output='{"tempC": 21}', is_error=False,
            ),
        ],
        RuntimeError("connection reset"),
    )
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "weather?"},
        headers=as_user(owner),
    )
    events = _parse_sse(resp.text)
    assert [e["type"] for e in events] == [
        "delta", "tool_call", "tool_result", "error",
    ]
    msgs = (
        await api.get(
            f"/api/conversations/{cid}/messages", headers=as_user(owner)
        )
    ).json()["messages"]
    assistant = msgs[-1]
    assert assistant["content"] == "Checking. "
    assert assistant["parts"] == [
        {"type": "text", "text": "Checking. "},
        {
            "type": "tool", "tool_call_id": "call_1", "tool_name": "get_weather",
            "input": '{"city": "Kyiv"}', "output": '{"tempC": 21}',
            "is_error": False,
        },
    ]


async def test_orphaned_tool_call_is_dropped_from_parts(api, panel_rt):
    """A tool_call with no matching tool_result before the stream ends (the
    agent errors mid-call) is a state Task 5's replay contract has no shape
    for, so it is deliberately dropped from persisted `parts` rather than
    persisted half-finished with invented placeholder output. Pinning this
    so the drop reads as a decision, not a bug found later."""
    owner, pid, cid = await _ready(api)
    panel_rt.responses_client = FakeResponsesClient([
        PanelStreamEvent(type="token", text="Checking. "),
        PanelStreamEvent(
            type="tool_call", tool_call_id="call_1", tool_name="get_weather",
            arguments='{"city": "Kyiv"}',
        ),
        PanelStreamEvent(type="error", text="agent unreachable: boom"),
    ])
    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "weather?"},
        headers=as_user(owner),
    )
    events = _parse_sse(resp.text)
    assert [e["type"] for e in events] == ["delta", "tool_call", "error"]
    msgs = (
        await api.get(
            f"/api/conversations/{cid}/messages", headers=as_user(owner)
        )
    ).json()["messages"]
    assistant = msgs[-1]
    assert assistant["content"] == "Checking. "
    assert assistant["parts"] == [{"type": "text", "text": "Checking. "}]


async def test_panel_sse_matches_cross_language_fixture(api, panel_rt, monkeypatch):
    """Pin the panel's SSE byte format against a fixture shared with the
    TypeScript side (`packages/typescript/vystak-panel/tests/fixtures/
    panel-sse.txt` — Task 4 consumes the same file from stream.test.ts).
    Nothing else pins this cross-language contract: change the Python
    format and no test on either side goes red without this.

    The assistant message id is the only nondeterministic value in the
    stream — add_message() assigns it via store._new_id(). Exactly two
    _new_id() calls happen during this POST (the user message, then the
    assistant message); update_conversation() does not call it. Patching a
    two-value queue after _ready()'s own setup calls makes the id, and so
    the whole byte sequence, reproducible.
    """
    owner, pid, cid = await _ready(api)

    import vystak_channel_panel.store as store_module

    fixed_ids = iter(["fixture-user-msg", "fixture-asst-msg"])
    monkeypatch.setattr(store_module, "_new_id", lambda: next(fixed_ids))

    panel_rt.responses_client = FakeResponsesClient([
        PanelStreamEvent(type="token", text="Let me check "),
        PanelStreamEvent(type="token", text="the weather."),
        PanelStreamEvent(
            type="tool_call", tool_call_id="call_1", tool_name="get_weather",
            arguments='{"city": "Kyiv"}',
        ),
        PanelStreamEvent(
            type="tool_result", tool_call_id="call_1",
            output='{"tempC": 21, "conditions": "clear"}', is_error=False,
        ),
        PanelStreamEvent(type="token", text="It's 21"),
        PanelStreamEvent(type="token", text="°C and clear."),
        PanelStreamEvent(type="done", response_id="resp_fixture_1"),
    ])

    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "What is the weather in Kyiv?"},
        headers=as_user(owner),
    )
    assert resp.text == FIXTURE_PATH.read_text()


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


class FakePanelNatsClient:
    """Mirrors PanelNatsClient's public surface without touching JetStream."""

    idle_timeout_s = 120.0

    def __init__(self):
        self.started: list[dict] = []
        self.events = [
            (0, PanelStreamEvent(type="token", text="hi")),
            (1, PanelStreamEvent(type="done", response_id="resp_1")),
        ]

    @staticmethod
    def turn_subject_for(route_entry, conv_id, turn_id):
        return f"base.streams.{conv_id}.{turn_id}"

    async def start_turn(self, route_entry, text, **kw):
        self.started.append({"text": text, **kw})
        return f"base.streams.{kw['conv_id']}.{kw['turn_id']}"

    async def stream_turn_events(self, subject):
        for seq, ev in self.events:
            yield seq, ev


class FakePanelNatsClientStartTurnFails(FakePanelNatsClient):
    async def start_turn(self, route_entry, text, **kw):
        raise RuntimeError("boom")


async def test_post_message_nats_start_turn_failure_clears_active_turn(api, panel_rt):
    """`start_turn` raising (e.g. agent unreachable) must clear the active
    turn it just set and surface exactly one `error` frame — regression
    guard for a real bug found in review: an `except ... as exc` binding
    whose value was read from a closure invoked after the except block (and
    the function) had already returned, which raises NameError
    instead of reaching the browser at all."""
    owner, pid, cid = await _ready(api)
    panel_rt.nats_client = FakePanelNatsClientStartTurnFails()

    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "hello"},
        headers=as_user(owner),
    )
    assert resp.status_code == 200
    frames = _parse_sse(resp.text)
    assert len(frames) == 1
    assert frames[0]["type"] == "error"
    assert "agent unreachable" in frames[0]["message"]

    conv = (
        await api.get(
            f"/api/projects/{pid}/conversations", headers=as_user(owner)
        )
    ).json()["conversations"][0]
    assert conv["active_turn_id"] is None


async def test_post_message_nats_path_streams_and_marks_active_turn(api, panel_rt):
    owner, pid, cid = await _ready(api)
    panel_rt.nats_client = FakePanelNatsClient()
    panel_rt.turn_tasks = {}
    panel_rt.spawn_persister = lambda *a, **k: None  # persister covered by test_turn_worker

    resp = await api.post(
        f"/api/conversations/{cid}/messages",
        json={"text": "hello"},
        headers=as_user(owner),
    )
    assert resp.status_code == 200
    frames = _parse_sse(resp.text)
    assert frames[0]["type"] == "delta"
    assert frames[0]["text"] == "hi"
    assert frames[0]["seq"] == 0
    assert frames[0]["turn_id"]  # generated uuid hex — non-empty is enough
    assert frames[-1]["type"] == "done"
    assert frames[-1]["response_id"] == "resp_1"
    assert "message_id" not in frames[-1]  # persister owns the row, not this route
    assert panel_rt.nats_client.started[0]["conv_id"] == cid

    # The turn must actually be marked active in the store (not just echoed
    # in the frames) — spawn_persister is stubbed to a no-op above so
    # nothing else would clear it, and this is the same invariant the GET
    # resume endpoint and _resume_active_turns rely on.
    conv = (
        await api.get(
            f"/api/projects/{pid}/conversations", headers=as_user(owner)
        )
    ).json()["conversations"][0]
    assert conv["active_turn_id"] == frames[0]["turn_id"]


async def test_resume_endpoint_204_when_no_active_turn(api, panel_rt):
    owner, pid, cid = await _ready(api)
    panel_rt.nats_client = FakePanelNatsClient()
    resp = await api.get(
        f"/api/conversations/{cid}/stream", headers=as_user(owner)
    )
    assert resp.status_code == 204


async def test_resume_endpoint_replays_active_turn(api, panel_rt):
    owner, pid, cid = await _ready(api)
    panel_rt.nats_client = FakePanelNatsClient()
    # mark the turn active the way the POST path would
    await panel_rt.panel_store.set_active_turn(cid, "turnZ")
    resp = await api.get(
        f"/api/conversations/{cid}/stream", headers=as_user(owner)
    )
    assert resp.status_code == 200
    frames = _parse_sse(resp.text)
    assert frames[0]["type"] == "delta" and frames[0]["turn_id"] == "turnZ"


async def test_resume_endpoint_204_on_http_transport(api, panel_rt):
    owner, pid, cid = await _ready(api)
    panel_rt.nats_client = None
    resp = await api.get(
        f"/api/conversations/{cid}/stream", headers=as_user(owner)
    )
    assert resp.status_code == 204
