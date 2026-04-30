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

    # Override the model's nominal context window. Useful for testing
    # (set to e.g. 5000 to make compaction fire on tiny conversations) or
    # for models not in the built-in `_CONTEXT_WINDOWS` table. None = use
    # the table's value (defaults to 200_000 for unknown models).
    context_window: int | None = Field(default=None, gt=0)

    # Opt-in defense-in-depth: when True, codegen also wires LangChain 1.1+'s
    # `SummarizationMiddleware` into the agent. It runs after our prompt
    # callable's Layer 3 and provides a second, model-level threshold
    # check. Off by default — our Layer 3 already covers the threshold path
    # and the langchain dep brings packaging fragility (see
    # langgraph/langgraph-prebuilt version skew that this codebase has hit).
    # Originally intended to wire the autonomous-tool middleware (Layer 2),
    # which no longer exists upstream as of langchain 1.1.
    use_langchain_middleware: bool = False

    summarizer: Model | None = None
