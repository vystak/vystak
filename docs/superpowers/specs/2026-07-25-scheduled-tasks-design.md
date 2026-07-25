# Scheduled Tasks — Design

Date: 2026-07-25
Status: approved

## Summary

Generalize the heartbeat feature into **scheduled tasks**: declarative
per-agent schedules in `vystak.yaml`, plus runtime creation by operators
(CLI/REST) and by agents themselves (a `schedule_task` tool). A scheduled
task is always declarative in shape — a schedule plus a prompt aimed at an
agent, with optional channel delivery. No arbitrary scheduled code.

Docker provider only in this iteration; Azure is a follow-up spec.

## Motivation

- Heartbeat covers "cron + prompt" but is fixed at deploy time; there is no
  way to add, change, or cancel a schedule without redeploying.
- The agent-tool use case ("remind me Monday 9am", "check this every hour")
  requires one-shot tasks and runtime creation, neither of which heartbeat
  supports.
- Vercel's eve validated schedules as a first-class agent-framework concept;
  Vystak's version stays declarative to match the no-codegen principle.

## Requirements (settled in brainstorming)

1. Creation paths: declarative YAML, operator CLI/REST, agent tool — all
   writing one store through one API.
2. Task action: prompt an agent (heartbeat's model). No direct tool calls,
   no user code files.
3. Schedule shapes: `cron`, `at` (one-shot), `every` (interval).
4. Heartbeat is generalized, not duplicated: `heartbeat:` remains schema
   sugar compiling to a scheduled task with the ack contract.
5. Persistence: SQLite on a named volume by default; Postgres when the
   project declares it (sessions-postgres pattern).
6. Missed fires: recurring tasks skip (resume from now); one-shots fire
   late within a 24h grace window, else marked `missed`.
7. Scope: vystak-provider-docker. Azure follow-up.

## Schema

New model `ScheduledTask` in `vystak/schema/schedule.py`; `Agent` gains
`schedules: list[ScheduledTask]`.

```yaml
agents:
  - name: ops-bot
    schedules:
      - name: monday-digest            # unique per agent
        cron: "0 9 * * 1"              # exactly one of: cron | at | every
        timezone: America/New_York
        prompt: "Summarize last week's deploys."
        target_channel: chat-main.channels.dev   # optional
        target_thread: null
        isolated_session: true
        skip_when_busy: true
        ack_max_chars: null            # set to enable HEARTBEAT_OK-style suppression
        model: null                    # per-task model override from the agent pool
        enabled: true
```

Field semantics:

- `name` — identity for reconciliation; unique per agent; required.
- Shape fields — exactly one of `cron` (5-field, croniter-validated),
  `at` (ISO-8601 timestamp; task auto-completes after firing), `every`
  (duration string: `"30s"`, `"20m"`, `"2h"`, `"1d"`; first fire one
  interval after activation). Model validator rejects zero or 2+ shapes.
- `timezone` — IANA name, default UTC. Applies to `cron` and `at`
  (when `at` has no explicit offset).
- `target_channel` — optional, unlike heartbeat. Unset → the fire runs;
  the result is visible only in traces/logs. Set → validated at plan time
  (channel exists and routes to the agent), same as heartbeat validation.
- `ack_max_chars` — `null` disables ack handling. When set, replies
  containing `HEARTBEAT_OK` within that length are suppressed (exact
  `is_heartbeat_ok` semantics).
- `isolated_session`, `skip_when_busy`, `model`, `enabled` — same meaning
  as on `Heartbeat`.

### Heartbeat compilation

`Heartbeat` stays in the schema, unchanged for users. Internally, the
scheduler input compiles `heartbeat:` to a `ScheduledTask` named
`heartbeat` with `cron=schedule`, `ack_max_chars=hb.ack_max_chars`, the
HEARTBEAT.md default prompt when `prompt` is null, and `target_channel`
required (heartbeat keeps its stricter contract). An agent may not also
declare an explicit schedule named `heartbeat`.

### Hashing

Declarative `schedules` join the agent hash tree (`vystak/hash/tree.py`)
exactly as heartbeat does today, so `vystak plan` detects changes.
Runtime-created tasks are data, not definition — they never contribute to
the hash and never cause drift.

## Scheduler service

`vystak-heartbeat` (package name retained this iteration) generalizes into
the platform scheduler.

### Store

New `ScheduleStore` with two backends, following the panel-store pattern:

- **SQLite** (default) at a fixed path on the `vystak-scheduler-data`
  named volume, with versioned in-place migrations (`SCHEMA_VERSION`).
- **Postgres** when the project declares the Postgres resource.

One table (`scheduled_tasks`), columns approximately:

```
id TEXT PK, agent_canonical TEXT, name TEXT,
source TEXT CHECK (declarative|runtime),
cron TEXT NULL, at_ts TEXT NULL, every TEXT NULL, timezone TEXT,
prompt TEXT NULL, target_channel TEXT NULL, target_thread TEXT NULL,
isolated_session INT, skip_when_busy INT, ack_max_chars INT NULL,
model TEXT NULL, enabled INT, created_by TEXT,
status TEXT CHECK (active|completed|missed|cancelled),
next_fire_at TEXT NULL, last_fire_at TEXT NULL, last_result TEXT NULL,
UNIQUE (agent_canonical, name)
```

`next_fire_at` is persisted so restart recovery never recomputes from
history.

### Fire loop

The N-per-heartbeat asyncio loops are replaced by one loop:

1. Sleep until `min(next_fire_at)` across active enabled tasks (with a
   cap so newly created tasks are picked up promptly; a store-change
   event wakes the loop on API writes).
2. Fire due tasks: same path as heartbeat v2 — Transport `send_task` to
   the agent, then ChannelDelivery if `target_channel` is set, applying
   the ack contract when `ack_max_chars` is set.
3. Recompute `next_fire_at` (cron/every) or mark `completed` (one-shot).
   Record `last_fire_at` / `last_result`.

`skip_when_busy` remains per-task (skip a fire while the previous fire of
the same task is in flight).

### Reconciliation on `vystak apply`

- Declarative tasks upsert by `(agent_canonical, name)` with
  `source=declarative`.
- Declarative tasks in the store but absent from the definition are
  deleted.
- `source=runtime` tasks are never touched by apply — they survive
  redeploys.
- A runtime task may not take a name colliding with a declarative task on
  the same agent (API rejects with 409).

### Missed fires

On startup:

- Recurring (`cron`/`every`): recompute `next_fire_at` from now; missed
  fires are skipped (current heartbeat behavior, documented as such).
- One-shot (`at`): if the timestamp passed while down and is within a
  **24h grace window**, fire immediately; older → status `missed`
  (surfaced by CLI/API, never silently dropped).

## REST API

FastAPI app on the scheduler container, internal platform network only,
unauthenticated this iteration (consistent with agent↔channel traffic; a
shared-secret header can be added later without breaking clients).

- `GET  /tasks?agent=&source=&status=` — list
- `POST /tasks` — create runtime task (`source` forced to `runtime`)
- `GET  /tasks/{id}` — detail incl. `next_fire_at`, `last_result`
- `PATCH /tasks/{id}` — enable/disable/edit; **runtime tasks only** —
  declarative tasks return 409 with a "change the YAML" message
- `DELETE /tasks/{id}` — cancel; runtime tasks only (same 409 rule)
- `GET  /healthz`

## CLI

`vystak schedules list|add|show|pause|resume|remove` as a new command
module in `vystak_cli/commands/`, resolving the scheduler endpoint the way
`vystak logs`/`status` resolve platform resources.

## Agent tool

`schedule_task` ships in the langchain template (`_vystak/runtime/`),
exposed only when `VYSTAK_SCHEDULER_URL` is injected (deployment has a
scheduler). Operations: `create`, `list`, `cancel` — **scoped to the
calling agent**; an agent cannot see or modify another agent's tasks.

When invoked from a channel conversation, `target_channel`/`target_thread`
default to the originating thread, so "remind me Monday 9am" delivers back
where it was asked. Agent identity and scheduler URL come from injected
env vars.

## Docker provider wiring

- `nodes/heartbeat.py` generalizes to the scheduler node. Spawn condition:
  any agent declares `heartbeat` **or** `schedules`, **or** the platform
  sets `scheduler: enabled` (runtime-only use — agents may create tasks
  even when none are declared).
- Adds: `vystak-scheduler-data` volume, internal HTTP port, store-backend
  env (SQLite path or Postgres DSN).
- Agent containers get `VYSTAK_SCHEDULER_URL` (+ agent canonical name)
  injected.
- The scheduler image's emitted `REQUIREMENTS` string gains
  `fastapi`/`uvicorn` **in the same commit** as the dependency (repo rule:
  channel/service containers install the emitted REQUIREMENTS string, not
  pyproject).

## Backward compatibility

Existing `heartbeat:` configs deploy unchanged: compiled task preserves the
ack contract, `HEARTBEAT_OK` suppression, HEARTBEAT.md default prompt,
delivery behavior. `test_heartbeat_v2.py` must stay green.

## Testing

Unit:
- Schema: exactly-one-of shape validation, duration parsing, timezone
  validation, heartbeat→task compilation.
- Store: CRUD, migrations, reconciliation matrix (declarative
  add/change/remove × runtime survival), name-collision rejection.
- Fire loop: next-fire computation for all three shapes, one-shot
  completion, skip_when_busy, missed-fire/grace logic.
- API: handler contract incl. 409s on declarative mutation.

Release (Docker, `release_integration`): new
`vystak-provider-docker/tests/release/test_schedules.py` —
1. deploy an agent with a declarative schedule; verify it fires;
2. create a one-shot via REST; verify it fires and completes;
3. restart the scheduler container; verify runtime tasks survive.

## Example

`examples/docker-schedules/`: agent with a declarative digest schedule +
README walking through `vystak schedules add` and the agent-tool
"remind me" flow. Part of definition of done per repo convention.

## Docs

New `docs/schedules.md`; `docs/heartbeat.md` remains and links to it as
the general mechanism.

## Out of scope (follow-ups)

- Azure provider wiring (separate spec, like other features).
- Panel "Schedules" tab (the REST API is shaped to support it).
- API authentication (shared-secret header).
- Catch-up/replay semantics for recurring tasks.
