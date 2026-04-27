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
