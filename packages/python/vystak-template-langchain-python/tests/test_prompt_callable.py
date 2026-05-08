"""build_prompt — system prompt assembly with memory + summary + prune."""

import pytest
from _vystak.runtime.prompt_callable import build_prompt
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage


class _Compaction:
    mode = "conservative"
    prune_tool_output_bytes = 100
    trigger_pct = 0.5
    keep_recent_pct = 0.2
    target_tokens = None
    context_window = 1000


def _agent(instructions="You are helpful.", compaction=None):
    class _A:
        name = "weather"
    a = _A()
    a.instructions = instructions
    a.compaction = compaction
    a.memory = None
    return a


@pytest.mark.asyncio
async def test_prompt_builds_system_message_from_instructions():
    fn = build_prompt(_agent(), memory_mgr=None, compactor=None, pruner=None)
    state = {"messages": [HumanMessage(content="hi")]}
    config = {"configurable": {"thread_id": "t1", "user_id": "u1"}}
    result = await fn(state, config)
    assert isinstance(result[0], SystemMessage)
    assert "You are helpful." in result[0].content


@pytest.mark.asyncio
async def test_prompt_appends_recalled_memories():
    class FakeMemory:
        async def recall(self, *, user_id, query="", project_id="default"):
            return ["[user/m1] User likes pizza"]

    fn = build_prompt(_agent(), memory_mgr=FakeMemory(), compactor=None, pruner=None)
    state = {"messages": [HumanMessage(content="hi")]}
    config = {"configurable": {"thread_id": "t1", "user_id": "u1"}}
    result = await fn(state, config)
    sys_msg = result[0]
    assert "pizza" in sys_msg.content


@pytest.mark.asyncio
async def test_prompt_prunes_oversized_tool_messages():
    from _vystak.runtime.compaction.pruner import PreCallPruner

    big = "x" * 10_000
    msgs = [
        HumanMessage(content="q1"),
        ToolMessage(content=big, tool_call_id="t1"),
        HumanMessage(content="q2"),
        HumanMessage(content="q3"),
        HumanMessage(content="q4"),
    ]
    pruner = PreCallPruner(_Compaction())
    fn = build_prompt(
        _agent(compaction=_Compaction()), memory_mgr=None, compactor=None, pruner=pruner
    )
    state = {"messages": msgs}
    config = {"configurable": {"thread_id": "t1", "user_id": "u1"}}
    result = await fn(state, config)
    tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
    assert len(tool_msgs[0].content) < 200
