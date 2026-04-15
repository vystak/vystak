"""Tests for the OpenAI-compatible chat client."""

from agentstack_chat.client import InvokeResult, StreamEvent, StreamResult


class TestDataClasses:
    def test_invoke_result(self):
        r = InvokeResult(response="hi", session_id="s1", input_tokens=5, output_tokens=3, total_tokens=8)
        assert r.response == "hi"
        assert r.total_tokens == 8

    def test_stream_event_token(self):
        e = StreamEvent(type="token", token="hello")
        assert e.type == "token"
        assert e.token == "hello"

    def test_stream_event_tool(self):
        e = StreamEvent(type="tool_call_start", tool="search")
        assert e.tool == "search"

    def test_stream_result(self):
        r = StreamResult(input_tokens=10, output_tokens=20, total_tokens=30)
        assert r.total_tokens == 30
