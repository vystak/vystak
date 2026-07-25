# Panel NATS Transport + Resumable Streaming — Design

**Date:** 2026-07-25
**Status:** Approved

## Problem

The control panel (`vystak-channel-panel`) bypasses the transport layer entirely:
it calls agents with raw `httpx` against `{agent}/v1/responses` (SSE). Under
`transport: nats` the routes file contains a NATS subject, not a URL, so the
panel is structurally broken on NATS. Streaming is also fragile everywhere:

- No durability: NATS "streaming" uses an ephemeral core-NATS reply inbox
  (`NatsTransport._stream_via_inbox`); if the subscriber dies, chunks are lost.
  `NatsTransport(jetstream=True)` stores the flag and never uses it.
- No agent-side peer: agents run `NatsHttpBridge` (single-reply only); nothing
  calls `Transport.serve()` with a `ServerDispatcher`, so `responses/create`,
  `responses/createStream`, and `tasks/sendSubscribe` sent by `NatsTransport`
  have no handler.
- No ordering or identity: neither `A2AEvent` nor the panel SSE carries a
  sequence number or stream/turn id; the panel persists one final assistant
  row per turn.
- Coupled lifetimes: a browser disconnect closes the httpx stream and abandons
  the agent turn.

## Goal

Full decoupling: the agent publishes stream chunks to JetStream regardless of
who is listening; the panel (and any number of tabs) subscribe/replay from a
durable stream. Resumable streaming is a **NATS-only capability**; on the
default HTTP transport the panel keeps its current direct-streaming behavior
(graceful degradation — the channel does not dictate the transport).

## Design

### 1. Durable stream backbone (vystak-transport-nats)

- **JetStream stream:** one per `{prefix}.{ns}` base, name
  `{prefix}-{ns}-streams` (dots → dashes; JetStream stream names cannot
  contain dots), subjects `{prefix}.{ns}.streams.>`, file storage, limits
  retention, `max_age` ≈ 1h. Provisioned lazily via idempotent
  `add_stream`/`update_stream` from whichever side touches it first (agent
  publisher or panel subscriber). The Docker NATS node already starts the
  broker with JetStream enabled (`-js -sd /data` on the `vystak-nats-data`
  volume) — no provider change needed. Azure has no NATS provisioning node,
  so NATS panels on Azure are out of scope.
- **Turn subjects:** `{prefix}.{ns}.streams.{conversation_id}.{turn_id}`,
  where the `{prefix}.{ns}` base is derived from the agent's tasks subject
  in `routes.json` (everything before `.agents.`).
- **Event envelope:** each published message is `{seq, event}`. `seq` is an
  explicit 0-based counter assigned by the agent (JetStream's stream sequence
  is global, not per-subject). `event` is the exact OpenAI Responses SSE
  payload the agent already produces (`response.output_text.delta`,
  `response.output_item.added`, `function_call_arguments.*`,
  `response.completed` / `response.failed`). Terminal events are the ones the
  panel already recognizes — no new event taxonomy.
- **New RPC method `responses/createDetached`:** sent over the agent's
  existing tasks subject with the Responses body plus `turn_id` and
  `stream_subject`. The agent replies immediately with an ack
  (`{turn_id, stream_subject}` or JSON-RPC error), then runs the turn to
  completion in a background task, publishing every event to the stream
  subject via `js.publish()`. Turn lifetime is fully decoupled from consumers.

**v1 simplification:** resume always replays from `seq` 0 (retention ~1h,
turns are small). `seq` is used for ordering/gap sanity, not incremental
`Last-Event-ID` resume. The UI rebuilds the in-flight assistant message
wholesale on reconnect — the same thing it does on page load.

### 2. Agent side (template runtime)

**Amended 2026-07-25 during planning.** The original design replaced
`NatsHttpBridge` with a `ServerDispatcher` + `Transport.serve()`. That is not
implementable today: agent images pip-install `vystak` **from PyPI** (bare
`vystak` in `_vystak/requirements.txt`) and do not install
`vystak-transport-nats` at all — new transport-package code cannot reach
agent containers until published, which would make the feature untestable in
release tests. Channel images, by contrast, bundle local package source, so
new `vystak-transport-nats` client code works in the panel immediately.

Instead, the agent side **extends `NatsHttpBridge`** (template-owned code,
consistent with its documented thin-proxy design; the bridge remains the
single queue-group subscriber). New method routing in `_forward`:

- `responses/create` — POST the request body (stream forced off) to
  `http://localhost:{port}/v1/responses`, reply with the JSON result (fixes
  the currently-dead `responses/create` over NATS as a side effect).
- `responses/get` — GET `http://localhost:{port}/v1/responses/{id}`, reply
  with the result (`null` on 404).
- `responses/createDetached` — validate (`request`, `turn_id`,
  `stream_subject` required), publish the ack reply immediately, then spawn a
  tracked background task: ensure the JetStream stream exists (plain
  `nats-py`, already a template dependency), POST `/v1/responses` with
  `stream: true` over localhost, parse the SSE lines, publish each event as
  `{seq, event}` to `stream_subject` via `js.publish()`; on any failure
  publish a synthesized `response.failed` terminal event.
- Everything else — existing raw-envelope forwarding to `/a2a`, unchanged.

The subject/stream naming helpers are duplicated in the template (it cannot
import `vystak_transport_nats`) with keep-in-sync comments on both copies —
same precedent as the skill-digest rules. `dispatch_a2a_stream` /
`dispatch_responses_create_stream` inbox streaming stays out of scope.

### 3. Panel channel (Python)

- **Transport selection at startup:** `VYSTAK_TRANSPORT_TYPE=http` → existing
  `ResponsesClient`, untouched; `=nats` → new `NatsPanelClient` wrapping
  `NatsTransport` (the routes entry `address` is already the right subject).
  `agent_base_url()` is only consulted on the HTTP path.
- **Schema migration:**
  - `conversations.active_turn_id` (nullable text) — set when a turn is
    dispatched, cleared when the terminal event is persisted.
  - `messages.turn_id` (nullable text) — lets a resumed client correlate the
    persisted row with the stream it watched.
- **Turn lifecycle (NATS):** `POST /messages` persists the user row, generates
  `turn_id`, sets `active_turn_id`, sends `responses/createDetached`. On ack it
  spawns a **persister task** owned by the panel process: an ordered JetStream
  consumer on the turn subject that accumulates text/parts exactly like
  today's `gen()` and, on the terminal event, writes the single assistant row,
  updates `last_response_id`, and clears `active_turn_id`. The HTTP response
  to the POST is a *second*, independent consumer proxying events as SSE
  (today's `delta` / `tool_call` / `tool_result` / `done` / `error` frames,
  plus `turn_id` and `seq`).
- **Resume endpoint:** `GET /api/conversations/{conv_id}/stream` — if
  `active_turn_id` is set, attach an ordered consumer from seq 0 and proxy as
  SSE; otherwise 204. No `from` offset in v1.
- **Crash recovery:** on panel startup, scan conversations with non-null
  `active_turn_id` and re-spawn persister tasks (replay from 0 rebuilds the
  accumulator).
- **Staleness:** persister idle timeout ≈ 120s with no new events → persist
  what it has as an error-annotated row, clear `active_turn_id`.

### 4. Next.js panel

- `app/api/chat/route.ts` gains a `GET` handler: resolve the conversation,
  call the panel resume endpoint, pipe through the existing
  `panelStreamToUIChunks` adapter unchanged (resumed streams start at seq 0,
  so it sees a well-formed stream). 204 → "nothing to resume".
- `chat.tsx` enables AI SDK v5 resume (`resume: true` on `useChat`), which
  fires the GET on mount. Page load mid-turn = server-rendered history + live
  tail. Multiple tabs each get their own consumer on the same subject.
- On HTTP transport the GET always 204s — identical UI code on both
  transports.

## Failure modes

- **Agent dead before ack** → JSON-RPC error/timeout on `createDetached` →
  panel emits an `error` SSE frame and clears `active_turn_id`; the user row
  stays (matches today's error behavior).
- **Broker restart mid-turn** → file-backed JetStream retains published
  chunks; the agent's remaining publishes fail → agent logs and abandons; the
  panel persister hits its idle timeout. Accepted v1 edge.
- **Duplicate persisters** → persist is guarded by re-checking
  `active_turn_id` still matches before writing.

## Testing

- Unit: dispatcher (seq'd publishes, terminal events on success/failure),
  panel persister accumulator, store migration, transport-selection branch.
- Release (`release_integration`, Docker): deploy panel + NATS with sentinel
  credentials, start a turn and drop the SSE connection immediately. The
  agent turn fails at the LLM call (sentinel key) and publishes its terminal
  event to JetStream regardless — assert the panel's detached persister still
  writes exactly one assistant row (with `turn_id`), clears
  `active_turn_id`, and the resume endpoint then returns 204. Mid-stream
  replay itself is covered by unit tests (a live-LLM replay assertion would
  be racy: a failed turn can complete before the resume request lands).

## Example (definition of done)

New `examples/docker-panel-nats` — the docker-panel example plus
`transport: nats`.

## Out of scope

- Resumability on the HTTP transport (would require panel-side chunk
  persistence; deliberately excluded).
- Incremental offset-based resume (`Last-Event-ID` / `from` param).
- Streaming for `/v1/chat/completions` (still non-streaming).
- `deliver_message` push surface for the panel (this design enables it later
  via the same subscribe pattern, but does not implement it).
