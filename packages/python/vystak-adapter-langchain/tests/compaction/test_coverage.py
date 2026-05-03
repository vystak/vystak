from langchain_core.messages import AIMessage, HumanMessage
from vystak_adapter_langchain.compaction.coverage import (
    assign_vystak_msg_id,
    fraction_covered,
    message_id,
)


def test_assign_vystak_msg_id_is_monotonic():
    msgs = [HumanMessage(content="a"), AIMessage(content="b"), HumanMessage(content="c")]
    assign_vystak_msg_id(msgs, thread_id="t1", start=1)
    ids = [message_id(m) for m in msgs]
    assert ids == ["t1:1", "t1:2", "t1:3"]


def test_assign_skips_messages_with_existing_id():
    a = HumanMessage(content="a")
    a.additional_kwargs["vystak_msg_id"] = "t1:5"
    b = AIMessage(content="b")
    assign_vystak_msg_id([a, b], thread_id="t1", start=10)
    assert message_id(a) == "t1:5"
    assert message_id(b) == "t1:10"


def test_message_id_falls_back_to_lc_id():
    m = AIMessage(content="x", id="lc-1234")
    assert message_id(m) == "lc-1234"


def test_fraction_covered_counts_messages_at_or_before_id():
    msgs = [HumanMessage(content="a"), AIMessage(content="b"),
            HumanMessage(content="c"), AIMessage(content="d")]
    assign_vystak_msg_id(msgs, thread_id="t1", start=1)
    assert fraction_covered(msgs, up_to="t1:2") == 0.5  # 2 of 4
    assert fraction_covered(msgs, up_to="t1:4") == 1.0
    assert fraction_covered(msgs, up_to="t1:0") == 0.0


def test_fraction_covered_zero_when_id_missing():
    msgs = [HumanMessage(content="a"), AIMessage(content="b")]
    assign_vystak_msg_id(msgs, thread_id="t1", start=1)
    assert fraction_covered(msgs, up_to="t1:99") == 0.0
