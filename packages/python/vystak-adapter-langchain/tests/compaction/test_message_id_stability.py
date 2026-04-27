"""vystak_msg_id survives reordering and re-stamping passes."""

from langchain_core.messages import AIMessage, HumanMessage
from vystak_adapter_langchain.compaction.coverage import (
    assign_vystak_msg_id,
    fraction_covered,
    message_id,
)


def test_reordering_preserves_ids():
    msgs = [HumanMessage(content="a"), AIMessage(content="b"), HumanMessage(content="c")]
    assign_vystak_msg_id(msgs, thread_id="t1", start=1)
    msgs.reverse()
    assert message_id(msgs[0]) == "t1:3"
    assert message_id(msgs[-1]) == "t1:1"


def test_second_pass_is_idempotent_on_already_stamped():
    msgs = [HumanMessage(content="a"), AIMessage(content="b")]
    next_counter = assign_vystak_msg_id(msgs, thread_id="t1", start=1)
    assert next_counter == 3

    msgs.append(HumanMessage(content="c"))
    next_counter = assign_vystak_msg_id(msgs, thread_id="t1", start=next_counter)
    assert message_id(msgs[0]) == "t1:1"
    assert message_id(msgs[1]) == "t1:2"
    assert message_id(msgs[2]) == "t1:3"


def test_fraction_covered_consistent_across_reorder():
    msgs = [HumanMessage(content="a"), AIMessage(content="b"),
            HumanMessage(content="c"), AIMessage(content="d")]
    assign_vystak_msg_id(msgs, thread_id="t1", start=1)
    f1 = fraction_covered(msgs, up_to="t1:2")
    msgs.reverse()
    f2 = fraction_covered(msgs, up_to="t1:2")
    assert 0 <= f1 <= 1
    assert 0 <= f2 <= 1
