# Slack Tool-Call Streaming — Design

**Date:** 2026-04-27
**Status:** Approved (brainstorm)
**Scope:** `vystak-channel-slack`, `vystak-adapter-langchain`, `vystak.schema.channel`. No
provider changes; works on every platform that runs the langchain
adapter.

## Goal

Surface intermediate tool-call activity as live updates to the Slack
message that holds the agent's reply. When the channel is configured
with `stream_tool_calls: true`, users see a progress trail (`🔧 tool
✓ duration`) while the agent works, then the final reply replaces it.
Default behavior (flag off) is unchanged — one-shot reply via
`send_task` exactly as today.

## Why

Today the bot posts a placeholder ("_Responding..._"), runs the agent
synchronously, then edits the placeholder with the final answer. There
is no signal during multi-tool turns: a fan-out call to `ask_weather`
+ `ask_time` looks identical to a stalled one until the final reply
lands. For agents that delegate to slow peers or external services,
this is invisible. Streaming surfaces "I'm doing something" without
forcing token-by-token edits (which Slack rate-limits and which produce
visual noise).

## Non-goals

- **Per-token streaming.** Slack's `chat.update` is rate-limited at
  ~1/sec for tier-3 apps. Token streaming would either drop tokens or
  spam the API. Final-text-only replacement avoids the rate limit
  entirely.
- **Showing tool arguments or raw results.** Privacy-sensitive content
  (user names, addresses, API responses) doesn't belong in the visible
  progress trail. The user sees what was called and how long; not what
  was passed in.
- **Streaming in DMs.** DMs are private 1:1; the same trail-then-replace
  flow applies, but the privacy concern about visible args/results is
  weaker. Implementation handles DMs identically to channels — no
  separate code path.
- **Tool-call streaming for non-A2A channels.** Out of scope; the API
  channel and CLI chat have their own streaming surfaces.

## Decisions captured during brainstorm

| # | Question | Decision |
|---|----------|----------|
| 1 | What's shown per tool call? | `🔧 <tool>` on start; replaced with `🔧 <tool> ✓ (Xs)` on end. No args, no return values. |
| 2 | On error | Replace progress trail with the existing "Sorry, I hit an error talking to *X*: ..." message — same UX as non-streaming. |
| 3 | Final reply formatting | Replace the entire progress trail with the final reply text. No collapsible details (Slack mrkdwn doesn't support it). |

## Architecture

The change spans three layers, in order of execution:

```
   ┌───────────────────────────────────┐
   │  Slack channel runtime            │
   │  ┌───────────────────────────┐    │
   │  │ on_mention / on_message   │    │
   │  │   ↓ if stream_tool_calls: │    │
   │  │   _stream_to_agent(...)   │ ───┼─── tasks/sendSubscribe (SSE)
   │  └───────────────────────────┘    │           │
   └───────────────────────────────────┘           │
                                                   ▼
   ┌───────────────────────────────────────────────────┐
   │  Agent runtime (server.py)                        │
   │  ┌─────────────────────────────────────────────┐  │
   │  │ _a2a_streaming                              │  │
   │  │   ↓                                         │  │
   │  │ process_turn_streaming                      │  │
   │  │   ↓ astream_events("v2")                    │  │
   │  │   ↓ on_tool_start  → TurnEvent(tool_start)  │  │
   │  │   ↓ on_tool_end    → TurnEvent(tool_end)    │  │
   │  │   ↓ on_chat_model_stream → (skipped)        │  │
   │  │   ↓ final          → TurnEvent(final)       │  │
   │  └─────────────────────────────────────────────┘  │
   └───────────────────────────────────────────────────┘
```

**Existing pieces (no change required):**
- `_a2a_streaming` already exists and forwards `TurnEvent`s as
  `A2AEvent`s over SSE. Today it only handles `token`, `interrupt`,
  `final`. We extend the type set.
- `process_turn_streaming` already iterates `astream_events("v2")`
  and emits `TurnEvent`s. Today it ignores `on_tool_start` /
  `on_tool_end` for token tracking purposes. We add new emissions.

**New pieces:**
- `SlackChannelConfig.stream_tool_calls: bool = False` (schema)
- `_stream_to_agent(...)` in `server_template.py` — parallel to
  `_forward_to_agent` but consumes the streaming generator.
- `TurnEvent` type discriminator extended: `tool_call_start` and
  `tool_call_end`.

## Data shapes

### `TurnEvent` (extended)

```python
@dataclass
class TurnEvent:
    type: Literal[
        "token",            # existing — per-token text chunk (skipped by Slack)
        "tool_call_start",  # NEW — emitted when a tool invocation begins
        "tool_call_end",    # NEW — emitted when a tool invocation finishes
        "interrupt",        # existing — input_required state
        "final",            # existing — completed turn, accumulated text
        "error",            # existing — declared but unused; still unused
    ]
    text: str = ""
    data: dict | None = None  # carries tool_name, duration_ms, etc.
    final: bool = False
```

For the new events, `data` carries:

```python
# tool_call_start
{"tool_name": "ask_weather_agent", "started_at": 1777300000.123}

# tool_call_end
{"tool_name": "ask_weather_agent", "duration_ms": 2103}
```

### `SlackChannelConfig` (extended)

```python
class SlackChannelConfig(BaseModel):
    port: int = 8080
    stream_tool_calls: bool = False  # NEW
```

### Channel-config JSON the runtime reads

```json
{
  ...existing fields...,
  "stream_tool_calls": true
}
```

## Runtime flow (channel side)

When `stream_tool_calls=True`:

1. **Resolve agent + post placeholder** — same as today: `_post_placeholder(say, thread_ts=...)` returns `{"channel", "ts"}`.
2. **Open A2A stream** — call `_default_client().stream_task(agent_name, text, metadata=..., timeout=...)`. Returns an `AsyncIterator[A2AEvent]`.
3. **Maintain a progress buffer** — list of `(tool_name, started_at, ended_at)` tuples plus a final-text holder.
4. **Throttled message edits** — keep `last_update_at`. On every event, if `time() - last_update_at >= 1.0`, render the buffer to mrkdwn and call `client.chat_update(channel=, ts=, text=...)`. Otherwise queue.
5. **Final event** — render the final reply (via `_to_slack_mrkdwn`) and `chat_update` with that text, replacing the entire progress trail.
6. **Errors** — on transport-layer or A2A error, replace the placeholder with the existing "Sorry, I hit an error talking to *X*: ..." text.

When `stream_tool_calls=False` — call `_forward_to_agent` as today; no stream consumer.

## Runtime flow (agent side)

`process_turn_streaming` already iterates `astream_events("v2")`. Extend the dispatcher:

```python
async for event in _agent.astream_events(agent_input, config=config, version="v2"):
    if "__interrupt__" in event:
        # ... existing
        return

    ev_kind = event.get("event")
    if ev_kind == "on_chat_model_stream":
        # ... existing token handling

    elif ev_kind == "on_tool_start":
        tool_name = event.get("name") or event.get("data", {}).get("name", "?")
        yield TurnEvent(
            type="tool_call_start",
            data={
                "tool_name": tool_name,
                "started_at": time.time(),
            },
        )

    elif ev_kind == "on_tool_end":
        tool_name = event.get("name") or event.get("data", {}).get("name", "?")
        # NOTE: existing on_tool_end branch already collects tm for memory.
        # Keep that, plus emit the new event.
        yield TurnEvent(
            type="tool_call_end",
            data={
                "tool_name": tool_name,
                "duration_ms": ...,  # tracked via a per-tool start_at map
            },
        )

    # ... rest unchanged
```

The duration is tracked by accumulating start times in a local
`dict[run_id, float]` keyed by langgraph's `event["run_id"]`.
`on_tool_end` looks up the start time and computes `duration_ms`.

## A2A wire shape

`_a2a_streaming` translates each `TurnEvent` into an `A2AEvent`. Add
two pass-throughs:

```python
elif ev.type == "tool_call_start":
    yield A2AEvent(type="tool_call", data=ev.data)

elif ev.type == "tool_call_end":
    yield A2AEvent(type="tool_result", data=ev.data)
```

`A2AEvent.type` already supports `"tool_call"` and `"tool_result"`
(see `vystak.transport.types`). The Slack channel reads them and
updates the buffer.

## Mrkdwn rendering of the progress trail

Each in-flight tool: `🔧 *<tool_name>*`
Each completed tool: `🔧 *<tool_name>* ✓ _(2.1s)_`

The trail is the placeholder text — newline-separated lines. Header
stays as `_Responding..._` until the first tool event lands, then is
replaced with `_Working..._`.

Worked example, 2 tools fanning out + final:

```
After tool_call_start(weather):
🔧 *ask_weather_agent*
_Working..._

After tool_call_start(time):
🔧 *ask_weather_agent*
🔧 *ask_time_agent*
_Working..._

After tool_call_end(weather, 2103ms):
🔧 *ask_weather_agent* ✓ _(2.1s)_
🔧 *ask_time_agent*
_Working..._

After tool_call_end(time, 412ms):
🔧 *ask_weather_agent* ✓ _(2.1s)_
🔧 *ask_time_agent* ✓ _(0.4s)_
_Working..._

After final:
<final reply text> ← entire trail replaced
```

## Files touched

| Path | Change |
|------|--------|
| `packages/python/vystak/src/vystak/schema/channel.py` | Add `stream_tool_calls: bool = False` to `SlackChannelConfig`. |
| `packages/python/vystak-channel-slack/src/vystak_channel_slack/plugin.py` | Emit `stream_tool_calls` into `channel_config.json`. |
| `packages/python/vystak-channel-slack/src/vystak_channel_slack/server_template.py` | (1) Read flag from `channel_config.json`; (2) add `_stream_to_agent` async helper; (3) branch in both `on_mention` and `on_message` thread-follow path; (4) reuse the new helper from the test API too if test API hits a tool path. |
| `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/turn_core.py` | Extend the `TurnEvent.type` Literal; add `tool_call_start` / `tool_call_end` emissions in `process_turn_streaming`. |
| `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/a2a.py` | Map the new `TurnEvent` types into `A2AEvent` (already-supported wire types). |
| `packages/python/vystak-channel-slack/tests/test_plugin.py` | Add `TestSlackChannelStreamToolCalls` — assert the flag is wired into `channel_config.json` and into `SERVER_PY` references. |
| `packages/python/vystak-adapter-langchain/tests/test_turn_core.py` | Add tests for the new TurnEvent types and the duration-tracking helper. |
| `packages/python/vystak-adapter-langchain/tests/test_a2a.py` | Add string-presence test that the streaming path emits the new wire types. |

No provider changes. No CLI changes. No documentation in `website/`
beyond a one-paragraph addition in `slack.md` (deferred to the plan).

## Testing

### Unit tests

1. **Schema** — Pydantic round-trip for `SlackChannelConfig(stream_tool_calls=True)`.
2. **Plugin emit** — `channel_config.json` contains `"stream_tool_calls": true` when the channel declares it.
3. **`SERVER_PY` content** — when `stream_tool_calls=True`, server.py contains the `_stream_to_agent` helper and references the flag.
4. **`turn_core.py` emission** — emitted `process_turn_streaming` includes the `on_tool_start` and `on_tool_end` branches; `tool_call_start` and `tool_call_end` literals appear in the `TurnEvent.type` annotation.
5. **A2A wire mapping** — emitted `_a2a_streaming` translates `tool_call_start` → `A2AEvent(type="tool_call")` and `tool_call_end` → `A2AEvent(type="tool_result")`.

### Integration test (release-tier)

Add a release-tier test that:

1. Deploys `examples/docker-slack-multi-agent` with `stream_tool_calls: true`.
2. Hits the test API (`/test/event`) with a multi-tool prompt
   ("weather in Lisbon and current time"). Note: the test API path
   needs to surface streaming events too — see Note below.
3. Asserts the response (or the live channel-state mock) shows at
   least 2 tool-call events plus a final.

**Note on test API:** the existing `POST /test/event` returns a single
JSON dict. To test the streaming path, we either (a) add a new
`POST /test/stream` SSE endpoint that mirrors the production flow,
or (b) accept that the test API only verifies the one-shot path and
relies on the unit tests for streaming verification. Choosing **(b)
for v1**: the streaming code path goes through `_stream_to_agent` →
`stream_task` → `_a2a_streaming` → `process_turn_streaming`, all of
which are independently tested. End-to-end visual verification stays
manual via Slack itself.

## Acceptance criteria

1. `SlackChannelConfig(stream_tool_calls=True)` validates and round-trips through pydantic.
2. With `stream_tool_calls: true` in `vystak.yaml`, `channel_config.json` carries the flag.
3. The channel container's `SERVER_PY` references `_stream_to_agent` and reads the flag at startup.
4. `process_turn_streaming` emits `TurnEvent(type="tool_call_start")` on every `on_tool_start` from langgraph and `TurnEvent(type="tool_call_end")` with `duration_ms` on every `on_tool_end`.
5. `_a2a_streaming` forwards both as `A2AEvent(type="tool_call")` and `A2AEvent(type="tool_result")` respectively.
6. The Slack channel runtime, when streaming is enabled, edits the message via `chat.update` no more than once per second per turn (rate-limit honoured).
7. On `final`, the entire progress trail is replaced with the final reply text via a single `chat_update`.
8. On error, the placeholder is replaced with the existing "Sorry, I hit an error talking to *X*: ..." message — same UX as the non-streaming path.
9. `stream_tool_calls=false` (default) preserves today's behavior exactly — `_forward_to_agent` is called, no streaming.
10. `just lint-python`, `just test-python`, `just typecheck-typescript`, `just test-typescript` all pass.

## Out of scope (deferred)

- Per-token streaming (replaced text in-place as tokens arrive). Slack's rate limit makes this awkward; revisit if a clear use-case appears.
- Showing tool args or results in the trail. Privacy-sensitive; revisit only with an explicit per-channel toggle and content-redaction pass.
- Streaming for `/v1/chat/completions` and `/v1/responses` consumers — the SSE shapes for those are different (`tool_call_chunk` deltas, etc.). Already partially supported pre-refactor; restoring is a separate spec.
- Generic "agent activity log" persistence (saving the trail somewhere queryable). The Slack channel is the rendered surface; log persistence would be a separate observability feature.

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Slack `chat.update` rate-limit (1/sec tier-3) | Throttle in `_stream_to_agent` — coalesce updates, never call faster than 1/sec. Final update is exempt (it's the user's reply, must land). |
| `astream_events("v2")` `on_tool_start`/`on_tool_end` shape differences across langgraph versions | Keep the dispatcher tolerant: read tool_name from both `event.get("name")` and `event["data"].get("name")`. Bug-compatible with how the existing code already reads `event["data"].get("output")`. |
| Streaming path silently drops `handle_memory_actions` (regression of bug fixed 2026-04-26) | The existing `process_turn_streaming` already calls `handle_memory_actions(_store, tool_msgs, ...)` at end-of-stream. New tool-event emissions don't change that path. Test-coverage gate `TestSharedTurnCoreInvariants` keeps it locked. |
| User accidentally enables in production with a noisy multi-tool agent → message becomes a wall of tool calls | Future improvement: coalesce repeated calls of the same tool into one line with a counter. Not needed for v1 — accept the noise. |
| `_a2a_streaming` itself was the source of past bugs (e.g., on_tool_end output as bare string) | The fix in `process_turn_streaming` for those bugs (SimpleNamespace wrap) remains. The new tool-event emissions are independent of memory handling — they're orthogonal additions to the same dispatcher. |
