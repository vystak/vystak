"""A2AAgentClient._reply_from_jsonrpc -- surfaces the approval-pending marker
emitted by LangGraphExecutor when a tool interrupt parks the task."""

import json

from vystak_channel_runtime.agent_client import A2AAgentClient
from vystak_channel_runtime.types import AgentReply

PAYLOAD = {"kind": "tool_approval", "tool": "dangerous", "args": {"x": 1}, "skill": "ops"}
MARKER = json.dumps({"kind": "approval_pending", "payload": PAYLOAD, "thread_id": "task-1"})


def _jsonrpc(state, text):
    return {"result": {"status": {"state": state, "message": {"parts": [{"text": text}]}}}}


def test_input_required_with_marker_sets_pending_approval():
    reply = A2AAgentClient._reply_from_jsonrpc(_jsonrpc("input-required", MARKER))
    assert isinstance(reply, AgentReply)
    assert reply.pending_approval == {"payload": PAYLOAD, "thread_id": "task-1"}
    assert reply.finish_reason == "approval_pending"
    assert reply.text == ""


def test_normal_completion_has_no_pending_approval():
    reply = A2AAgentClient._reply_from_jsonrpc(_jsonrpc("completed", "hi"))
    assert reply.pending_approval is None
    assert reply.text == "hi"


def test_input_required_with_non_marker_text_falls_through_to_plain_reply():
    """input-required with text that isn't the approval marker (e.g. a real
    human-input prompt) must not be swallowed -- it becomes a normal reply."""
    reply = A2AAgentClient._reply_from_jsonrpc(_jsonrpc("input-required", "what's your name?"))
    assert reply.pending_approval is None
    assert reply.text == "what's your name?"
    assert reply.finish_reason == "input-required"
