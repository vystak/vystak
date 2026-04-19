"""Tests for transport A2A envelope types."""

import pytest
from pydantic import ValidationError
from vystak.transport import (
    A2AEvent,
    A2AMessage,
    A2AResult,
    AgentRef,
)


class TestAgentRef:
    def test_minimal(self):
        ref = AgentRef(canonical_name="time-agent.agents.prod")
        assert ref.canonical_name == "time-agent.agents.prod"

    def test_invalid_canonical_rejected(self):
        with pytest.raises(ValidationError):
            AgentRef(canonical_name="not-canonical")


class TestA2AMessage:
    def test_text_only(self):
        m = A2AMessage.from_text("hello")
        assert m.role == "user"
        assert m.parts == [{"text": "hello"}]

    def test_with_metadata(self):
        m = A2AMessage.from_text("hi", correlation_id="c-1")
        assert m.correlation_id == "c-1"

    def test_correlation_defaults_to_uuid(self):
        m = A2AMessage.from_text("hi")
        assert m.correlation_id is not None
        assert len(m.correlation_id) > 0


class TestA2AEvent:
    def test_token(self):
        e = A2AEvent(type="token", text="hello")
        assert e.type == "token"
        assert e.text == "hello"
        assert e.final is False

    def test_final(self):
        e = A2AEvent(type="final", text="done", final=True)
        assert e.final is True


class TestA2AResult:
    def test_basic(self):
        r = A2AResult(text="reply", correlation_id="c-1")
        assert r.text == "reply"
        assert r.correlation_id == "c-1"
