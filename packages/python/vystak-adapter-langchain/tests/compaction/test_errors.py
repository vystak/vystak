from vystak_adapter_langchain.compaction.errors import (
    CompactionError,
    SummaryResult,
)


def test_summary_result_fields():
    s = SummaryResult(
        text="summary…",
        model_id="claude-haiku-4-5-20251001",
        usage={"input_tokens": 1234, "output_tokens": 56},
    )
    assert s.text == "summary…"
    assert s.model_id == "claude-haiku-4-5-20251001"
    assert s.usage["input_tokens"] == 1234


def test_compaction_error_carries_reason():
    err = CompactionError("rate limited")
    assert str(err) == "rate limited"
    assert err.reason == "rate limited"


def test_compaction_error_chainable():
    inner = RuntimeError("upstream")
    err = CompactionError("rate limited", cause=inner)
    assert err.cause is inner
