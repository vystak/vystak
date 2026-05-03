"""In-process metrics. Exported via the FastAPI /metrics route at server level."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class CompactionMetrics:
    counts: dict[tuple, int] = field(default_factory=lambda: defaultdict(int))
    input_tokens: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    output_tokens: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    messages_compacted: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    suppression_counts: dict[tuple, int] = field(default_factory=lambda: defaultdict(int))
    estimate_errors: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def total_count(self, *, layer: str, trigger: str, outcome: str) -> int:
        return self.counts[(layer, trigger, outcome)]

    def input_tokens_total(self, *, layer: str) -> int:
        return self.input_tokens[layer]

    def suppressions(self, *, layer: str, reason: str) -> int:
        return self.suppression_counts[(layer, reason)]

    def estimate_error_samples(self, *, provider: str) -> list[float]:
        return list(self.estimate_errors[provider])


def record_compaction(
    m: CompactionMetrics,
    *,
    layer: str,
    trigger: str,
    outcome: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    messages_compacted: int = 0,
) -> None:
    m.counts[(layer, trigger, outcome)] += 1
    m.input_tokens[layer] += input_tokens
    m.output_tokens[layer] += output_tokens
    if messages_compacted:
        m.messages_compacted[layer].append(messages_compacted)


def record_suppression(m: CompactionMetrics, *, layer: str, reason: str) -> None:
    m.suppression_counts[(layer, reason)] += 1


def record_estimate_error(
    m: CompactionMetrics, *, provider: str, relative_error: float
) -> None:
    m.estimate_errors[provider].append(relative_error)
