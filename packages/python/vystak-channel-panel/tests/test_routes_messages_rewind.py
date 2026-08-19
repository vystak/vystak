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
