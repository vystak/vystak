# Durable execution

A turn that survives a container restart. LangGraph's checkpointer is
SQLite by default (never in-memory), a separate turn journal tracks
in-flight work, and — for agents deployed behind the NATS transport — the
bridge re-drives any turn that was still running when the process died,
instead of silently dropping it.

**v1 scope: Docker + NATS only.** The checkpointer/journal durability
described below applies to every Docker deployment. The re-drive,
park/resume, and panel-rewind mechanics — the parts that actually recover
a turn after a restart — exist only in the NATS transport's bridge
(`_vystak/runtime/nats_bridge.py`). Over the HTTP transport, a turn that
was mid-flight when the agent container died is simply lost, exactly as
before this feature; the HTTP path never sees a rewind. Azure is not part
of this feature at all — nothing here (checkpointer default aside) is
implemented for `vystak-provider-azure`; it neither rejects durable turns
nor supports them, the mechanism just isn't there.

## What survives a restart, and what doesn't

Two SQLite files live under `/data` in the agent's container:

- **`/data/sessions.db`** — the LangGraph checkpointer. Every graph step
  (message, tool call, tool result) is a checkpoint. Survives restarts by
  construction; this is what lets a re-driven turn resume from its last
  committed step instead of from scratch.
- **`/data/turns.db`** — the turn journal (`SqliteTurnJournal`), tracking
  one row per detached turn dispatched over NATS: `turn_id`, `thread_id`,
  `status` (`running` / `parked` / `done` / `failed`), `last_seq`,
  `attempts`. This is what the bridge reads on startup to find turns that
  were orphaned by the previous process's death.

What survives: everything committed to a checkpoint before the crash —
completed tool calls, prior assistant turns, session state. What does
**not** survive: work in progress inside a single ungraphed step at the
moment of the crash (e.g. a tool call that was mid-execution, not yet
recorded) — on re-drive that step re-runs from its last checkpoint
boundary, not from the exact instant of the crash. `examples/docker-panel-durable`'s
README documents this concretely: a restart mid-`slow_step` re-drives that
step from its beginning, not mid-sleep — the step's own side effect (a
completion-log write) only happens once the step actually finishes, so a
re-run is safe to observe even though the tool function itself executes
twice.

## Path resolution

Both files follow the same three-link fallback chain, resolved independently:

| File | Env override | Deployed default | Fallback (no `/data`, e.g. local dev/unit tests) |
|---|---|---|---|
| Checkpointer | `VYSTAK_SESSIONS_PATH` | `/data/sessions.db` | `<tempdir>/vystak-sessions.db` |
| Turn journal | `VYSTAK_TURNS_PATH` | `/data/turns.db` | `<tempdir>/vystak-turns.db` |

`/data` is used when it exists and is writable — i.e. the deployed
container, where the platform provider mounted a volume there. An agent
with a declared `sessions:` block still uses its own configured path for
the checkpointer; the turn journal always resolves independently via
`resolve_turns_path()`, regardless of what the checkpointer is doing.

## The checkpointer default changed: migration note

Before this feature, an agent with no `sessions:` block got an in-memory
(`MemorySaver`) checkpointer — nothing durable, nothing to re-drive.
**Every agent is now durable by default**: `build_checkpointer()` always
returns a SQLite-backed checkpointer, whether or not `sessions:` is
declared.

This has a real consequence for **existing Docker deployments**:

- `vystak-provider-docker`'s `DockerAgentNode` now always mounts a
  `vystak-agent-<name>-data` volume at `/data`, **unless** some other
  declared dependency (a `sessions:` sqlite store, or a sqlite `memory:`/
  service dependency) already claims the `/data` bind path — in which case
  that volume is reused and no second one is created.
- The `Agent` schema itself did not change to add this — there's no new
  field, so **`vystak plan` shows no diff** for an already-deployed agent.
  The volume only gets attached when the agent's container is actually
  recreated.
- **An existing deployment must be destroyed and re-applied** (`vystak
  destroy` then `vystak apply`) to pick up the data volume and start
  writing a durable checkpointer/journal. Re-running `vystak apply` alone,
  with no other change to the agent, will not attach it — Docker doesn't
  let you add a volume mount to a running container in place, and nothing
  in the deploy identity hash changed to trigger a recreate.

Once attached, `vystak-agent-<name>-data` (like every other data volume in
this stack — Vault, Postgres, the scheduler's store) **survives `vystak
destroy` by design**. A `destroy` + `apply` cycle with the same agent name
resumes against the prior checkpointer/journal state rather than starting
clean. If you need a full reset (e.g. wiping stale sessions or a corrupted
journal), remove the volume by hand:

```bash
docker volume rm vystak-agent-<name>-data
```

## Re-drive: what happens when the agent container restarts

This only applies to agents behind the NATS transport (`NatsHttpBridge`,
`_vystak/runtime/nats_bridge.py`).

1. On startup, before subscribing to NATS, the bridge takes a snapshot of
   every turn the journal shows as `running` — these are, by definition,
   leftovers from a *previous* process (nothing in the current process
   could have written a `running` row before it has subscribed to
   anything). This snapshot is what actually gets swept; a turn created
   after this process starts handling live traffic is never touched by
   the sweep, even if it's also `running`.
2. The sweep itself doesn't run immediately — it waits for the agent's own
   `GET /healthz` to return 200 (polled with backoff, up to 30s) before
   touching any orphaned turn. Re-driving against a not-yet-ready local
   server would just fail every attempt without making progress.
3. For each orphaned turn, the bridge asks the agent for its current
   checkpoint (`GET /v1/_vystak/checkpoint?thread_id=...`), publishes a
   `vystak.turn.rewind` event (telling any consumer replaying the stream —
   the panel included — to discard everything after that checkpoint's
   boundary seq), then resumes the turn against `POST
   /v1/_vystak/resume` from that checkpoint.
4. Each re-drive attempt increments the journal row's `attempts` counter.
   **After 3 attempts** (`MAX_REDRIVE_ATTEMPTS = 3`), the turn is given up
   on: it's marked `failed` and a synthetic `response.failed` event is
   published so any waiting consumer still gets a terminal event instead
   of hanging forever.

A turn that crashed before it ever got a `thread_id` (i.e. before
`response.created` was ever emitted) can't be resumed at all — there's
nothing to check a checkpoint against — so it's failed immediately on the
first sweep, with no rewind published.

## Park and resume: the seam for future approvals

A LangGraph node that calls `interrupt()` doesn't fail and doesn't
complete — the turn **parks**: no terminal SSE event is published, and the
journal row's status becomes `parked` (distinct from `running`, so it is
never picked up by the crash re-drive sweep as if it were an ordinary
in-flight turn).

Two RPCs, both served by the bridge:

- **`responses/turnStatus {turn_id}`** — reports a turn's current status
  (`running` / `parked` / `done` / `failed` / `unknown`). This is what the
  panel's persister uses (see below) to tell "still working" apart from
  "actually finished."
- **`responses/resumeDetached {turn_id, resume}`** — resumes a parked turn,
  passing `resume` through to LangGraph's `Command(resume=...)`. No
  rewind is published on this path — nothing was lost when the turn
  parked, so nothing needs to be discarded on the way back in.

Nothing in this codebase calls `interrupt()` today; this mechanism exists
as the seam a future human-in-the-loop approval step (e.g. "confirm before
running this tool") would build on — pause the graph, surface the
pending state to a human, resume with their answer via
`resumeDetached`.

## The panel: idle no longer means "done"

Before this feature, the panel's turn persister treated a gap in the
NATS event stream (`TurnStreamIdle`, a 120s no-message timeout on a
single read) as "the turn is over" and concluded it — wrongly, for a
long-running tool call or a re-drive in progress.

Now, on every idle gap, the persister asks the bridge via
`responses/turnStatus` instead of assuming:

- `running` or `parked` → keep waiting, re-attach to the stream.
- the RPC call itself fails (agent unreachable) → also keep waiting — an
  unreachable agent is exactly the moment a real answer matters most, not
  a moment to give up.
- anything else (`done`, `failed`, `unknown`) → conclude the turn.

This can't loop forever: there's an **overall turn deadline of 15
minutes** (`DEFAULT_TURN_DEADLINE_S = 900.0`), checked each time the idle
gap fires. If a turn is still not concluded after 15 minutes of wall
clock, the persister gives up and concludes it as errored — independent
of what `turnStatus` says.

When a re-drive publishes a `vystak.turn.rewind`, the panel's SSE proxy
discards its buffered events after the rewind's boundary seq and sends
the browser a `reset` frame, followed by a replay of exactly the retained
(committed) events. The browser clears its rendered transcript and
rebuilds only the committed prefix — no duplicated tool calls or replies
from the pre-restart attempt.

## Try it

`examples/docker-panel-durable/` is a complete walkthrough: a single agent
with a four-step tool (each step sleeps 20s), deployed with the panel
channel over NATS. Its README walks through dispatching the job,
restarting the agent container mid-flight (`docker restart`), and
observing in the browser that the turn resumes rather than silently
dropping, with the transcript resetting to the committed prefix and no
duplicated step results.

## Related

- [`examples/docker-panel-durable/`](../examples/docker-panel-durable/) — the restart walkthrough.
- [`docs/schedules.md`](schedules.md) / [`docs/heartbeat.md`](heartbeat.md) — the other always-on background mechanisms in this stack, for comparison.
- `packages/python/vystak-provider-docker/tests/release/test_durable_turns.py` — the release-tier tests (`release_integration` for a deterministic restart/re-drive cell, `release_live_chat` for a real-LLM round trip proving resume-not-rerun).
