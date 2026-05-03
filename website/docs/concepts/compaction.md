---
title: Session compaction
sidebar_label: Compaction
---

# Session compaction

Long conversations grow without bound. Replaying every turn into the
prompt eventually overflows the model's context window, drives prefill
cost up, and dilutes recent intent with stale tool output. Vystak
compacts sessions in three layers, all running on the agent server next
to the LangGraph checkpoint.

## When to enable it

- Agents that hold long-running conversations — support assistants,
  multi-turn debugging copilots, anything with `sessions.engine =
  postgres` or `sqlite`.
- Agents that emit large tool outputs (file reads, search dumps, exec
  stdout) where most of each prefill is dead weight.

If your agent does one-shot turns or always starts a fresh thread,
compaction has nothing to do — leave it off.

## The three layers

### Layer 1 — tool-output prune

Always-on, no LLM call, pure function. Before every turn, scans
`ToolMessage` entries older than the last few user→assistant turns. If
their content is bigger than `prune_tool_output_bytes` (default 4 KB),
they're rewritten as `head + "...truncated N bytes..." + tail`. The
last N turns are preserved byte-for-byte.

This is cheap defense — it catches the common case of an agent quoting
a 50 KB file read into the prompt forever.

### Layer 3 — threshold pre-call summarize

Runs in the prompt callable, before the LLM sees the messages. Token
estimate (sync tokenizer when the model exposes one, otherwise a
calibrated chars/3.5 fallback) decides whether prefill is at
`trigger_pct × context_window`. If so:

1. Split into `older` (everything except the recent zone) + `recent`.
2. Summarize `older` with the configured summarizer model.
3. Replace older messages with a single `SystemMessage(summary)`.

Subsequent turns read `latest_compaction(thread_id)` and assemble
`[summary] + messages_after_up_to_id` so the summary persists across
turns. The original LangGraph checkpoint is never rewritten — every
generation lives in the `vystak_compactions` table.

A 60-second / 70%-coverage idempotency guard suppresses Layer 3 when a
recent compaction already covers most of the message list, so the
threshold never re-summarizes the same span.

### Manual `/compact`

`POST /v1/sessions/{thread_id}/compact` with optional
`{"instructions": "..."}` body. Forces a compaction regardless of
trigger state. Useful as a slash command (`/compact` in `vystak-chat`)
or as a checkpoint at task boundaries.

## What's not Layer 2

The original design called for an autonomous-tool middleware (the model
decides when to summarize at clean task boundaries). LangChain renamed
that API in 1.1 (`SummarizationMiddleware`) and removed the
autonomous-tool variant. The remaining threshold class is incompatible
with vystak's `prompt=` callable architecture, so vystak doesn't wire
it. Layer 3 in the prompt callable provides the same threshold
guarantee. (See `vystak.schema.compaction` for the full rationale.)

## Schema

```yaml
agents:
  - name: chatty
    model: agent_model
    sessions:
      type: postgres
      provider: {name: docker, type: docker}
    compaction:
      mode: aggressive            # off | conservative | aggressive
      trigger_pct: 0.3             # optional override (0 < x < 1)
      keep_recent_pct: 0.2         # optional override
      prune_tool_output_bytes: 4096
      target_tokens: 50000         # post-compaction target
      context_window: 5000         # override the model's nominal window
      summarizer:                  # optional — falls back to agent.model
        name: summarizer
        provider: {name: anthropic, type: anthropic}
        model_name: claude-haiku-4-5-20251001
        api_keys: {name: ANTHROPIC_API_KEY}
```

### Mode presets

| Field | `conservative` (default) | `aggressive` |
|---|---|---|
| `trigger_pct` | 0.75 | 0.60 |
| `keep_recent_pct` | 0.10 | 0.20 |
| `prune_tool_output_bytes` | 4096 | 1024 |
| `target_tokens` | half of `context_window` | quarter |

`mode: off` short-circuits the codegen — no compaction code is emitted
and no langchain extras are pulled into `requirements.txt`.

### `context_window`

Defaults to a built-in table (200K for current Claude/Sonnet/Haiku, 128K
for `gpt-4o`, 1M for `gpt-4.1`, 200K for unknown models). Override to:

- **Test compaction quickly** — set `5000` and compaction fires within
  a handful of turns instead of needing a real long conversation.
- **Match an unfamiliar model** — when you point `ANTHROPIC_API_URL` at
  a non-Anthropic endpoint or run a model not in the built-in table.

## What gets stored

Every compaction (Layer 3 *and* manual) appends a row to
`vystak_compactions`:

| column | description |
|---|---|
| `thread_id`, `generation` | composite PK, generation increments per thread |
| `summary_text` | the summary text |
| `up_to_message_id` | stable `vystak_msg_id` of the last message replaced |
| `trigger` | `threshold` or `manual` |
| `summarizer_model` | actual model name used for the summary |
| `input_tokens`, `output_tokens` | usage from the summarizer call |
| `created_at` | timestamp |

The LangGraph checkpoint is never rewritten — older generations stay
queryable for audit and debugging.

## Inspection endpoints

Generated on every compaction-enabled agent:

- `POST /v1/sessions/{thread_id}/compact` — force a compaction
- `GET /v1/sessions/{thread_id}/compactions` — list all generations
- `GET /v1/sessions/{thread_id}/compactions/{generation}` — full row

The chat-channel proxy (`vystak-channel-chat`) forwards all three so
they're reachable through the OpenAI-compatible front door.

`vystak-chat` slash commands `/compact [instructions]` and
`/compactions` resolve `thread_id` from the most recent
`previous_response_id` and call the inspection endpoints.

## Failure handling

| Layer | On summarizer error | User-visible |
|---|---|---|
| Prune | n/a — pure function | — |
| Threshold | hard-truncate to `target_tokens`, set `_vystak_compaction_fallback` on call config | observable via `x_vystak` SSE chunk; logged WARNING |
| Manual | HTTP 502 with `code: "compaction_failed"` | direct error to caller |

The threshold layer fails open by design — a missed compaction is
preferable to a dropped turn. Manual is interactive, so it fails loudly.

## Token estimation strategy

Three tiers, in order:

1. **Cheap early-out** — last turn's `usage_metadata.input_tokens`
   plus `chars/3.5 × 1.10` on new messages. Skips the pre-flight if
   well below threshold.
2. **Provider tokenizer** — calls
   `model.aget_num_tokens_from_messages` (async) or
   `get_num_tokens_from_messages` (sync, run in a worker thread).
   Anthropic models expose only the sync version in langchain 1.x.
3. **Calibrated chars/3.5** — last-resort fallback. The 4-chars/token
   GPT heuristic underestimates Anthropic prefill; Claude's tokenizer
   yields ~3.5 chars/token in practice, plus we add a 10% safety
   margin for system prompt and tool definitions.

Probe results are cached per-model so models without either tokenizer
log INFO once instead of WARNING every turn.

## Observability

In-process counters per agent (`vystak_compaction_total{layer, trigger,
outcome}`, `vystak_compaction_input_tokens_total{layer}`,
`vystak_compaction_messages_compacted{layer}`,
`vystak_compaction_estimate_error{provider}`,
`vystak_compaction_suppressions{layer, reason}`).

Structured logs:

```
vystak.compaction.threshold.suppressed thread_id=... covered=0.85 seconds_since=12
vystak.compaction.threshold.fallback thread_id=... reason="rate limited"
```

## Example

`examples/docker-compaction/` is a complete working setup with Postgres
sessions + chat channel + Slack channel + compaction tuned for fast dev
loops (5K context, 0.3 trigger). Walks through deploy → drive → inspect
→ destroy.

## Related

- [Services](./services) — Postgres / SQLite session store backing
- [Channels](./channels) — `vystak-channel-chat` proxies the inspection
  endpoints

## Status

Compaction is wired into agents generated by `vystak-adapter-langchain`
when `compaction.mode != "off"`. Tested end-to-end against Postgres
sessions on Docker; stub-tested for SQLite and in-memory backends.
