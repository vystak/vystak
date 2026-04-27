"""Session compaction runtime — public surface."""

from vystak_adapter_langchain.compaction.coverage import (
    assign_vystak_msg_id,
    fraction_covered,
    message_id,
)
from vystak_adapter_langchain.compaction.errors import (
    CompactionError,
    SummaryResult,
)
from vystak_adapter_langchain.compaction.presets import (
    ResolvedCompaction,
    resolve_preset,
)
from vystak_adapter_langchain.compaction.prune import prune_messages
from vystak_adapter_langchain.compaction.store import (
    CompactionRow,
    CompactionStore,
    InMemoryCompactionStore,
    PostgresCompactionStore,
    SqliteCompactionStore,
)
from vystak_adapter_langchain.compaction.summarize import summarize
from vystak_adapter_langchain.compaction.threshold import maybe_compact
from vystak_adapter_langchain.compaction.tokens import (
    EstimateResult,
    estimate_tokens,
)

__all__ = [
    "CompactionError",
    "CompactionRow",
    "CompactionStore",
    "EstimateResult",
    "InMemoryCompactionStore",
    "PostgresCompactionStore",
    "ResolvedCompaction",
    "SqliteCompactionStore",
    "SummaryResult",
    "assign_vystak_msg_id",
    "estimate_tokens",
    "fraction_covered",
    "maybe_compact",
    "message_id",
    "prune_messages",
    "resolve_preset",
    "summarize",
]
