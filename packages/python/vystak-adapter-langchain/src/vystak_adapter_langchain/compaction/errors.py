"""Error and result types for the compaction module."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SummaryResult:
    """Outcome of a single summarize() call."""

    text: str
    model_id: str
    usage: dict = field(default_factory=dict)


class CompactionError(Exception):
    """Raised by summarize() on any provider failure.

    Threshold layer catches and falls back. Manual endpoint surfaces as 502.
    """

    def __init__(self, reason: str, *, cause: Exception | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.cause = cause
