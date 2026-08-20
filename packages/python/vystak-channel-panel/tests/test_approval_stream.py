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


def test_prepark_interrupt_artifact_is_superseded():
    """Full NATS-path sequence: a pre-park tool_call/tool_result pair whose
    result is the raised Interrupt (LangChain's callback layer sees the
    GraphInterrupt as any other tool error before the graph-level park is
    detected), THEN the approval_requested park marker, THEN the resumed
    run's real tool_call/tool_result pair for the same tool. parts() must
    contain exactly one tool part for that tool, and it must be the
    completed one — not the interrupt artifact, not the approval card."""
    acc = TurnAccumulator()
    # Pre-park attempt: tool_call + tool_result carrying the interrupt.
    acc.feed_seq(0, PanelStreamEvent(type="tool_call", tool_call_id="pre",
                                     tool_name="restart_service",
                                     arguments='{"name": "web"}'))
    acc.feed_seq(1, PanelStreamEvent(type="tool_result", tool_call_id="pre",
                                     output="Interrupt(value={...})", is_error=True))
    # Park.
    acc.feed_seq(2, PanelStreamEvent(type="approval_requested", approval=PAYLOAD))
    # Resume: a fresh tool_call/tool_result pair for the same tool.
    acc.feed_seq(3, PanelStreamEvent(type="tool_call", tool_call_id="post",
                                     tool_name="restart_service",
                                     arguments='{"name": "web"}'))
    acc.feed_seq(4, PanelStreamEvent(type="tool_result", tool_call_id="post",
                                     output="restarted web", is_error=False))

    tool_parts = [p for p in acc.parts() if p["type"] == "tool"]
    assert len(tool_parts) == 1
    assert tool_parts[0]["tool_call_id"] == "post"
    assert tool_parts[0]["output"] == "restarted web"
    assert tool_parts[0]["is_error"] is False
    assert tool_parts[0].get("state") != "approval-requested"


def test_prepark_interrupt_artifact_dropped_at_park_even_without_resume():
    """The interrupt artifact is superseded the moment the park is
    recorded, not deferred until a resume shows up — so even if the turn
    never resumes on this stream instance (e.g. a page reload mid-park),
    only the approval-requested card is shown, not a spurious errored
    entry."""
    acc = TurnAccumulator()
    acc.feed_seq(0, PanelStreamEvent(type="tool_call", tool_call_id="pre",
                                     tool_name="restart_service",
                                     arguments='{"name": "web"}'))
    acc.feed_seq(1, PanelStreamEvent(type="tool_result", tool_call_id="pre",
                                     output="Interrupt(value={...})", is_error=True))
    acc.feed_seq(2, PanelStreamEvent(type="approval_requested", approval=PAYLOAD))

    tool_parts = [p for p in acc.parts() if p["type"] == "tool"]
    assert len(tool_parts) == 1
    assert tool_parts[0]["state"] == "approval-requested"


def test_denied_tool_part_survives_a_later_park_of_the_same_tool():
    """A DENIED gated tool produces a legitimate resolved part with
    is_error False (`_denied_result` returns normally, it doesn't raise) —
    that's a real transcript entry, not the pre-park interrupt artifact.
    If the LLM retries the same tool later in the turn and it parks again,
    the earlier denial result must survive, not be silently popped."""
    acc = TurnAccumulator()
    acc.feed_seq(0, PanelStreamEvent(type="tool_call", tool_call_id="c1",
                                     tool_name="restart_service",
                                     arguments='{"name": "web"}'))
    acc.feed_seq(1, PanelStreamEvent(type="tool_result", tool_call_id="c1",
                                     output="Denied by alice: not now",
                                     is_error=False))
    # Retried later in the same turn — parks again.
    acc.feed_seq(2, PanelStreamEvent(type="approval_requested", approval=PAYLOAD))

    tool_parts = [p for p in acc.parts() if p["type"] == "tool"]
    assert len(tool_parts) == 2
    assert tool_parts[0]["tool_call_id"] == "c1"
    assert tool_parts[0]["output"] == "Denied by alice: not now"
    assert tool_parts[0]["is_error"] is False
    assert tool_parts[1]["state"] == "approval-requested"
