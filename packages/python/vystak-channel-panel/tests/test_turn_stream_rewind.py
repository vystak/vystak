from vystak_channel_panel.responses_client import PanelStreamEvent
from vystak_channel_panel.turn_stream import TurnAccumulator


def _tok(text):
    return PanelStreamEvent(type="token", text=text)


def test_rewind_drops_events_above_to_seq():
    acc = TurnAccumulator()
    for seq, text in enumerate(["a", "b", "c", "d"]):
        acc.feed_seq(seq, _tok(text))
    acc.rewind(1)
    assert acc.content == "ab"


def test_rewind_is_inclusive_of_to_seq():
    acc = TurnAccumulator()
    acc.feed_seq(0, _tok("keep"))
    acc.rewind(0)
    assert acc.content == "keep"


def test_rewind_to_negative_clears_everything():
    acc = TurnAccumulator()
    acc.feed_seq(0, _tok("gone"))
    acc.rewind(-1)
    assert acc.content == ""
    assert acc.has_output is False


def test_feeding_after_rewind_continues_cleanly():
    acc = TurnAccumulator()
    acc.feed_seq(0, _tok("a"))
    acc.feed_seq(1, _tok("STALE"))
    acc.rewind(0)
    acc.feed_seq(1, _tok("b"))
    assert acc.content == "ab"


def test_rewind_refolds_tool_parts():
    acc = TurnAccumulator()
    acc.feed_seq(0, _tok("before "))
    acc.feed_seq(1, PanelStreamEvent(type="tool_call", tool_call_id="c1",
                                     tool_name="search", arguments="{}"))
    acc.feed_seq(2, PanelStreamEvent(type="tool_result", tool_call_id="c1",
                                     output="hit", is_error=False))
    acc.feed_seq(3, _tok("STALE"))
    acc.rewind(2)
    parts = acc.parts()
    assert [p["type"] for p in parts] == ["text", "tool"]
    assert acc.content == "before "


def test_retained_returns_surviving_pairs():
    acc = TurnAccumulator()
    acc.feed_seq(0, _tok("a"))
    acc.feed_seq(1, _tok("b"))
    acc.rewind(0)
    assert [s for s, _ in acc.retained()] == [0]
