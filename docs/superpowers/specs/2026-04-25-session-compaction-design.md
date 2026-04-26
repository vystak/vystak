# Session compaction — design

**Date:** 2026-04-25
**Status:** Design approved; pending implementation plan.

## Problem

Long-running sessions on a deployed vystak agent grow without bound. The full
LangGraph checkpoint is replayed into the prompt on every turn, which causes
three failure modes:

1. **Context overflow** — the prompt eventually exceeds the model's context
   window and the call fails.
2. **Cost & latency** — every turn re-pays prefill tokens for the entire
   transcript.
3. **Quality** — accumulated tool outputs (file dumps, search results, exec
   logs) bury recent intent and the agent loses focus.

Vystak today has no mitigation. Sessions either work in-memory (`MemorySaver`,
no persistence at all) or persist to Postgres / SQLite via LangGraph's
`AsyncPostgresSaver` / `AsyncSqliteSaver`, with the full message list replayed
each turn.

## Goals

- Three-layer defense:
  1. cheap, always-on **pruning** of bloated tool outputs (OpenClaw-style)
  2. **autonomous summarization** the agent can trigger via tool middleware
     (LangChain-style)
  3. **threshold-based pre-call summarization** as a backstop when the model
     is about to overflow
- A **manual `/compact`** escape hatch reachable from the chat REPL.
- **Non-destructive** — original transcripts in the LangGraph checkpoint stay
  untouched; compaction state lives in a separate table.
- **Observable** — failed compaction never silently degrades quality without a
  user-visible signal.

## Non-goals

- Cross-session compaction, summarization that survives `/new`.
- A non-LLM extractive summarizer (deferred — single concrete summarizer model).
- Reconstructing the full transcript on the client side. The disk transcript
  exists; surfacing it is a future feature.
- Live-LLM end-to-end test on first ship (deferred to a future cell if mocked
  summarization drifts).

## Architecture overview

```
                  ┌────────────────────────────────────────────────┐
                  │  Generated agent server (FastAPI + LangGraph)  │
                  │                                                │
   incoming turn  │   prompt callable (_make_prompt):              │
   ───────────────┼───►   1. recall memories                       │
                  │       2. assemble messages from checkpoint     │
                  │       3. PRUNE  ◄─ Layer 1 (always)            │
                  │       4. THRESHOLD COMPACT ◄─ Layer 2 (gated)  │
                  │       5. send to LLM                           │
                  │                                                │
                  │   create_react_agent middlewares:              │
                  │       AUTONOMOUS COMPACT ◄─ Layer 3 (tool)     │
                  │                                                │
                  │   POST /v1/sessions/{thread_id}/compact:       │
                  │       MANUAL COMPACT ◄─ admin/CLI escape       │
                  │                                                │
                  │   ┌────────────────────────────────────────┐   │
                  │   │  vystak_compactions table              │   │
                  │   │  (postgres / sqlite / in-memory dict)  │◄──┼── all 3 layers
                  │   └────────────────────────────────────────┘   │   write here;
                  │                                                │   prompt callable
                  │                                                │   reads `latest`
                  └────────────────────────────────────────────────┘
```

All three summarization layers converge on `write_compaction()`. The prompt
callable consults `latest_compaction(thread_id)` on every turn and assembles
`[summary_message] + messages_after_up_to_id` when one exists. The LangGraph
checkpoint is never rewritten.

## Schema

A new optional `Compaction` model attached to `Agent`. Stored in
`packages/python/vystak/src/vystak/schema/compaction.py`:

```python
from typing import Literal
from vystak.schema.common import NamedModel
from vystak.schema.model import Model


CompactionMode = Literal["off", "conservative", "aggressive"]


class Compaction(NamedModel):
    """Session compaction policy."""

    mode: CompactionMode = "conservative"

    # Optional numeric overrides; None = inherit from mode preset.
    trigger_pct: float | None = None
    keep_recent_pct: float | None = None
    prune_tool_output_bytes: int | None = None
    target_tokens: int | None = None

    # Falls back to agent.model when None.
    summarizer: Model | None = None
```

`Agent` adds `compaction: Compaction | None = None`.

**Mode presets** (resolved at codegen time):

| field | conservative (default) | aggressive |
|---|---|---|
| `trigger_pct` | 0.75 | 0.60 |
| `keep_recent_pct` | 0.10 | 0.20 |
| `prune_tool_output_bytes` | 4096 | 1024 |
| `target_tokens` | half of context window | quarter |

**Why 0.75 conservative.** Two competing pressures:

1. *Cache.* Anthropic's prompt cache TTL is 5 minutes; compaction
   invalidates the cache prefix on the next turn. Higher thresholds
   preserve the cache more often.
2. *Quality.* Chroma's "context rot" research
   (https://www.trychroma.com/research/context-rot) shows all frontier
   models degrade with input length regardless of window utilization —
   arguing for *earlier* triggers, not later. And the most-cited
   production failure mode is mid-task threshold compaction (see e.g.
   anthropics/claude-code#46602, #10948, #13919) — the later threshold
   fires, the more likely it interrupts ongoing reasoning.

The autonomous middleware (Layer 2) is the relief valve: at 0.75 it has
room to fire first at a clean task boundary, before the threshold layer
panics. Claude Code's VS Code extension ships 0.75; LangChain's
`create_deep_agent` ships 0.85. We pick 0.75 because we're carrying
Layer 2 — `create_deep_agent`'s setting assumes the autonomous tool will
catch most cases before the threshold, which is the same model we have.
Aggressive (0.60) is for users who explicitly accept frequent cache
invalidation in exchange for tighter overflow protection.

`mode: "off"` short-circuits codegen — no compaction code is emitted at all.

**Hash contribution.** All `Compaction` fields contribute to `AgentHashTree`.
Changing `mode` triggers a redeploy because the middleware wiring changes.

**Validation.** Pydantic constraints: `0 < trigger_pct < 1`,
`0 < keep_recent_pct < 1`, `prune_tool_output_bytes > 0`, `target_tokens > 0`.

## The `vystak_compactions` table

Single source of truth, separate from LangGraph's checkpoint. One row per
`(thread_id, generation)` so successive compactions don't overwrite history.

**Postgres DDL** (added to the existing `AsyncPostgresStore.setup()` block):

```sql
CREATE TABLE IF NOT EXISTS vystak_compactions (
    thread_id        TEXT NOT NULL,
    generation       INTEGER NOT NULL,
    summary_text     TEXT NOT NULL,
    up_to_message_id TEXT NOT NULL,
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    summarizer_model TEXT,
    trigger          TEXT NOT NULL,    -- 'autonomous' | 'threshold' | 'manual'
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (thread_id, generation)
);
CREATE INDEX IF NOT EXISTS vystak_compactions_thread_idx
    ON vystak_compactions (thread_id, generation DESC);
```

**SQLite** mirrors the schema in `AsyncSqliteStore` (extended in
`templates.generate_store_py()`).

**MemorySaver mode** uses an in-memory dict keyed by `thread_id`. Same shape,
no persistence — appropriate because the LangGraph state itself isn't
persisted in this mode either.

**Generations.** Successive compactions append; older rows are kept for
debugging and to support `--generation N` inspection later. The prompt
callable always reads the highest generation per `thread_id`.

## Layers

### Layer 1 — pre-call prune (`compaction/prune.py`)

Pure synchronous function, no LLM:

```python
def prune_messages(
    messages: list[BaseMessage],
    *,
    max_tool_output_bytes: int,
    keep_last_turns: int = 3,
) -> list[BaseMessage]:
    """Soft-trim oversized tool outputs head-and-tail; protect last N turns."""
```

- Scans `ToolMessage` instances older than `keep_last_turns` user→assistant pairs.
- Replaces oversized payloads with `head + "\n...truncated N bytes...\n" + tail`.
- Preserves the last `keep_last_turns` turns byte-for-byte.
- Never touches `HumanMessage` / `AIMessage` text content.
- In-memory only — does **not** write to the checkpoint or `compactions` table.

### Layer 2 — autonomous summarization tool

Codegen wires LangChain's `create_summarization_tool_middleware` into
`create_react_agent`:

```python
from langchain.agents.middleware import create_summarization_tool_middleware

agent = create_react_agent(
    model, tools, checkpointer=memory, store=store,
    prompt=prompt_fn,
    middlewares=[
        create_summarization_tool_middleware(
            model=summarizer_model,
            keep_last_n_messages=keep_n_recent,
        ),
    ],
)
```

When the middleware fires, an `on_summarize` callback writes the result to
`vystak_compactions` via `write_compaction(..., trigger="autonomous")`. The
table — not the middleware's internal state — is the source of truth that the
prompt callable reads on the next turn.

### Layer 3 — threshold pre-call summarize (`compaction/threshold.py`)

Runs in `_make_prompt` after Layer 1 prune, before sending to the LLM:

```python
# Idempotency thresholds — see "Layer coordination" below.
LAYER3_SUPPRESS_RECENT_PCT = 0.30
LAYER3_SUPPRESS_RECENT_SECONDS = 60


async def maybe_compact(
    messages,
    *,
    model,
    last_input_tokens: int | None,
    context_window: int,
    trigger_pct: float,
    keep_recent_pct: float,
    summarizer,
    compaction_store,
    thread_id,
) -> list[BaseMessage]:
    # Idempotency guard: if Layer 2 (autonomous middleware) just wrote a
    # compaction that already covers most of the current message list,
    # skip — otherwise we'd summarize a fresh summary.
    latest = await latest_compaction(compaction_store, thread_id)
    if latest is not None:
        already_covered = _fraction_covered(messages, latest.up_to_message_id)
        seconds_since = _seconds_since(latest.created_at)
        if (already_covered >= 1 - LAYER3_SUPPRESS_RECENT_PCT
                or seconds_since < LAYER3_SUPPRESS_RECENT_SECONDS):
            return messages  # let the existing compaction stand

    estimated = await estimate_tokens(
        messages, model=model, last_input_tokens=last_input_tokens,
    )
    if estimated < context_window * trigger_pct:
        return messages

    cutoff = max(1, int(len(messages) * (1 - keep_recent_pct)))
    older, recent = messages[:cutoff], messages[cutoff:]
    try:
        summary = await summarize(summarizer, older)
    except CompactionError as exc:
        # Fail open — return mechanically-truncated messages and record the
        # fallback reason on the call config. The server's streaming path
        # reads this off the config and emits the `x_vystak: {type:
        # "compaction_fallback", reason}` chunk; the non-streaming path logs
        # it server-side. See "Failure handling" for the exact surfaces.
        _record_fallback(thread_id, reason=str(exc))
        return _hard_truncate(messages, target_tokens)

    await write_compaction(
        compaction_store, thread_id, summary.text,
        up_to_message_id=older[-1].id,
        trigger="threshold",
        summarizer_model=summary.model_id,
        usage=summary.usage,
    )
    return [SystemMessage(content=summary.text)] + recent
```

**Token estimation.** The naive "use last turn's `input_tokens`" approach
is too optimistic — a single new turn can append a large tool output that
shifts the prefill by 20%+ tokens, and Anthropic prompt caching makes
*billable* prefill diverge from *actual* prefill in ways that aren't
visible to a previous-turn snapshot. We therefore prefer pre-flight token
counting and use the cached number only as a coarse early-out:

1. **Coarse early-out (cheap path)** — `last_input_tokens` from the
   previous turn's `usage_metadata` (already captured at
   `templates.py:198` and `:838`) plus a quick `chars/4` estimate on
   messages added since that turn. If the result is below
   `0.6 * trigger_pct * context_window` (i.e. clearly below threshold),
   skip the next step. This catches the common case (most turns) without
   making any provider call.
2. **Pre-flight tokenizer (authoritative path)** — when the early-out
   indicates we *might* be near threshold, call
   `model.aget_num_tokens_from_messages(messages)` and use its result for
   the actual gate. Anthropic: `POST /v1/messages/count_tokens` (free,
   ~50ms). OpenAI: local `tiktoken`. This is the number we trust for the
   trigger comparison.
3. **`chars/4` heuristic** — last-resort fallback if step 2 fails (network
   error, unsupported provider). Logged at WARNING — every fallback is a
   signal that the trigger gate is unreliable for this turn.

**Caveats documented in the code**: Anthropic explicitly states
`count_tokens` returns an estimate, not a contract. Claude 3.7+ thinking
blocks under-report by 5–15% in field reports. We treat the
`trigger_pct * context_window` threshold as the *intent*, not a hard
guarantee — overflow can still happen and Layer 3's fallback handles it.

### Layer coordination

All three layers write to `vystak_compactions` via the same `write_compaction`
entry point, but they fire on different cadences (autonomous = model decision,
threshold = prefill size, manual = user request). Without coordination, two
layers can fire on adjacent turns and produce a summary-of-summary, which is
the canonical cause of "summary drift" reported in production
(dbreunig "How Long Contexts Fail", 2025; Redis "Context Window Overflow",
2026).

**The rules:**

1. **Read path is single-source.** The prompt callable always assembles
   `[summary_of(latest_compaction)] + messages_after_up_to_id`. There is one
   `latest_compaction` per `thread_id`; the read never blends generations.
2. **Layer 3 defers to a recent Layer 2 / manual write.** If a compaction
   was written within the last 60 seconds *or* it already covers ≥70% of the
   current message list, Layer 3 returns messages unchanged. The guard
   prevents the autonomous middleware and the threshold layer from
   double-firing on the same turn boundary.
3. **Layer 2 is allowed to fire when there's already a compaction**, by
   design — the agent can ask for an updated summary mid-conversation. The
   new generation supersedes the old one for read purposes.
4. **Manual is always honored.** `/compact` writes regardless of recency,
   because it's an explicit user request.

**Message-ID stability.** `up_to_message_id` is the stable key that bridges
the compaction state to the LangGraph checkpoint. LangGraph's persistent
checkpointers (postgres, sqlite) assign stable IDs; `MemorySaver` does not
guarantee them across process restarts. For `MemorySaver` we use a
`thread_id`-scoped monotonic counter assigned at message-add time and stored
on the message's `additional_kwargs["vystak_msg_id"]`. The compaction store
records this counter, not the LangGraph-internal id. `_fraction_covered` and
the prompt callable both consult this attribute first, falling back to
`message.id` for persistent backends.

### Manual `/compact` endpoint

Generated when `compaction.mode != "off"`:

```python
class CompactRequest(BaseModel):
    instructions: str | None = None


@app.post("/v1/sessions/{thread_id}/compact")
async def compact_session(thread_id: str, body: CompactRequest):
    messages = await _load_thread_messages(thread_id)
    if not messages:
        raise HTTPException(404, "thread not found")
    summary = await summarize(
        _summarizer_model, messages,
        extra_instructions=body.instructions,
    )
    gen = await write_compaction(
        _compaction_store, thread_id, summary,
        up_to_message_id=messages[-1].id,
        trigger="manual",
        summarizer_model=_summarizer_model_id,
        usage=summary.usage,
    )
    return {
        "thread_id": thread_id,
        "generation": gen,
        "summary_preview": summary.text[:200],
        "messages_compacted": len(messages),
    }
```

**Chat channel pass-through.** `vystak-channel-chat`
(`server_template.py`) proxies `/v1/sessions/*` to the routed agent the same
way it already proxies `/v1/responses`. The chat channel resolves which
agent owns the supplied `thread_id` by reusing the response→agent map it
already maintains for `/v1/responses` chaining. Note: this replaces the
legacy `vystak-gateway` path; new server-side endpoints land on the chat
channel only.

**REPL (`vystak-chat`).**

- New `/compact [instructions]` slash command in `vystak_chat/chat.py:COMMANDS`.
- New `client.compact(url, thread_id, instructions)` helper in
  `vystak_chat/client.py`.
- Resolving `thread_id` from the REPL: the response store (`_responses`)
  already maps `response_id → thread_id`. Surface `thread_id` on the
  `GET /v1/responses/{response_id}` payload (one-line addition to
  `ResponsesHandler.get`) so the client can resolve from the most recent
  `previous_response_id`.

## Codegen wiring

Runtime module **`vystak_adapter_langchain/compaction.py`** (handwritten,
not generated). Public surface:

- `prune_messages(messages, *, max_tool_output_bytes, keep_last_turns)` — pure.
- `maybe_compact(...)` — Layer 3 entry point.
- `summarize(model, messages, *, instructions=None) -> SummaryResult` —
  single LLM call; returns `SummaryResult(text, model_id, usage)`. Raises
  `CompactionError` on any provider failure.
- `write_compaction(store, thread_id, text, *, up_to_message_id, trigger,
  summarizer_model, usage) -> int` — returns new generation; dispatches
  to postgres / sqlite / in-memory backend.
- `latest_compaction(store, thread_id) -> CompactionRow | None`.
- `estimate_tokens(messages, *, model, last_input_tokens) -> int` —
  three-tier strategy from Section "Token estimation".
- `CompactionError` — raised by `summarize` only; never raised by prune.

**Generated `agent.py`** changes (when `compaction.mode != "off"`):

- Adds `from vystak_adapter_langchain.compaction import prune_messages, maybe_compact`.
- `_make_prompt` rewires its tail: recall memories → assemble messages from
  state → `prune_messages(...)` → `maybe_compact(...)` → return.
- `create_react_agent` gains the `middlewares=[create_summarization_tool_middleware(...)]` argument.

**Generated `server.py`** changes (when `compaction.mode != "off"`):

- DDL emitted into the lifespan setup, alongside `await store.setup()`.
- `_compaction_store` global, initialized from the same connection as `_store`
  for postgres/sqlite, or as an in-memory dict for `MemorySaver`.
- `POST /v1/sessions/{thread_id}/compact` route.
- Response store entries gain a `last_input_tokens` field, threaded into the
  next turn's `config.configurable`.

`mode: "off"` is the no-op gate: identical predicate
`_compaction_enabled(agent)` consulted in all three files.

**`requirements.txt`** — when compaction is enabled, add
`langchain>=1.0,<1.2` (tight pin: `create_summarization_tool_middleware`
shipped in 1.0 in October 2025 and the API still exposes
`**deprecated_kwargs`, so we expect minor-version churn). The codegen also
emits a runtime version assertion at server startup so a stale lockfile
fails fast rather than producing silently-wrong middleware behavior.
`langchain-core` and `langgraph` are already pinned by the existing
template.

**Fallback path if the middleware moves under us.** `compaction.py`
exposes a `MANUAL_LANGCHAIN_FALLBACK` flag (env var
`VYSTAK_COMPACTION_FALLBACK=1`). When set, codegen omits the middleware and
Layer 2 becomes a `@tool def summarize_history(...)` that calls our own
`summarize()` and writes through `write_compaction`. Same data path, no
LangChain-middleware dependency. We don't ship this on by default — it's
the bail-out lever for when LangChain breaks the middleware API.

## Observability

Compaction is the single feature most likely to silently degrade quality.
Every layer emits structured logs and Prometheus-style counters; without
this, operators have no way to detect drift or misconfiguration.

**Counters** (one per agent canonical name, exposed at the existing
`/metrics` route the LangChain adapter already wires up):

- `vystak_compaction_total{layer, trigger, outcome}` — outcome ∈
  `{written, suppressed, failed_fallback, failed_hard}`. Suppressed means
  the idempotency guard skipped a Layer-3 fire.
- `vystak_compaction_input_tokens_total{layer}` and
  `vystak_compaction_output_tokens_total{layer}` — what the summarizer
  consumed and emitted; lets operators size summarizer cost.
- `vystak_compaction_messages_compacted{layer}` (histogram) — how many
  messages the summary replaced.
- `vystak_compaction_estimate_error{provider}` (histogram) — for every
  turn where Layer 3's pre-flight count was followed by a real
  `usage_metadata`, record the relative error. Drift in this histogram is
  the early warning that token counting has stopped being reliable for
  this provider.

**Structured logs** (one per compaction write, JSON):

```json
{"event": "vystak.compaction.write", "thread_id": "...", "generation": 3,
 "trigger": "threshold", "messages_compacted": 24, "summary_chars": 812,
 "summarizer_model": "claude-haiku-4-5-20251001",
 "input_tokens": 18234, "output_tokens": 412}
```

**Replay / inspection endpoint** — generations are kept on the table for a
reason. Expose them:

- `GET /v1/sessions/{thread_id}/compactions` — list all generations with
  `{generation, trigger, created_at, messages_compacted, summarizer_model}`.
- `GET /v1/sessions/{thread_id}/compactions/{generation}` — full row
  including `summary_text`. Useful when a user reports "the agent forgot
  X" — operators can read what was summarized away.

The chat-channel proxy passes both routes through. `vystak-chat` gets a
`/compactions` slash command that lists the table for the current thread.

## Tool-output offloading

Beyond head-and-tail truncation, large tool outputs (file reads, search
dumps, exec stdout) are offloaded:

- Tool outputs above `prune_tool_output_bytes` are written to
  `/tmp/vystak/{thread_id}/{tool_call_id}.txt` inside the agent container.
- The in-prompt representation collapses to:
  `[<tool_name>] OK ({bytes} bytes) | preview: {first_line}\n  → {path}`
- A new built-in tool `read_offloaded(path: str, offset: int = 0,
  length: int = 4000)` lets the agent re-fetch a slice on demand.
- Files are GC'd when the thread is destroyed (existing `vystak destroy`
  hook removes the per-thread directory).

This matches the Factory.ai / Deep Agents 2025–2026 pattern (path + preview)
and recovers detail that head-and-tail loses. Disabled when no `workspace`
is declared on the agent (no writable filesystem).

## Failure handling

`summarize()` raises `CompactionError` on any failure (LLM timeout, rate
limit, content policy, network). Per-layer behavior:

| Layer | On `CompactionError` | User-visible |
|---|---|---|
| Prune (Layer 1) | n/a — pure function | — |
| Autonomous middleware | logged; agent continues, tool returns error string | normal LangChain tool-error surface |
| Threshold (pre-call) | hard-truncate to `target_tokens`; emit `x_vystak: {type: "compaction_fallback", reason}` SSE chunk; turn proceeds | observable in stream; logged server-side |
| Manual `/compact` | HTTP 502, body `{error: {code: "compaction_failed", reason}}` | direct error to caller |

The threshold layer is the only place we silently fall back, by design (the
"fail open + observable" choice from question 6). Manual is interactive, so
it fails loudly.

## Testing

### Unit tests (`vystak-adapter-langchain/tests/`)

- **`test_compaction_prune.py`** — oversized tool outputs head/tail trimmed;
  last 3 turns preserved byte-for-byte; AI/Human text never touched;
  `keep_last_turns=0` and empty-list edge cases.
- **`test_compaction_threshold.py`** — mocked summarizer; below-trigger leaves
  messages unchanged; summarizer called with everything older than
  `keep_recent_pct`; on `CompactionError`, mechanical truncation kicks in and
  fallback signal is set; cached `last_input_tokens` short-circuits the
  tokenizer call; first-turn fallback to provider tokenizer.
- **`test_compaction_store.py`** — generation increments monotonically per
  `thread_id`; in-memory / sqlite / postgres backends behave identically
  (parametrized fixture); `latest_compaction` returns the highest generation.
- **`test_compaction_codegen.py`** — `mode: "off"` produces zero compaction
  code; `mode: "conservative"` emits middleware wiring with preset numbers;
  explicit numeric overrides win over preset; hash differs between
  `mode: "off"` and `mode: "conservative"`; `Compaction` schema validation
  rejects invalid values.
- **`test_compaction_endpoint.py`** — `POST /v1/sessions/{thread_id}/compact`
  with mocked summarizer returns 200 + generation; 404 on unknown thread; 502
  with `compaction_failed` body on summarizer error; `instructions` reaches
  `summarize()`.

### Schema test (`vystak/tests/test_agent.py`)

- `Compaction` round-trips through the YAML loader.
- `Agent.compaction = None` (default) doesn't break existing fixtures.

### Release cell

`packages/python/vystak-provider-docker/tests/release/test_C1_postgres_compaction.py`,
gated on `release_integration`:

1. Deploy a Postgres-backed agent with `compaction: {mode: "aggressive",
   trigger_pct: 0.05}` (fires after a few turns).
2. Drive ~30 turns of synthetic conversation through `/v1/responses`, each
   with a fake-large tool output.
3. Query the agent's container directly (`docker exec`) for the
   `vystak_compactions` table — assert at least one row exists with
   `trigger="threshold"`.
4. Assert subsequent turns send the summary in the system prompt (verified
   by reading the agent's last log line — generated server logs the assembled
   prompt at DEBUG).
5. Hit `POST /v1/sessions/{thread_id}/compact` with
   `instructions="focus on the user's name"` — assert HTTP 200 and a new
   generation row.
6. Standard `vystak destroy` teardown via the existing `project` fixture.

Mocked LLM via `ANTHROPIC_API_URL` pointing at the existing `vystak-mock-llm`
test fixture (deterministic short responses + arbitrary tool outputs). No
real LLM cost.

### Drift / coordination tests

- **`test_compaction_layer_coordination.py`** — drives a sequence that
  forces Layer 2 (autonomous, mocked tool call) and Layer 3 (threshold) to
  contend on the same turn boundary. Asserts: only one row written;
  `outcome=suppressed` counter increments for the loser; the surviving
  generation has the higher coverage.
- **`test_compaction_drift.py`** — synthesizes a 5+ generation chain
  (force-trigger compaction, then again, and again, …) and asserts: every
  generation's `up_to_message_id` strictly advances; summary length stays
  bounded (each summary is ≤ `target_tokens`, not growing); the first
  generation's summary text remains retrievable via the inspection
  endpoint after the fifth generation is written.
- **`test_compaction_message_id_stability.py`** — runs the full prune /
  compact path against `MemorySaver`, asserts that `vystak_msg_id` survives
  message reordering caused by `add_messages` reducer interleaving and that
  `_fraction_covered` returns identical values across a process restart.

### Explicitly out of scope for first ship

- `release_live_chat` cell with a real Haiku summarizer.
- Cross-provider parity test (Azure inherits the same generated server, so
  the Docker cell covers the codegen).

## File touch list

**New files**

- `packages/python/vystak/src/vystak/schema/compaction.py`
- `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/compaction.py`
- `packages/python/vystak-adapter-langchain/tests/test_compaction_prune.py`
- `packages/python/vystak-adapter-langchain/tests/test_compaction_threshold.py`
- `packages/python/vystak-adapter-langchain/tests/test_compaction_store.py`
- `packages/python/vystak-adapter-langchain/tests/test_compaction_codegen.py`
- `packages/python/vystak-adapter-langchain/tests/test_compaction_endpoint.py`
- `packages/python/vystak-adapter-langchain/tests/test_compaction_layer_coordination.py`
- `packages/python/vystak-adapter-langchain/tests/test_compaction_drift.py`
- `packages/python/vystak-adapter-langchain/tests/test_compaction_message_id_stability.py`
- `packages/python/vystak-provider-docker/tests/release/test_C1_postgres_compaction.py`

**Modified files**

- `packages/python/vystak/src/vystak/schema/agent.py` — add `compaction` field.
- `packages/python/vystak/src/vystak/schema/__init__.py` — re-export `Compaction`.
- `packages/python/vystak/src/vystak/hash/tree.py` — hash contribution.
- `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py`
  — wire compaction into `agent.py` and `server.py` codegen, extend SQLite
  store with the `vystak_compactions` table.
- `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/responses.py`
  — surface `thread_id` on `GET /v1/responses/{response_id}` and thread
  `last_input_tokens` through the response store.
- `packages/python/vystak-channel-chat/src/vystak_channel_chat/server_template.py`
  — proxy `/v1/sessions/*` (compact write + inspection reads).
- `packages/python/vystak-chat/src/vystak_chat/chat.py` — `/compact` slash command.
- `packages/python/vystak-chat/src/vystak_chat/client.py` — `compact()` helper.
- `packages/python/vystak/tests/test_agent.py` — schema round-trip.
- `test_plan.md` — add C-axis (compaction) cell to the matrix.
