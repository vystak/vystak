import pytest
from langchain_core.messages import AIMessage, HumanMessage
from vystak_adapter_langchain.compaction.errors import (
    CompactionError,
    SummaryResult,
)
from vystak_adapter_langchain.compaction.summarize import summarize


class _StubModel:
    model_name = "claude-haiku-4-5-20251001"

    def __init__(self, *, raises: Exception | None = None, text: str = "SUMMARY"):
        self._raises = raises
        self._text = text

    async def ainvoke(self, messages):
        if self._raises:
            raise self._raises
        return AIMessage(
            content=self._text,
            usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        )


@pytest.mark.asyncio
async def test_summarize_returns_summary_result():
    model = _StubModel(text="brief recap")
    result = await summarize(
        model,
        [HumanMessage(content="user said X"), AIMessage(content="agent replied Y")],
    )
    assert isinstance(result, SummaryResult)
    assert result.text == "brief recap"
    assert result.model_id == "claude-haiku-4-5-20251001"
    assert result.usage["input_tokens"] == 100


@pytest.mark.asyncio
async def test_summarize_passes_instructions():
    captured = {}

    class _Capture:
        model_name = "x"

        async def ainvoke(self, messages):
            captured["messages"] = messages
            return AIMessage(
                content="ok",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            )

    await summarize(
        _Capture(),
        [HumanMessage(content="abc")],
        instructions="focus on the user's name",
    )
    rendered = "\n".join(m.content for m in captured["messages"])
    assert "focus on the user's name" in rendered


@pytest.mark.asyncio
async def test_summarize_raises_compaction_error_on_failure():
    model = _StubModel(raises=RuntimeError("rate limited"))
    with pytest.raises(CompactionError) as exc:
        await summarize(model, [HumanMessage(content="abc")])
    assert "rate limited" in exc.value.reason
    assert isinstance(exc.value.cause, RuntimeError)


@pytest.mark.asyncio
async def test_summarize_strips_thinking_blocks_from_anthropic_response():
    """Anthropic responses with extended thinking return a list of blocks
    including `{"type": "thinking", "thinking": "...", "signature": "..."}`.
    The summary text must contain only the `type=="text"` blocks — never
    raw thinking traces.

    Use a plain stub (not langchain's AIMessage) because langchain 1.x
    AIMessage validation rejects free-form dict blocks. Our `_flatten`
    operates on whatever `.content` shape the model returns.
    """

    class _Resp:
        def __init__(self, content, usage):
            self.content = content
            self.usage_metadata = usage

    class _ThinkingModel:
        model_name = "claude-sonnet-test"

        async def ainvoke(self, messages):
            return _Resp(
                content=[
                    {"type": "thinking", "thinking": "internal reasoning", "signature": "abc123"},
                    {"type": "text", "text": "Final summary text."},
                ],
                usage={"input_tokens": 50, "output_tokens": 10},
            )

    result = await summarize(_ThinkingModel(), [HumanMessage(content="x")])
    assert result.text == "Final summary text."
    assert "thinking" not in result.text
    assert "signature" not in result.text
