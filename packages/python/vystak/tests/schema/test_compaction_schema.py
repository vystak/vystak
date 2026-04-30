import pytest
from pydantic import ValidationError
from vystak.schema.compaction import Compaction


def test_default_mode_is_conservative():
    c = Compaction()
    assert c.mode == "conservative"
    assert c.trigger_pct is None
    assert c.summarizer is None


def test_explicit_overrides_round_trip():
    c = Compaction(mode="aggressive", trigger_pct=0.5, keep_recent_pct=0.2)
    assert c.mode == "aggressive"
    assert c.trigger_pct == 0.5
    assert c.keep_recent_pct == 0.2


def test_off_mode_valid():
    c = Compaction(mode="off")
    assert c.mode == "off"


def test_invalid_mode_rejected():
    with pytest.raises(ValidationError):
        Compaction(mode="weird")


def test_trigger_pct_bounds():
    with pytest.raises(ValidationError):
        Compaction(trigger_pct=0.0)
    with pytest.raises(ValidationError):
        Compaction(trigger_pct=1.0)
    with pytest.raises(ValidationError):
        Compaction(trigger_pct=-0.1)
    Compaction(trigger_pct=0.5)  # ok


def test_keep_recent_pct_bounds():
    with pytest.raises(ValidationError):
        Compaction(keep_recent_pct=0.0)
    with pytest.raises(ValidationError):
        Compaction(keep_recent_pct=1.0)
    Compaction(keep_recent_pct=0.5)  # ok


def test_prune_tool_output_bytes_positive():
    with pytest.raises(ValidationError):
        Compaction(prune_tool_output_bytes=0)
    with pytest.raises(ValidationError):
        Compaction(prune_tool_output_bytes=-1)
    Compaction(prune_tool_output_bytes=1024)  # ok


def test_target_tokens_positive():
    with pytest.raises(ValidationError):
        Compaction(target_tokens=0)
    Compaction(target_tokens=10_000)  # ok


def test_use_langchain_middleware_default_off():
    c = Compaction()
    assert c.use_langchain_middleware is False


def test_use_langchain_middleware_round_trip():
    c = Compaction(use_langchain_middleware=True)
    assert c.use_langchain_middleware is True
    rebuilt = Compaction.model_validate(c.model_dump())
    assert rebuilt.use_langchain_middleware is True
