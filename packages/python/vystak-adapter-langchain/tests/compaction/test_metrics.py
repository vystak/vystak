from vystak_adapter_langchain.compaction.metrics import (
    CompactionMetrics,
    record_compaction,
    record_estimate_error,
    record_suppression,
)


def test_metrics_increment_counters():
    m = CompactionMetrics()
    record_compaction(m, layer="layer3", trigger="threshold", outcome="written",
                      input_tokens=100, output_tokens=20, messages_compacted=12)
    assert m.total_count(layer="layer3", trigger="threshold", outcome="written") == 1
    assert m.input_tokens_total(layer="layer3") == 100


def test_suppression_counter():
    m = CompactionMetrics()
    record_suppression(m, layer="layer3", reason="recent")
    record_suppression(m, layer="layer3", reason="recent")
    assert m.suppressions(layer="layer3", reason="recent") == 2


def test_estimate_error_histogram():
    m = CompactionMetrics()
    record_estimate_error(m, provider="anthropic", relative_error=0.05)
    record_estimate_error(m, provider="anthropic", relative_error=0.20)
    samples = m.estimate_error_samples(provider="anthropic")
    assert samples == [0.05, 0.20]
