# Durable / Checkpointed Execution — Design

**Date:** 2026-07-27
**Status:** Draft
**Follows:** `2026-07-25-panel-nats-resumable-streaming-design.md` (implemented)

## Problem

The resumable-streaming design decoupled the *delivery* of a turn from any
particular browser connection: the agent publishes events to JetStream, the
panel's process-owned persister consumes them, and multiple tabs can attach.
What it did not decouple is the *execution* of a turn from the agent process.

`NatsHttpBridge._run_detached` (`_vystak/runtime/nats_bridge.py:357`) holds the
entire turn in memory:

- `seq = 0` is a local variable in the coroutine.
- Nothing anywhere on the agent side records `{turn_id, stream_subject,
  request}` — the only durable trace of an in-flight turn is
  `conversations.active_turn_id` in the *panel's* database.
- The turn runs as a bare `asyncio.Task` tracked in `self._inflight`.

So if the agent container dies mid-turn, the turn is lost. The panel's startup
rescan re-spawns a persister, replays the subject from seq 0, receives nothing
further, and after the ~120s idle timeout writes an error-annotated assistant
row. Every completed tool call and every token already paid for is discarded.

This is wasteful rather than merely inconvenient: LangGraph's checkpointer
already commits graph state at every node boundary, so the expensive work
*is* durable. What is missing is (a) the bookkeeping to find that thread again
after a restart, (b) the machinery to continue publishing into its stream, and
(c) a way for a turn to suspend deliberately rather than only by crashing.

A second, quieter problem: `build_checkpointer` (`_vystak/runtime/store.py:29`)
returns `MemorySaver` when the agent declares no `sessions:`. Durable execution
on top of an in-memory checkpointer is a contradiction, and the failure is
silent — the agent looks fine until it restarts.

## Goal

An in-flight turn survives the agent container being restarted or replaced: it
resumes from the last committed checkpoint, continues publishing into the same
turn stream, and the assistant reply eventually lands exactly once. A turn can
also *park* — suspend at a well-defined point, holding no process state — and
be resumed later by an explicit RPC.

### Non-goals

Detached execution is structurally NATS-only (it exists only in the NATS
bridge; on HTTP the panel streams over httpx and the turn dies with the
connection). NATS-on-Azure was already ruled out by the prior design because
there is no Azure NATS provisioning node. **v1 is therefore Docker + NATS
only**, with the same graceful-degradation posture as its predecessor: on HTTP
the behavior is exactly what it is today.

Human-in-the-loop approvals (todos item 1) are *not* built here. This design
lands the `interrupt()` / park seam that approvals need, and stops there.

## Design

### 1. Durable checkpointer by default

`build_checkpointer` drops `MemorySaver` entirely:

| `sessions:` | checkpointer |
|---|---|
| absent | **new:** `AsyncSqliteSaver` at `/data/sessions.db` |
| `sqlite` | `AsyncSqliteSaver` at the declared path (unchanged) |
| `postgres` | `AsyncPostgresSaver` (unchanged) |

SQLite always works — worst case (`/data` not mounted, as on Azure) it lands on
the container filesystem and survives a process restart but not container
replacement. That degradation is acceptable and is strictly better than today's
in-memory behavior. The path is overridable via `VYSTAK_SESSIONS_PATH`, mirroring
the `VYSTAK_TRANSPORT_TYPE` precedent, so no new `vystak` core schema field is
required — important, because agent images pip-install bare `vystak` from PyPI
and cannot see unpublished core changes.

**Provider change:** `vystak-provider-docker`'s agent node mounts `/data` only
when `sessions:` is declared (`nodes/agent.py:250`). It must now always
provision and mount a per-agent data volume (`vystak-agent-<name>-data`) when
the agent declares no sessions service of its own.

**Upgrade note.** The `Agent` schema is unchanged, so `AgentHashTree` produces
the same hash and `vystak plan` shows no diff — an existing deployment will not
pick up the new volume until it is recreated. This must be documented: a
`vystak destroy && vystak apply` is required to gain durability on an
already-deployed agent.

### 2. Turn journal (agent-side)

A `detached_turns` table, following the `heartbeat_sessions.py` sidecar-store
precedent (same shape: an ABC, an in-memory impl for tests, a SQLite impl):

```sql
CREATE TABLE IF NOT EXISTS detached_turns (
    turn_id        TEXT PRIMARY KEY,
    stream_subject TEXT NOT NULL,
    thread_id      TEXT,               -- learned from response.created
    request_json   TEXT NOT NULL,
    status         TEXT NOT NULL,      -- running | parked | done | failed
    last_seq       INTEGER NOT NULL DEFAULT -1,   -- high-water published
    boundary_seq   INTEGER NOT NULL DEFAULT -1,   -- last committed checkpoint
    attempts       INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

A companion table maps checkpoint identity to stream position:

```sql
CREATE TABLE IF NOT EXISTS turn_boundaries (
    turn_id       TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    PRIMARY KEY (turn_id, checkpoint_id)
);
```

`boundary_seq` alone is not safe to rewind to. `on_chain_end` fires when the
node function returns, which is not necessarily after the superstep's
checkpoint write has landed. A crash in that gap means LangGraph resumes from
an *earlier* checkpoint than `boundary_seq` claims, so the rewind
under-truncates and consumers keep stale events that the resumed run then
re-emits. Recording `(checkpoint_id → seq)` lets the re-drive ask LangGraph
which checkpoint the thread is *actually* resuming from and rewind to that
seq. `boundary_seq` is retained as the fallback when the resumed checkpoint id
has no recorded seq.

**To verify during planning:** the precise ordering of `on_chain_end` versus
the checkpoint write in the pinned LangGraph version. If the write provably
precedes the event, `turn_boundaries` collapses back into the single
`boundary_seq` column and this table is dropped.

The journal is **always SQLite at `/data/turns.db`**, independent of the
checkpointer engine. Keeping it out of the Postgres path avoids a second store
backend for v1; the trade-off is that the journal is per-container, which is
correct under Docker's single-replica model and is called out as a constraint
if agent replicas ever land.

`thread_id` is not known when the turn is dispatched — `_stream_iterator`
derives it from `previous_response_id` or generates one
(`openai/responses.py:53`). The bridge already proxies the `response.created`
event, which carries `response.id`; it writes that into the journal row on
sight. No new plumbing.

### 3. Checkpoint boundaries in the stream

The bridge is a proxy — it sees Responses SSE events, not LangGraph node
transitions, so it cannot infer where a checkpoint committed. `_stream_iterator`
already consumes `astream_events(version="v2")`, where node completions surface
as `on_chain_end` with `ev["name"]` in `("agent", "tools")`. At each such event
it emits an internal marker:

```json
{"type": "vystak.checkpoint"}
```

The bridge **consumes and does not republish** this marker: on sight it records
`boundary_seq = last_seq` in the journal. JetStream therefore carries no
internal events. Every other consumer of `/v1/responses` (the panel's HTTP
path, `vystak-chat`) ignores unknown event types already —
`translate_responses_event` returns `None` for anything unrecognized — so this
is additive and safe.

### 4. Resume endpoint

`_stream_iterator` starts the graph with `{"messages": messages}`. Continuing an
interrupted thread means invoking the same graph with `None` (or
`Command(resume=...)`) on the existing `thread_id`, which `POST /v1/responses`
cannot express — it always starts a new response.

Add `POST /v1/_vystak/resume`, body `{thread_id, resume?}`, returning the same
Responses SSE stream. Internally it is `_stream_iterator` with the graph input
swapped for `None` or `Command(resume=resume)`. It is an internal surface
(underscored path, not advertised on the agent card).

### 5. Re-drive on startup

At bridge startup, after the NATS connection is established, scan the journal
for `status='running'` rows and re-drive each:

1. If `attempts >= 3`, publish a synthesized `response.failed` terminal event,
   mark `failed`, stop. This is the crash-loop backstop — without it a turn
   that reliably kills the container retries forever.
2. Increment `attempts`.
3. Publish a rewind control event at the next seq:
   `{"seq": last_seq + 1, "event": {"type": "vystak.turn.rewind",
   "to_seq": boundary_seq}}`.
4. `POST /v1/_vystak/resume` with the journal's `thread_id`, and continue
   publishing events from `last_seq + 2` onward, updating `last_seq` and
   `boundary_seq` exactly as the first attempt did.

Rows with `status='parked'` are deliberately skipped (see §8).

The rewind exists because LangGraph re-executes the *interrupted* node on
resume. If the crash landed mid-LLM-stream, that model node re-runs and
re-emits text deltas that consumers already saw. Rewind tells every consumer to
discard everything after the last committed boundary before accepting the
continuation. Completed tool nodes are *not* re-run — which is the whole reason
to resume from a checkpoint rather than re-running the turn.

### 6. Consumer changes

Three places fold the event stream and therefore must honor rewind:

- **`TurnAccumulator` (`turn_stream.py:71`)** — retain raw `(seq, event)` pairs
  alongside the fold. `rewind(to_seq)` drops pairs above `to_seq` and re-folds
  from scratch. Turns are small and the class already rebuilds wholesale on
  replay-from-0, so the cost is negligible and the logic stays obvious.
- **Panel SSE proxy (`routes_messages.py`)** — on rewind, emit a
  `{"type": "reset"}` browser frame, then re-emit the retained prefix as
  ordinary `delta` / `tool_call` / `tool_result` frames before resuming live
  forwarding.
- **`panelStreamToUIChunks` (Next.js)** — handle `reset` by clearing the
  in-flight assistant message. This is the same state the adapter reaches on a
  fresh resume attach, so it is a reuse of existing behavior rather than a new
  rendering path.

### 7. The panel's idle timeout must stop concluding turns

This is the change without which the rest of the design does not work.

`stream_turn_events` raises `TurnStreamIdle` after 120s of silence
(`vystak_transport_nats/streams.py:71`), and `run_turn_persister` treats it as
the turn concluding: `errored = True`, persist a partial assistant row, clear
`active_turn_id`. A container restart plus JetStream reconnect plus journal
rescan plus re-drive will routinely exceed 120s — for this feature that is the
*normal* path, not an edge. Left as-is, the panel writes an error row and
clears `active_turn_id` before the agent finishes resuming, its own startup
rescan then has nothing to re-spawn, and the agent republishes into a subject
with no consumer. The reply is lost and the error row stands.

Silence must therefore mean "still working" rather than "concluded". The panel
cannot read the agent's journal (it is agent-side SQLite), so it asks:

- **New RPC `responses/turnStatus {turn_id}`** — the bridge reads its journal
  and replies `running | parked | done | failed | unknown`.
- On `TurnStreamIdle` the persister queries it. `running` or `parked` → keep
  waiting and re-enter the consume loop. `done` or `failed` → conclude as
  today. `unknown` → conclude (the agent has no record; the turn predates a
  volume wipe or was never journaled).
- **RPC failure is not a conclusion.** During a restart the agent is
  unreachable, which is exactly when the answer matters; a failed query keeps
  waiting.
- A bounded overall deadline (default 15 min, from first dispatch) is the
  backstop so a turn cannot wait forever. On expiry the persister concludes as
  errored, as today.

### 8. Park / interrupt seam

A tool calling LangGraph's `interrupt()` suspends the graph; the checkpointer
holds the pending interrupt and the detached runner exits, holding no process
state — this is the "parks at zero compute" property. The bridge marks the
journal row `parked` and publishes no terminal event, so the panel's persister
keeps waiting (its idle timeout is the failure path if a park is never
resumed).

A new RPC, `responses/resumeDetached {turn_id, resume}`, looks the row up,
flips it to `running`, and drives `POST /v1/_vystak/resume` with
`Command(resume=resume)` — from there it is identical to §5 without the rewind
(no work was lost, so there is nothing to discard).

No shipped tool calls `interrupt()` in v1. The seam is exercised by a test-only
interrupting tool. Approvals (todos item 1) become: a `needs_approval` flag that
wraps a tool in `interrupt()`, plus panel UI to call `responses/resumeDetached`.

## Failure modes

- **Crash before the journal row is written** → identical to today: the panel
  times out and writes an error row. The window is one INSERT wide; the row is
  written *before* the ack is published.
- **Crash loop** → capped at 3 attempts, then a synthesized `response.failed`.
- **Rewind arrives for a consumer that already persisted** → the persister
  writes only on a terminal event, and `get_message_by_turn_id` already guards
  double-insert, so a late rewind cannot produce a second row.
- **JetStream retention (~1h) expires before resume** → replay from 0 is
  incomplete; the persister writes what it has. Accepted, same as the prior
  design's broker-restart edge.
- **Parked turn never resumed** → `turnStatus` reports `parked`, so the
  persister waits until the 15-minute overall deadline and then concludes as
  errored. The journal row stays `parked` and is never auto-resumed. v1 accepts
  the mismatch; a park-aware panel state is follow-up work.
- **Agent unreachable for longer than the overall deadline** → the persister
  concludes as errored even though the agent may still resume later and
  republish. Bounding the wait is a deliberate trade against an unbounded
  pending turn.

## Testing

Unit:
- Journal store: CRUD, status transitions, attempt capping, in-memory impl parity.
- `vystak.checkpoint` emission from `astream_events` for `agent`/`tools` nodes.
- `TurnAccumulator.rewind` — fold correctness after truncation.
- Startup rescan: skips `parked`, caps at 3 attempts, publishes rewind at the
  right seq.
- Resume endpoint: passes `None` vs `Command(resume=...)` correctly.
- `build_checkpointer`: no `MemorySaver` on any path; default path resolution.
  **`/data` does not exist in unit-test or dev environments**, and
  `AsyncSqliteSaver.from_conn_string("/data/sessions.db")` fails at lifespan
  startup when it is absent — this would break `just test-python`, one of the
  four live CI gates. Path resolution needs an explicit fallback chain
  (`VYSTAK_SESSIONS_PATH` → `/data/sessions.db` when the directory exists and
  is writable → a local path), covered by a test per branch.
- `responses/turnStatus`: every status mapping, plus the persister's behavior
  on RPC failure (keeps waiting) and on overall-deadline expiry (concludes).

Release:
- `release_integration` (sentinel credentials, no live LLM): dispatch a
  detached turn; it fails fast at the LLM call. Assert the journal row reaches
  `failed`, the terminal event is published, and the rescan does not re-drive a
  completed turn.
- `release_integration` (deterministic restart, no live LLM): the
  `release_live_chat` cell below is the only end-to-end proof, and it
  auto-skips on sentinel keys and never runs in GitHub Actions — so the
  plumbing needs a gate that always runs locally. Dispatch a turn, `docker
  restart` the agent, and assert the mechanical facts that hold regardless of
  LLM behavior: the journal row survives on the volume, the rescan logs a
  re-drive, `attempts` increments, a rewind event is published, and the panel
  does not conclude the turn at 120s.
- `release_live_chat` (real key): the actual proof. An agent with a
  deliberately slow tool; start a turn, `docker restart` the agent mid-tool,
  assert the assistant row eventually lands **exactly once** with its
  `turn_id`, `active_turn_id` is cleared, and the tool ran only once. A live
  LLM is unavoidable here — with sentinel credentials there is no mid-turn to
  interrupt.

## Example (definition of done)

`examples/docker-panel-durable` — `examples/docker-panel-nats` (which already
exists, from the prior design) plus a deliberately slow multi-step tool, with a
README walking through `docker restart vystak-<agent>` mid-turn and observing
the reply still land.

## Out of scope

- Durable execution on the HTTP transport.
- Azure (no NATS provisioning node).
- Approvals / `needs_approval` (todos item 1) — seam only.
- Postgres-backed turn journal.
- Multi-replica agents (the journal is per-container).
- Park-aware panel UI state (a parked turn still hits the idle timeout).
