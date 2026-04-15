"""Tests for the Responses API chat client."""

from agentstack_chat.client import ResponseResult, StreamEvent, StreamResult


class TestDataClasses:
    def test_response_result(self):
        r = ResponseResult(
            response="hi", response_id="resp-123",
            input_tokens=5, output_tokens=3, total_tokens=8,
        )
        assert r.response == "hi"
        assert r.response_id == "resp-123"

    def test_stream_event_token(self):
        e = StreamEvent(type="token", token="hello")
        assert e.type == "token"

    def test_stream_event_function_call(self):
        e = StreamEvent(type="function_call_start", tool="get_weather")
        assert e.tool == "get_weather"

    def test_stream_event_function_output(self):
        e = StreamEvent(type="function_call_output", result="16C")
        assert e.result == "16C"

    def test_stream_result(self):
        r = StreamResult(input_tokens=10, output_tokens=20, total_tokens=30)
        assert r.total_tokens == 30
