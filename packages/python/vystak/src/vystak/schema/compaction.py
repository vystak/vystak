"""Session compaction policy."""

from typing import Literal

from pydantic import Field

from vystak.schema.common import NamedModel
from vystak.schema.model import Model

CompactionMode = Literal["off", "conservative", "aggressive"]


class Compaction(NamedModel):
    """Session compaction policy.

    See `docs/superpowers/specs/2026-04-25-session-compaction-design.md`.
    `mode` is the shorthand; explicit numeric fields override the preset.
    `summarizer=None` falls back to `agent.model` at codegen time.
    """

    name: str = ""
    mode: CompactionMode = "conservative"

    trigger_pct: float | None = Field(default=None, gt=0.0, lt=1.0)
    keep_recent_pct: float | None = Field(default=None, gt=0.0, lt=1.0)
    prune_tool_output_bytes: int | None = Field(default=None, gt=0)
    target_tokens: int | None = Field(default=None, gt=0)

    summarizer: Model | None = None
