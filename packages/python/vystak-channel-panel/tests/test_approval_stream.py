from vystak_channel_panel.responses_client import PanelStreamEvent
from vystak_channel_panel.turn_stream import (
    TurnAccumulator,
    browser_frame,
    translate_responses_event,
)

PAYLOAD = {"kind": "tool_approval", "tool": "restart_service",
           "args": {"name": "web"}, "skill": "ops"}


def test_translate_recognizes_approval_requested():
    ev = translate_responses_event(
        {"type": "vystak.approval.requested", "payload": PAYLOAD}, {})
    assert ev.type == "approval_requested"
    assert ev.approval == PAYLOAD


def test_browser_frame_for_approval():
    ev = PanelStreamEvent(type="approval_requested", approval=PAYLOAD)
    frame = browser_frame(ev)
    assert frame["type"] == "approval"
    assert frame["tool_name"] == "restart_service"
    assert frame["input"] == {"name": "web"}
    assert frame["tool_call_id"]  # stable non-empty id


def test_accumulator_persists_pending_approval_part():
    acc = TurnAccumulator()
    acc.feed_seq(0, PanelStreamEvent(type="token", text="working "))
    acc.feed_seq(1, PanelStreamEvent(type="approval_requested", approval=PAYLOAD))
    parts = acc.parts()
    assert parts[-1] == {
        "type": "tool", "state": "approval-requested",
        "tool_call_id": parts[-1]["tool_call_id"],
        "tool_name": "restart_service",
        "input": '{"name": "web"}',
        "output": "", "is_error": False,
    }


def test_resolved_approval_replaces_pending_part():
    """After resume, the real tool_call/tool_result pair supersedes the
    pending part (same tool name) so the transcript shows one entry."""
    acc = TurnAccumulator()
    acc.feed_seq(0, PanelStreamEvent(type="approval_requested", approval=PAYLOAD))
    acc.feed_seq(1, PanelStreamEvent(type="tool_call", tool_call_id="c1",
                                     tool_name="restart_service",
                                     arguments='{"name": "web"}'))
    acc.feed_seq(2, PanelStreamEvent(type="tool_result", tool_call_id="c1",
                                     output="restarted web", is_error=False))
    tool_parts = [p for p in acc.parts() if p["type"] == "tool"]
    assert len(tool_parts) == 1
    assert tool_parts[0].get("state") != "approval-requested"
