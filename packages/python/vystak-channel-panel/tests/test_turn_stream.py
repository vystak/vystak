"""Tests for the shared Responses-event translator and turn accumulator."""

from vystak_channel_panel.responses_client import PanelStreamEvent
from vystak_channel_panel.turn_stream import (
    TurnAccumulator,
    browser_frame,
    translate_responses_event,
)


def test_translate_text_delta():
    ev = translate_responses_event(
        {"type": "response.output_text.delta", "delta": "hi"}, {}
    )
    assert ev.type == "token" and ev.text == "hi"


def test_translate_tool_call_correlates_name_and_args():
    pending: dict = {}
    assert translate_responses_event(
        {"type": "response.output_item.added",
         "item": {"type": "function_call", "call_id": "c1", "name": "get_time"}},
        pending,
    ) is None
    assert translate_responses_event(
        {"type": "response.function_call_arguments.delta", "call_id": "c1", "delta": '{"a"'},
        pending,
    ) is None
    ev = translate_responses_event(
        {"type": "response.function_call_arguments.done", "call_id": "c1", "arguments": ""},
        pending,
    )
    assert ev.type == "tool_call"
    assert ev.tool_name == "get_time"
    assert ev.arguments == '{"a"'


def test_translate_tool_result_and_terminals():
    ev = translate_responses_event(
        {"type": "response.output_item.added",
         "item": {"type": "function_call_output", "call_id": "c1",
                  "output": "12:00", "error": False}},
        {},
    )
    assert ev.type == "tool_result" and ev.output == "12:00"
    done = translate_responses_event(
        {"type": "response.completed", "response": {"id": "r9"}}, {}
    )
    assert done.type == "done" and done.response_id == "r9"
    failed = translate_responses_event(
        {"type": "response.failed", "response": {"error": {"message": "boom"}}}, {}
    )
    assert failed.type == "error" and failed.text == "boom"
    assert translate_responses_event({"type": "response.created"}, {}) is None


def test_accumulator_orders_text_and_tools():
    acc = TurnAccumulator()
    acc.feed(PanelStreamEvent(type="token", text="a"))
    acc.feed(PanelStreamEvent(type="tool_call", tool_call_id="c1",
                              tool_name="t", arguments="{}"))
    acc.feed(PanelStreamEvent(type="tool_result", tool_call_id="c1", output="ok"))
    acc.feed(PanelStreamEvent(type="token", text="b"))
    assert acc.content == "ab"
    parts = acc.parts()
    assert [p["type"] for p in parts] == ["text", "tool", "text"]
    assert parts[1]["tool_name"] == "t"
    assert acc.has_output


def test_accumulator_drops_unmatched_tool_call():
    acc = TurnAccumulator()
    acc.feed(PanelStreamEvent(type="tool_call", tool_call_id="c1",
                              tool_name="t", arguments="{}"))
    assert acc.parts() is None
    assert not acc.has_output


def test_browser_frames():
    assert browser_frame(PanelStreamEvent(type="token", text="x")) == {
        "type": "delta", "text": "x"}
    assert browser_frame(PanelStreamEvent(
        type="tool_call", tool_call_id="c", tool_name="n", arguments="{}")) == {
        "type": "tool_call", "tool_call_id": "c", "tool_name": "n", "arguments": "{}"}
    assert browser_frame(PanelStreamEvent(
        type="tool_result", tool_call_id="c", output="o", is_error=True)) == {
        "type": "tool_result", "tool_call_id": "c", "output": "o", "is_error": True}
    assert browser_frame(PanelStreamEvent(type="error", text="bad")) == {
        "type": "error", "message": "bad"}
