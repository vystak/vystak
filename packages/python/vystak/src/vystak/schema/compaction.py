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

    summarizer: Model | None = None

    # NOTE: Layer 2 (LangChain SummarizationMiddleware) is intentionally
    # not exposed as a schema field. Two upstream realities make it
    # incompatible with the current codegen:
    #
    #  1. The autonomous-tool middleware variant from the original design
    #     was removed in langchain 1.1.x.
    #  2. The remaining `SummarizationMiddleware` is threshold-based and
    #     attaches via `langchain.agents.create_agent(..., middleware=[...])`
    #     — but our codegen uses `langgraph.prebuilt.create_react_agent`
    #     with a custom `prompt=` callable (memory recall + Layer 1 prune
    #     + Layer 3 compact). `create_agent` doesn't accept the callable
    #     prompt, so wiring middleware would require converting the entire
    #     prompt-callable chain to middleware too.
    #
    # Layer 3 in our prompt callable provides the same threshold guarantee.
    # If a future user needs the LangChain middleware specifically, the
    # follow-up is to migrate the codegen to `create_agent` with
    # middleware-based prompt assembly.
