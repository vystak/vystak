"""Tests for vystak_channel_runtime.types."""

import pytest
from vystak.schema.common import ChannelType
from vystak_channel_runtime.types import (
    AgentCallError,
    AgentChunk,
    AgentReply,
    InboundEvent,
    Message,
    SkipEvent,
    ThreadBinding,
)


def test_inbound_event_round_trip():
    ev = InboundEvent(
        channel_type=ChannelType.SLACK,
        scope_id="T1",
        thread_id="C1:123.45",
        user_id="U1",
        text="hi",
        is_dm=False,
        mentions_bot=True,
        metadata={"channel_name": "general"},
        raw=None,
    )
    dumped = ev.model_dump()
    re = InboundEvent(**dumped)
    assert re.channel_type == ChannelType.SLACK
    assert re.scope_id == "T1"
    assert re.metadata == {"channel_name": "general"}


def test_agent_reply_minimum():
    r = AgentReply(text="hello")
    assert r.text == "hello"
    assert r.tool_calls == []
    assert r.finish_reason is None


def test_agent_chunk_minimum():
    c = AgentChunk(delta="hi")
    assert c.delta == "hi"


def test_message_shape():
    m = Message(role="user", content="hi")
    assert m.role == "user"
    assert m.content == "hi"


def test_thread_binding_shape():
    b = ThreadBinding(
        channel_type="slack",
        scope_id="T1",
        thread_id="C1:123.45",
        agent_name="hero",
    )
    assert b.agent_name == "hero"
    assert b.user_id is None


def test_skip_event_is_exception():
    with pytest.raises(SkipEvent):
        raise SkipEvent("ignored")


def test_agent_call_error_is_exception():
    with pytest.raises(AgentCallError):
        raise AgentCallError("agent down")
