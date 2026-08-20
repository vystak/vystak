---
title: Durable Execution
sidebar_label: Durable Execution
---

# Durable Execution

A turn that survives a container restart. LangGraph's checkpointer is
SQLite by default (never in-memory), a separate turn journal tracks
in-flight work, and — for agents deployed behind the NATS transport — the
bridge re-drives any turn that was still running when the process died,
instead of silently dropping it.

**v1 scope: Docker + NATS only.** The checkpointer/journal durability
below applies to every Docker deployment. The re-drive, park/resume, and
panel-rewind mechanics — the parts that actually recover a turn after a
restart — exist only in the NATS transport's bridge. Over the HTTP
transport, a turn that was mid-flight when the agent container died is
simply lost, exactly as before this feature; the HTTP path never sees a
rewind. Azure isn't part of this feature at all — nothing here beyond the
checkpointer default is implemented for the Azure provider.

## What survives, and what doesn't

Two SQLite files live under `/data` in the agent's container:

- **`/data/sessions.db`** — the LangGraph checkpointer. Every graph step
  is a checkpoint; this is what lets a re-driven turn resume from its last
  committed step instead of from scratch.
- **`/data/turns.db`** — the turn journal, tracking one row per detached
  turn dispatched over NATS: `turn_id`, `thread_id`, `status`, `last_seq`,
  `attempts`. The bridge reads this on startup to find turns orphaned by
  the previous process's death.

What survives: everything committed to a checkpoint before the crash. What
doesn't: work in progress inside a single step at the exact moment of the
crash — on re-drive, that step re-runs from its last checkpoint boundary,
not from the instant of the crash.

## Path resolution

| File | Env override | Deployed default | Fallback (local dev/tests) |
|---|---|---|---|
| Checkpointer | `VYSTAK_SESSIONS_PATH` | `/data/sessions.db` | `<tempdir>/vystak-sessions.db` |
| Turn journal | `VYSTAK_TURNS_PATH` | `/data/turns.db` | `<tempdir>/vystak-turns.db` |

## Upgrading an existing deployment

Before this feature, an agent with no `sessions:` block got an in-memory
checkpointer — nothing durable. **Every agent is now durable by default.**

For an already-deployed agent, this matters:

- The Docker provider now always mounts a `vystak-agent-<name>-data`
  volume at `/data`, unless another declared dependency already claims
  that path.
- The `Agent` schema didn't change to add this, so **`vystak plan` shows
  no diff** on an existing deployment.
- **You must `vystak destroy` then `vystak apply`** to attach the volume —
  a plain re-`apply` won't recreate the running container, so the mount
  never gets added.

Once attached, the volume **survives `vystak destroy`** by design, same as
the Vault/Postgres/scheduler data volumes elsewhere in this stack. To
fully reset a durable agent's state:

```bash
docker volume rm vystak-agent-<name>-data
```

## Re-drive after a restart

Applies only to agents behind the NATS transport. On startup, the bridge:

1. Snapshots every `running` turn in the journal — by definition, these
   predate this process (nothing here could have written `running` before
   subscribing).
2. Waits for the agent's own `/healthz` to return 200 before touching any
   of them.
3. For each orphaned turn: looks up its checkpoint, publishes a
   `vystak.turn.rewind` event (telling consumers to discard everything
   after that boundary), then resumes it against the agent.
4. Caps retries at **3 attempts** — after that, the turn is marked
   `failed` and a synthetic terminal event is published so nothing waits
   forever.

## Park and resume — the approvals seam

A LangGraph node calling `interrupt()` parks the turn instead of failing
or completing: no terminal event, journal status `parked`. Two RPCs:

- `responses/turnStatus {turn_id}` — reports `running` / `parked` /
  `done` / `failed` / `unknown`.
- `responses/resumeDetached {turn_id, resume}` — resumes a parked turn.
  No rewind published — nothing was lost on a park.

Nothing ships an `interrupt()`-calling tool today; this is the foundation
a future human-in-the-loop approval step would build on.

## The panel: idle no longer means "done"

The panel's turn persister used to treat a gap in the event stream as "the
turn is over." Now, on every idle gap, it asks `responses/turnStatus`
instead of assuming — `running`/`parked` (or an unreachable agent) means
keep waiting; anything else concludes the turn. An **overall 15-minute
deadline** bounds this regardless of what `turnStatus` reports.

When a re-drive publishes a rewind, the browser gets a `reset` frame and a
replay of exactly the retained events — no duplicated tool calls or
replies from the pre-restart attempt.

## Try it

`examples/docker-panel-durable/` walks through dispatching a four-step
job, restarting the agent container mid-flight, and watching the panel
resume the turn instead of dropping it.

## Related

- [Transport](./transport) — the NATS bridge this feature builds on
- [Channels](../channels/panel) — the panel channel's rewind handling
- `docs/durable-execution.md` in the repo — full implementation reference
