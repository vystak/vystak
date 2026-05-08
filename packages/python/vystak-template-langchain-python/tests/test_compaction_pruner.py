"""PreCallPruner — Layer 1 head-and-tail truncate of oversized ToolMessages."""

from _vystak.runtime.compaction.pruner import PreCallPruner
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _make_compaction(threshold_bytes: int = 4096):
    class _C:
        prune_tool_output_bytes = threshold_bytes
    return _C()


def test_prune_leaves_short_tool_outputs_alone():
    msgs = [
        HumanMessage(content="hi"),
        AIMessage(content="ok"),
        ToolMessage(content="short", tool_call_id="t1"),
    ]
    pruned = PreCallPruner(_make_compaction()).prune(msgs)
    assert pruned[-1].content == "short"


def test_prune_truncates_oversized_old_tool_output():
    big = "x" * 10_000
    msgs = [
        HumanMessage(content="q1"),
        AIMessage(content=""),
        ToolMessage(content=big, tool_call_id="t1"),
        HumanMessage(content="q2"),
        AIMessage(content="a2"),
        HumanMessage(content="q3"),
        AIMessage(content="a3"),
        HumanMessage(content="q4"),
        AIMessage(content="a4"),
    ]
    pruner = PreCallPruner(_make_compaction(threshold_bytes=100))
    pruned = pruner.prune(msgs)
    truncated = pruned[2]
    assert isinstance(truncated, ToolMessage)
    assert len(truncated.content) < 200
    assert "..." in truncated.content


def test_prune_preserves_recent_tool_output_even_if_oversized():
    big = "y" * 10_000
    msgs = [
        HumanMessage(content="q1"),
        AIMessage(content=""),
        ToolMessage(content=big, tool_call_id="t1"),
    ]
    pruner = PreCallPruner(_make_compaction(threshold_bytes=100))
    pruned = pruner.prune(msgs)
    assert len(pruned[-1].content) == 10_000


def test_prune_never_touches_human_or_ai_messages():
    big = "z" * 10_000
    msgs = [
        HumanMessage(content=big),
        AIMessage(content=big),
        HumanMessage(content="q2"),
        AIMessage(content="a2"),
        HumanMessage(content="q3"),
        AIMessage(content="a3"),
        HumanMessage(content="q4"),
        AIMessage(content="a4"),
    ]
    pruner = PreCallPruner(_make_compaction(threshold_bytes=100))
    pruned = pruner.prune(msgs)
    assert len(pruned[0].content) == 10_000
    assert len(pruned[1].content) == 10_000
