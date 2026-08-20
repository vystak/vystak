"""Slack Block Kit approvals -- Task 11 (+ fix-round: streaming path,
restart-survival, broad error handling).

Mirrors `test_runtime.py`'s stubbing (`_FakeSay`, `MemoryChannelStore`,
`_bolt_event`). `resume_turn`/`stream_turn` are stubbed on a fake agent
client rather than constructing a real `A2AAgentClient`/`NatsAgentClient` --
those (including the streaming-approval-marker parsing) are covered by
`vystak-channel-runtime/tests/test_agent_client_resume.py` and
`test_agent_client.py`.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from vystak_channel_runtime.store import MemoryChannelStore
from vystak_channel_runtime.types import AgentChunk, AgentReply
from vystak_channel_slack.runtime import SlackChannelRuntime

PAYLOAD = {
    "kind": "tool_approval",
    "tool": "restart_service",
    "args": {"svc": "web"},
    "skill": "ops",
}
PAYLOAD_2 = {"kind": "tool_approval", "tool": "delete_db", "args": {"table": "x"}, "skill": "ops"}


def _config(**overrides):
    base = {
        "channel_type": "slack",
        "agent_protocol": "a2a-turn",
        "agents": ["hero"],
        "default_agent": "hero",
        "group_policy": "open",
        "dm_policy": "open",
        "allow_from": [],
        "allow_bots": False,
        "channel_overrides": {},
    }
    base.update(overrides)
    return base


def _bolt_event(text="hi <@U_BOT>", channel_type="channel", thread_ts=None, bot_id=None):
    return {
        "type": "message",
        "channel": "C1",
        "user": "U_USER",
        "text": text,
        "ts": "1.0",
        "team": "T1",
        "channel_type": channel_type,
        **({"thread_ts": thread_ts} if thread_ts else {}),
        **({"bot_id": bot_id} if bot_id else {}),
    }


class _FakeSay:
    def __init__(self):
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)


class _FakeAgentClient:
    def __init__(self):
        self.send_turn = AsyncMock()
        self.resume_turn = AsyncMock()

    async def stream_turn(self, *args, **kwargs):
        raise NotImplementedError


def _button(blocks, action_id):
    for block in blocks:
        if block.get("type") != "actions":
            continue
        for el in block.get("elements", []):
            if el.get("action_id") == action_id:
                return el
    return None


def _action_body(action_id: str, value: dict, *, username="alice", user_id="U123"):
    return {
        "actions": [{"action_id": action_id, "value": json.dumps(value)}],
        "user": {"id": user_id, "username": username},
        "channel": {"id": "C1"},
        "message": {"ts": "111.222", "thread_ts": "100.000"},
    }


def _value(**overrides):
    base = {"thread_id": "task-1", "tool": "restart_service", "agent": "hero"}
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_pending_approval_posts_block_kit():
    say = _FakeSay()
    agent_client = _FakeAgentClient()
    agent_client.send_turn.return_value = AgentReply(
        text="",
        finish_reason="approval_pending",
        pending_approval={"payload": PAYLOAD, "thread_id": "task-1"},
    )
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
        agent_client=agent_client,
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "app_mention", "event": _bolt_event(thread_ts="1.0"), "say": say}
    await rt.handle_event(raw)

    assert len(say.calls) == 1
    kwargs = say.calls[0]
    assert "restart_service" in kwargs["text"]
    assert "svc" in kwargs["text"]
    blocks = kwargs["blocks"]
    approve = _button(blocks, "vystak_approve")
    deny = _button(blocks, "vystak_deny")
    assert approve is not None
    assert deny is not None
    assert json.loads(approve["value"]) == _value()
    assert json.loads(deny["value"]) == _value()


@pytest.mark.asyncio
async def test_approve_action_resumes_and_posts_reply():
    agent_client = _FakeAgentClient()
    agent_client.resume_turn.return_value = AgentReply(text="All done.")
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
        agent_client=agent_client,
    )
    client = MagicMock()
    client.chat_update = AsyncMock()
    client.chat_postMessage = AsyncMock()
    client.chat_postEphemeral = AsyncMock()
    body = _action_body("vystak_approve", _value())

    await rt._handle_approval_action(body, client, approved=True)

    agent_client.resume_turn.assert_awaited_once_with(
        "task-1", {"approved": True, "decided_by": "@alice", "note": None}, "http://hero:8000"
    )
    client.chat_update.assert_awaited_once()
    update_kwargs = client.chat_update.call_args.kwargs
    assert update_kwargs["channel"] == "C1"
    assert update_kwargs["ts"] == "111.222"
    assert "Approved by" in update_kwargs["text"]
    assert update_kwargs["blocks"] == []

    client.chat_postMessage.assert_awaited_once()
    post_kwargs = client.chat_postMessage.call_args.kwargs
    assert post_kwargs["channel"] == "C1"
    assert post_kwargs["text"] == "All done."
    assert post_kwargs["thread_ts"] == "100.000"


@pytest.mark.asyncio
async def test_deny_action_sends_denied_decision():
    agent_client = _FakeAgentClient()
    agent_client.resume_turn.return_value = AgentReply(text="Cancelled.")
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
        agent_client=agent_client,
    )
    client = MagicMock()
    client.chat_update = AsyncMock()
    client.chat_postMessage = AsyncMock()
    client.chat_postEphemeral = AsyncMock()
    body = _action_body("vystak_deny", _value())

    await rt._handle_approval_action(body, client, approved=False)

    agent_client.resume_turn.assert_awaited_once_with(
        "task-1", {"approved": False, "decided_by": "@alice", "note": None}, "http://hero:8000"
    )
    update_kwargs = client.chat_update.call_args.kwargs
    assert "Denied by" in update_kwargs["text"]
    post_kwargs = client.chat_postMessage.call_args.kwargs
    assert post_kwargs["text"] == "Cancelled."


@pytest.mark.asyncio
async def test_second_click_reports_already_resolved():
    agent_client = _FakeAgentClient()
    agent_client.resume_turn.side_effect = RuntimeError("turn is not parked")
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
        agent_client=agent_client,
    )
    client = MagicMock()
    client.chat_update = AsyncMock()
    client.chat_postMessage = AsyncMock()
    client.chat_postEphemeral = AsyncMock()
    body = _action_body("vystak_approve", _value())

    await rt._handle_approval_action(body, client, approved=True)

    client.chat_postEphemeral.assert_awaited_once()
    ephemeral_kwargs = client.chat_postEphemeral.call_args.kwargs
    assert ephemeral_kwargs["channel"] == "C1"
    assert ephemeral_kwargs["user"] == "U123"
    assert "already resolved" in ephemeral_kwargs["text"].lower()
    client.chat_update.assert_not_awaited()
    client.chat_postMessage.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_action_chains_on_second_park():
    """resume_turn returns a NEW pending_approval -- post another approval
    message instead of treating text as the final reply."""
    agent_client = _FakeAgentClient()
    agent_client.resume_turn.return_value = AgentReply(
        text="",
        finish_reason="approval_pending",
        pending_approval={"payload": PAYLOAD_2, "thread_id": "task-1"},
    )
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
        agent_client=agent_client,
    )
    client = MagicMock()
    client.chat_update = AsyncMock()
    client.chat_postMessage = AsyncMock()
    client.chat_postEphemeral = AsyncMock()
    body = _action_body("vystak_approve", _value())

    await rt._handle_approval_action(body, client, approved=True)

    client.chat_update.assert_awaited_once()  # first message still resolved
    client.chat_postMessage.assert_awaited_once()
    post_kwargs = client.chat_postMessage.call_args.kwargs
    assert post_kwargs["channel"] == "C1"
    assert post_kwargs["thread_ts"] == "100.000"
    assert "delete_db" in post_kwargs["text"]
    blocks = post_kwargs["blocks"]
    approve = _button(blocks, "vystak_approve")
    assert json.loads(approve["value"]) == {
        "thread_id": "task-1", "tool": "delete_db", "agent": "hero",
    }


# ---------------------------------------------------------------------------
# Important 2 fix-round -- restart survival via the button's "agent" hint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_resolves_agent_url_from_button_value():
    """The button carries the agent route -- resume_turn must be called
    with the resolved agent_url even though nothing populated the client's
    process-local cache (simulating a channel restart)."""
    agent_client = _FakeAgentClient()
    agent_client.resume_turn.return_value = AgentReply(text="Back online.")
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
        agent_client=agent_client,
    )
    client = MagicMock()
    client.chat_update = AsyncMock()
    client.chat_postMessage = AsyncMock()
    client.chat_postEphemeral = AsyncMock()
    body = _action_body("vystak_approve", _value(agent="hero"))

    await rt._handle_approval_action(body, client, approved=True)

    agent_client.resume_turn.assert_awaited_once_with(
        "task-1", {"approved": True, "decided_by": "@alice", "note": None}, "http://hero:8000"
    )
    client.chat_postMessage.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_falls_back_to_none_when_agent_unrouted():
    """An unknown/unrouted agent name in the button value must not crash
    the handler -- agent_url falls back to None (the client's own cache)."""
    agent_client = _FakeAgentClient()
    agent_client.resume_turn.return_value = AgentReply(text="ok")
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
        agent_client=agent_client,
    )
    client = MagicMock()
    client.chat_update = AsyncMock()
    client.chat_postMessage = AsyncMock()
    client.chat_postEphemeral = AsyncMock()
    body = _action_body("vystak_approve", _value(agent="ghost-agent"))

    await rt._handle_approval_action(body, client, approved=True)

    agent_client.resume_turn.assert_awaited_once_with(
        "task-1", {"approved": True, "decided_by": "@alice", "note": None}, None
    )


# ---------------------------------------------------------------------------
# Important 3 fix-round -- broad exception handling, never a dead button
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unexpected_exception_from_resume_turn_posts_ephemeral():
    agent_client = _FakeAgentClient()
    agent_client.resume_turn.side_effect = ValueError("boom")
    rt = SlackChannelRuntime(
        config=_config(),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
        agent_client=agent_client,
    )
    client = MagicMock()
    client.chat_update = AsyncMock()
    client.chat_postMessage = AsyncMock()
    client.chat_postEphemeral = AsyncMock()
    body = _action_body("vystak_approve", _value())

    await rt._handle_approval_action(body, client, approved=True)

    client.chat_postEphemeral.assert_awaited_once()
    ephemeral_kwargs = client.chat_postEphemeral.call_args.kwargs
    assert ephemeral_kwargs["channel"] == "C1"
    assert "could not be delivered" in ephemeral_kwargs["text"].lower()
    client.chat_update.assert_not_awaited()
    client.chat_postMessage.assert_not_awaited()


# ---------------------------------------------------------------------------
# Critical 1 fix-round -- streaming path (Slack's DEFAULT agent_protocol)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_approval_via_streaming_posts_block_kit_not_raw_json():
    """Slack defaults to agent_protocol=a2a-stream. An approval_pending
    chunk must reach post_reply as reply.pending_approval, and the raw
    marker JSON must never be posted as reply text."""
    say = _FakeSay()
    agent_client = _FakeAgentClient()

    async def fake_stream_turn(*args, **kwargs):
        yield AgentChunk(
            type="approval_pending",
            delta="",
            data={"payload": PAYLOAD, "thread_id": "task-1"},
            finish_reason="approval_pending",
            final=True,
        )

    agent_client.stream_turn = fake_stream_turn
    rt = SlackChannelRuntime(
        config=_config(agent_protocol="a2a-stream"),
        routes={"hero": {"address": "http://hero:8000"}},
        store=MemoryChannelStore(),
        agent_client=agent_client,
    )
    rt._bot_user_id = "U_BOT"
    raw = {"type": "app_mention", "event": _bolt_event(thread_ts="1.0"), "say": say}
    await rt.handle_event(raw)

    assert len(say.calls) == 1
    kwargs = say.calls[0]
    assert "blocks" in kwargs
    assert "restart_service" in kwargs["text"]
    # The raw marker JSON must never be the posted text.
    assert "approval_pending" not in kwargs["text"]
    assert '"kind"' not in kwargs["text"]
