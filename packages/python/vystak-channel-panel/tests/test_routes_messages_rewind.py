import pytest
from vystak_channel_panel.turn_stream import browser_frame, translate_responses_event


def test_translate_recognizes_rewind():
    ev = translate_responses_event({"type": "vystak.turn.rewind", "to_seq": 4}, {})
    assert ev.type == "rewind"
    assert ev.to_seq == 4


def test_browser_frame_for_rewind_is_reset():
    from vystak_channel_panel.responses_client import PanelStreamEvent
    assert browser_frame(PanelStreamEvent(type="rewind", to_seq=4)) == {"type": "reset"}


@pytest.mark.asyncio
async def test_proxy_emits_reset_then_replays_prefix(sse_proxy_harness):
    h = sse_proxy_harness(events=[
        (0, {"type": "response.output_text.delta", "delta": "keep"}),
        (1, {"type": "response.output_text.delta", "delta": "STALE"}),
        (2, {"type": "vystak.turn.rewind", "to_seq": 0}),
        (3, {"type": "response.output_text.delta", "delta": "-new"}),
    ])
    frames = await h.collect()
    kinds = [f["type"] for f in frames]
    assert "reset" in kinds
    reset_at = kinds.index("reset")
    after = [f for f in frames[reset_at + 1:] if f["type"] == "delta"]
    assert "".join(f["text"] for f in after) == "keep-new"


@pytest.mark.asyncio
async def test_rewind_frames_carry_turn_id_and_seq(sse_proxy_harness):
    """The reset frame and every replayed frame must carry `turn_id`/`seq`,
    same as every other frame on the normal path — the browser has nothing
    else to correlate an SSE frame back to its turn/ordering by."""
    h = sse_proxy_harness(events=[
        (0, {"type": "response.output_text.delta", "delta": "keep"}),
        (1, {"type": "response.output_text.delta", "delta": "STALE"}),
        (2, {"type": "vystak.turn.rewind", "to_seq": 0}),
    ])
    frames = await h.collect()
    reset_at = next(i for i, f in enumerate(frames) if f["type"] == "reset")
    reset_frame = frames[reset_at]
    assert reset_frame["turn_id"] == "turn-1"
    assert reset_frame["seq"] == 2

    replayed = [f for f in frames[reset_at + 1:] if f["type"] == "delta"]
    assert len(replayed) == 1
    assert replayed[0]["turn_id"] == "turn-1"
    assert replayed[0]["seq"] == 0
    assert replayed[0]["text"] == "keep"


@pytest.mark.asyncio
async def test_rewind_straddling_tool_call_replays_pair_with_original_seqs(sse_proxy_harness):
    """Promoted from Task 11's deferred minor by the final-review finding:
    the panel proxy replays a retained tool_call/tool_result pair with its
    ORIGINAL seqs (and tool_call_id) — this is exactly the shape the TS
    adapter fix (lib/stream.ts's reset-generation toolCallId prefixing)
    depends on to render the replayed pair as a fresh post-reset block
    instead of a stale in-place update."""
    h = sse_proxy_harness(events=[
        (0, {"type": "response.output_text.delta", "delta": "before "}),
        (1, {"type": "response.output_item.added",
             "item": {"type": "function_call", "call_id": "c1", "name": "search"}}),
        (2, {"type": "response.function_call_arguments.delta", "call_id": "c1", "delta": "{}"}),
        (3, {"type": "response.function_call_arguments.done", "call_id": "c1", "arguments": ""}),
        (4, {"type": "response.output_item.added",
             "item": {"type": "function_call_output", "call_id": "c1",
                      "output": "hit", "error": False}}),
        (5, {"type": "response.output_text.delta", "delta": "STALE"}),
        (6, {"type": "vystak.turn.rewind", "to_seq": 4}),
        (7, {"type": "response.output_text.delta", "delta": "-after"}),
    ])
    frames = await h.collect()
    kinds = [f["type"] for f in frames]
    assert "reset" in kinds
    reset_at = kinds.index("reset")

    # Retained prefix (seqs 0, 3, 4 survive; the STALE delta at seq 5 does
    # not) replayed in original order, immediately after the reset frame.
    replayed = frames[reset_at + 1:reset_at + 4]
    assert [(f["type"], f["seq"]) for f in replayed] == [
        ("delta", 0), ("tool_call", 3), ("tool_result", 4),
    ]
    assert replayed[1]["tool_call_id"] == "c1"
    assert replayed[1]["tool_name"] == "search"
    assert replayed[2]["tool_call_id"] == "c1"
    assert replayed[2]["output"] == "hit"
    assert replayed[2]["is_error"] is False

    # New content after the rewind follows the replayed prefix.
    after = [f for f in frames[reset_at + 1:] if f["type"] == "delta"]
    assert "".join(f["text"] for f in after) == "before -after"
