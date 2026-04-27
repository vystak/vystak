import pytest
from vystak.schema.compaction import Compaction
from vystak_adapter_langchain.compaction.presets import resolve_preset


def test_conservative_preset():
    r = resolve_preset(Compaction(mode="conservative"), context_window=200_000)
    assert r.trigger_pct == 0.75
    assert r.keep_recent_pct == 0.10
    assert r.prune_tool_output_bytes == 4096
    assert r.target_tokens == 100_000  # half of 200_000


def test_aggressive_preset():
    r = resolve_preset(Compaction(mode="aggressive"), context_window=200_000)
    assert r.trigger_pct == 0.60
    assert r.keep_recent_pct == 0.20
    assert r.prune_tool_output_bytes == 1024
    assert r.target_tokens == 50_000  # quarter of 200_000


def test_off_raises():
    with pytest.raises(ValueError, match="off"):
        resolve_preset(Compaction(mode="off"), context_window=200_000)


def test_explicit_overrides_win():
    r = resolve_preset(
        Compaction(mode="conservative", trigger_pct=0.5, target_tokens=12_345),
        context_window=200_000,
    )
    assert r.trigger_pct == 0.5  # overridden
    assert r.target_tokens == 12_345
    assert r.keep_recent_pct == 0.10  # preset default still applies
