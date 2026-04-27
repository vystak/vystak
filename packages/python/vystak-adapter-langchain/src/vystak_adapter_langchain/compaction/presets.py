"""Mode → concrete numeric policy."""

from dataclasses import dataclass

from vystak.schema.compaction import Compaction

_PRESETS = {
    "conservative": {
        "trigger_pct": 0.75,
        "keep_recent_pct": 0.10,
        "prune_tool_output_bytes": 4096,
        "target_tokens_divisor": 2,  # half of context window
    },
    "aggressive": {
        "trigger_pct": 0.60,
        "keep_recent_pct": 0.20,
        "prune_tool_output_bytes": 1024,
        "target_tokens_divisor": 4,
    },
}


@dataclass(frozen=True)
class ResolvedCompaction:
    """Concrete numeric policy fed to the runtime."""

    trigger_pct: float
    keep_recent_pct: float
    prune_tool_output_bytes: int
    target_tokens: int


def resolve_preset(
    compaction: Compaction, *, context_window: int
) -> ResolvedCompaction:
    if compaction.mode == "off":
        raise ValueError("resolve_preset called with mode='off'")
    base = _PRESETS[compaction.mode]
    return ResolvedCompaction(
        trigger_pct=compaction.trigger_pct or base["trigger_pct"],
        keep_recent_pct=compaction.keep_recent_pct or base["keep_recent_pct"],
        prune_tool_output_bytes=(
            compaction.prune_tool_output_bytes or base["prune_tool_output_bytes"]
        ),
        target_tokens=(
            compaction.target_tokens
            or context_window // base["target_tokens_divisor"]
        ),
    )
