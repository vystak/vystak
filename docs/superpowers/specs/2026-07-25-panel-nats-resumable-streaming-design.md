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

- **JetStream stream:** one per platform, name `vystak-streams`, subjects
  `vystak.{ns}.streams.>`, file storage, limits retention, `max_age` ≈ 1h.
  Provisioned lazily via idempotent `js.add_stream()` from whichever side
  touches it first (agent publisher or panel subscriber). The Docker/Azure
  NATS provisioning nodes must start the broker with JetStream enabled
  (`-js` + store dir on the existing volume).
- **Turn subjects:** `vystak.{ns}.streams.{conversation_id}.{turn_id}`.
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

New `_vystak/runtime/transport_dispatcher.py` implementing
`ServerDispatcherProtocol`; `app_factory.py` startup runs
`transport.serve(name, dispatcher)` when `VYSTAK_TRANSPORT_TYPE == "nats"`,
**replacing** `maybe_build_bridge()` / `NatsHttpBridge`. (They cannot coexist:
both would join the same queue group and split messages randomly.)

- `dispatch_a2a` — reuse the bridge's mechanism: POST the raw envelope to
  `http://localhost:{port}/a2a`, return the body. Existing NATS deployments
  see unchanged behavior.
- `dispatch_responses_create` / `dispatch_responses_get` — call the existing
  `openai/responses.py` handlers directly (fixes the currently-dead
  `responses/create` over NATS as a side effect).
- `dispatch_responses_create_detached` — new **optional** method on
  `ServerDispatcherProtocol` (vystak core): validate, ack, spawn the detached
  publishing task (drive `_stream_iterator`, wrap each event as `{seq, event}`,
  `js.publish()` to the turn subject; terminal event on completion or failure).
- `dispatch_a2a_stream` / `dispatch_responses_create_stream` — delegate to the
  same handlers over the existing inbox-reply routing in
  `NatsTransport._handle_inbound`, making the transport's client half honest.

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
- Release (`release_integration`, Docker): deploy panel + NATS, start a turn,
  drop the SSE connection mid-stream, reconnect via the resume endpoint,
  assert the full text arrives and exactly one assistant row is persisted.

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
