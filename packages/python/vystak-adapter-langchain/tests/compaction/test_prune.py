from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from vystak_adapter_langchain.compaction.prune import prune_messages


def _msgs():
    """Build a synthetic transcript with one oversized old tool output."""
    big = "x" * 10_000
    return [
        HumanMessage(content="hi"),
        AIMessage(content="reading file"),
        ToolMessage(content=big, tool_call_id="t1"),
        AIMessage(content="ok next"),
        HumanMessage(content="more"),
        AIMessage(content="reading again"),
        ToolMessage(content="small", tool_call_id="t2"),
        AIMessage(content="done"),
        HumanMessage(content="final"),
        AIMessage(content="all good"),
    ]


def test_oversized_old_tool_output_is_truncated():
    pruned = prune_messages(_msgs(), max_tool_output_bytes=4096, keep_last_turns=2)
    big_tm = pruned[2]
    assert isinstance(big_tm, ToolMessage)
    assert "...truncated" in big_tm.content
    assert len(big_tm.content) < 6000


def test_recent_turns_preserved_byte_for_byte():
    msgs = _msgs()
    pruned = prune_messages(msgs, max_tool_output_bytes=4096, keep_last_turns=2)
    # Last 4 messages = last 2 user→assistant turns; must be untouched.
    for orig, kept in zip(msgs[-4:], pruned[-4:], strict=True):
        assert orig.content == kept.content


def test_below_threshold_tool_output_untouched():
    msgs = _msgs()
    pruned = prune_messages(msgs, max_tool_output_bytes=4096, keep_last_turns=2)
    small_tm = pruned[6]
    assert small_tm.content == "small"


def test_human_and_ai_text_never_truncated():
    msgs = [HumanMessage(content="x" * 50_000), AIMessage(content="y" * 50_000)]
    pruned = prune_messages(msgs, max_tool_output_bytes=4096, keep_last_turns=2)
    assert pruned[0].content == "x" * 50_000
    assert pruned[1].content == "y" * 50_000


def test_empty_list():
    assert prune_messages([], max_tool_output_bytes=4096, keep_last_turns=2) == []


def test_keep_last_turns_zero_truncates_everything_oversized():
    msgs = [
        AIMessage(content="a"),
        ToolMessage(content="x" * 10_000, tool_call_id="t1"),
    ]
    pruned = prune_messages(msgs, max_tool_output_bytes=100, keep_last_turns=0)
    assert "...truncated" in pruned[1].content
