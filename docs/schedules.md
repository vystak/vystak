# Scheduled tasks

A scheduled task fires a prompt at an agent on a schedule — a cron
expression, a one-shot timestamp, or a recurring interval — and optionally
delivers the reply into a channel thread. It generalizes `heartbeat:`
(see [`docs/heartbeat.md`](heartbeat.md)): a declarative `heartbeat:` block
compiles internally into a scheduled task named `"heartbeat"` with a
stricter, always-on delivery contract. Everything below applies to both,
except where noted.

Unlike heartbeat, scheduled tasks can also be created and cancelled at
**runtime** — by an operator via the CLI/REST API, or by the agent itself
via a tool — without editing `vystak.yaml` or redeploying.

## Quick start

```yaml
agents:
  - name: ops-bot
    framework: langchain-python
    default_model: claude
    platform: local
    schedules:
      - name: monday-digest        # unique per agent; reconciliation identity
        cron: "0 9 * * 1"          # exactly one of: cron | at | every
        timezone: America/New_York
        prompt: "Summarize last week's deploys and any outstanding alerts."
        target_channel: chat-main.channels.dev   # optional; null → log only
        target_thread: digest-room

channels:
  - name: chat-main
    type: chat
    platform: local
    agents: [ops-bot]
```

Declaring `schedules:` (or `heartbeat:`) on any agent auto-provisions the
`vystak-heartbeat` container — the same one that also hosts heartbeat — as
the platform's scheduler. No extra platform config is required.

See the full example: [`examples/docker-schedules/`](../examples/docker-schedules/).

## Configuration reference

`ScheduledTask` fields (`vystak.schema.schedule.ScheduledTask`):

| Field | Type | Default | Notes |
|---|---|---|---|
| `name` | string | required | Unique per agent. Reconciliation identity for `vystak apply`. The literal name `"heartbeat"` is reserved (rejected at schema load) — it's what a declarative `heartbeat:` block compiles to. |
| `cron` | string \| null | `null` | 5-field cron expression. Exactly one of `cron`/`at`/`every` must be set. |
| `at` | datetime \| null | `null` | One-shot ISO-8601 fire time. The task's `status` becomes `completed` once it fires. |
| `every` | string \| null | `null` | Interval duration: `"30s"`, `"20m"`, `"2h"`, `"1d"`. First fire is one interval after the task becomes active. |
| `timezone` | string | `"UTC"` | IANA name. Applies to `cron` evaluation and to a timezone-naive `at`. Validated at schema load. |
| `prompt` | string \| null | `null` | Prompt sent to the agent on fire. `null` → `"Scheduled task '<name>' fired."` (or the heartbeat default prompt, for the task named `"heartbeat"`). |
| `target_channel` | string \| null | `null` | Channel `canonical_name` for result delivery. `null` → the fire still happens, but the result is visible only in logs/traces — nothing is delivered. Validated at plan time (channel exists and routes the agent) when set. |
| `target_thread` | string \| null | `null` | Delivery thread/scope id. **Delivery requires both `target_channel` and `target_thread` to be set** — if either is null, the agent still fires but nothing is posted anywhere. |
| `isolated_session` | bool | `true` | `true` → each fire uses a synthetic session id, invisible in user-facing history. `false` → the fire's session id is `target_thread` (or `name` if unset), so it appears inline and the agent can reference its own prior fires. |
| `skip_when_busy` | bool | `true` | Skip a fire if the previous fire of the *same task* is still in flight. Does not coordinate with concurrent user turns. |
| `ack_max_chars` | int \| null | `null` | `null` → ack suppression is **off**; every reply is delivered (subject to the `target_channel`/`target_thread` rule above). When set, a reply containing `HEARTBEAT_OK` within that length is suppressed — the same contract heartbeat uses (see [Ack contract](heartbeat.md#ack-contract)), just opt-in here instead of on-by-default. |
| `model` | string \| null | `null` | Model name from the agent's pool (`default_model` + `models`). Validated at plan time. `null` → agent's `default_model`. |
| `enabled` | bool | `true` | `false` keeps the row but excludes it from firing. |

Contrast with `Heartbeat`: `target_channel` is required and `ack_max_chars`
defaults to `300` (ack **on**) there; on `ScheduledTask` both are opt-in,
since not every scheduled task is a silent check-in.

## The three shapes

Exactly one of `cron`, `at`, `every` must be set — a model validator
rejects zero or multiple.

```yaml
schedules:
  # cron — recurring, calendar-aligned
  - name: monday-digest
    cron: "0 9 * * 1"              # 9:00 AM every Monday
    prompt: "Summarize last week."

  # at — one-shot, fires once then completes
  - name: deploy-freeze-reminder
    at: "2026-08-01T17:00:00Z"
    prompt: "Remind the channel the deploy freeze starts now."

  # every — recurring, fixed interval from activation
  - name: queue-check
    every: 30m                     # 30s, 20m, 2h, 1d
    prompt: "Check the deploy queue for stuck jobs."
```

## Runtime scheduling

### CLI

```bash
vystak schedules list [--agent <canonical>] [--all]     # --all includes completed/missed/cancelled
vystak schedules add --agent <canonical> --name <name> \
  [--cron <expr> | --at <iso8601> | --every <dur>] \
  [--timezone UTC] [--prompt <text>] \
  [--channel <canonical>] [--thread <id>]
vystak schedules show <task-id>
vystak schedules pause <task-id>       # PATCH enabled=false
vystak schedules resume <task-id>      # PATCH enabled=true
vystak schedules remove <task-id>      # DELETE (cancel)
```

Talks to the scheduler's REST API at `http://127.0.0.1:9797` by default
(override with `VYSTAK_SCHEDULER_URL`). If nothing is deployed with
schedules, every subcommand fails with `scheduler is not running — is
anything deployed with schedules?` rather than a raw connection error.

`add` only exposes the fields above as flags; to set `model`,
`isolated_session`, `skip_when_busy`, or `ack_max_chars` on a runtime task,
`POST` the scheduler's REST API directly (below) — it accepts the full
`ScheduledTask` shape.

**Declarative tasks are read-only through this CLI**: `pause`/`resume`/`remove`
against a task whose `source` is `declarative` return an error — edit
`schedules:` in `vystak.yaml` and `vystak apply` again instead.

### REST API

Internal platform network + host-published on `127.0.0.1:9797`, unauthenticated
(consistent with agent↔channel traffic in this iteration):

| Method | Path | Notes |
|---|---|---|
| `GET` | `/tasks?agent=&source=&status=` | List, optionally filtered. |
| `POST` | `/tasks` | Create a runtime task (`source` is always forced to `runtime`). Body is `ScheduledTask` fields + `agent` (canonical name) + optional `created_by`. `409` if `name` collides with an existing task (declarative or runtime) for that agent. |
| `GET` | `/tasks/{id}` | Detail, incl. `next_fire_at`, `last_fire_at`, `last_result`. |
| `PATCH` | `/tasks/{id}` | Edit/enable/disable — **runtime tasks only**. `404` if missing, `409` on a declarative task ("declarative task — change the YAML definition and re-apply"), `422` if the patched shape fails validation. Changing a shape field (`cron`/`at`/`every`/`timezone`) clears `next_fire_at` so it's recomputed on the next poll. |
| `DELETE` | `/tasks/{id}` | Cancel — **runtime tasks only**, same `409` rule as `PATCH`. Returns `204`. |
| `GET` | `/healthz` | `{"status": "ok"}`. |

### Agent tool

The langchain template ships `schedule_task` / `list_scheduled_tasks` /
`cancel_scheduled_task` (`_vystak/runtime/schedules.py`), exposed to the
agent automatically whenever the deployment has a scheduler (i.e.
`VYSTAK_SCHEDULER_URL`/`VYSTAK_AGENT_CANONICAL` are injected — which happens
whenever the agent declares `heartbeat`/`schedules`, or the platform sets
`scheduler.enabled: true`).

- `schedule_task(name, cron=None, at=None, every=None, prompt=None, timezone="UTC", deliver_here=True)` —
  creates a task for the calling agent itself. With `deliver_here=True`
  (the default), it reads the originating channel/thread from the current
  turn's metadata and sets `target_channel`/`target_thread` to point back
  at the conversation that asked — e.g. "remind me in 2 hours to check the
  deploy" delivers the reminder into the same chat thread it was asked
  from. If no originating channel/thread is known (e.g. called outside a
  channel-routed turn), the tool says so and the result is logged only.
- `list_scheduled_tasks()` — lists the calling agent's own tasks.
- `cancel_scheduled_task(task_id)` — cancels one of the calling agent's own
  tasks; refuses (`"not your task"`) if the id belongs to another agent.

All three are **scoped to the calling agent** — an agent can't see or
modify another agent's scheduled tasks.

## Reconciliation (`vystak apply`)

- Declarative tasks are **upserted** by `(agent, name)` on every apply.
- A declarative task removed from `vystak.yaml` is **deleted** from the
  store on the next apply.
- `source=runtime` tasks (CLI- or agent-created) are **never touched** by
  apply — they survive redeploys.
- If a declarative task's name already belongs to a runtime task for that
  agent, the declarative entry is **skipped with a warning** — the runtime
  row is left completely untouched (it is not overwritten or resurrected).
- The reverse direction is rejected outright: creating a runtime task whose
  name collides with an existing task (declarative or runtime) for that
  agent fails with `409`.
- Declarative `schedules` contribute to the agent's identity hash
  (`vystak/hash/tree.py`), so `vystak plan`/`apply` detects changes and
  redeploys accordingly. Runtime-created tasks are pure data — they never
  contribute to the hash and never cause drift.

## Missed-fire policy

On scheduler startup, every active row is reclassified:

- **Recurring** (`cron`/`every`): `next_fire_at` is always recomputed
  strictly from *now* — missed fires while the scheduler was down are
  never replayed (a missed 9:00 digest does not fire late).
- **One-shot** (`at`): if the timestamp is still in the future, it's
  scheduled normally. If it already passed but is within a **24-hour grace
  window**, it fires on the next poll pass. Older than 24 hours, it's
  marked `status=missed` instead of firing — surfaced via
  `vystak schedules show`/`list --all` and the REST API, never silently
  dropped.

## Ack contract

Same mechanism as heartbeat's — see
[`docs/heartbeat.md#ack-contract`](heartbeat.md#ack-contract) — except it's
opt-in here: set `ack_max_chars` to enable it (heartbeat has it on by
default at `300`).

## Observability

Structured log events at the `vystak.heartbeat.task_scheduler` logger.
Every scheduled task emits the `scheduled_task.*` family, **except** the
task named `"heartbeat"` (whatever a declarative `heartbeat:` block
compiles to), which keeps the legacy `heartbeat.*` names so existing
log-based tooling and `docs/heartbeat.md`'s table keep working unchanged:

| Event (non-heartbeat) | Event (`name == "heartbeat"`) | Level | When |
|---|---|---|---|
| `scheduled_task.fired` | `heartbeat.fired` | INFO | Each fire dispatched into the pipeline. |
| `scheduled_task.acked` | `heartbeat.acked` | INFO | Reply matched `HEARTBEAT_OK` (`ack_max_chars` set) and was dropped. |
| `scheduled_task.skipped` | `heartbeat.skipped` | INFO | Skipped due to `skip_when_busy`. |
| `scheduled_task.fired_failed` | `heartbeat.fired_failed` | ERROR | The fire itself raised; loop continues. |
| `scheduled_task.delivery_failed` | `heartbeat.delivery_failed` | ERROR | `deliver()` raised after a successful fire; the fire is still recorded. |

A missing `target_thread` (or `target_channel`) doesn't skip the fire —
the agent is still called and `.fired` is still logged; it only skips the
delivery step afterward, silently (no separate event).

## Plan-time validation

`vystak plan`/`apply` validate, for every declared schedule:

1. If `target_channel` is set, it matches a declared channel's
   `canonical_name`, and that channel actually routes the agent.
2. If `model` is set, it's in the agent's model pool (`default_model` +
   `models`).
3. The `cron`/`every`/`timezone` values are valid (schema-level, at load
   time — same as `at`'s exactly-one-shape check).
4. No agent declares a schedule literally named `"heartbeat"` (reserved).

Failures block deploy with a message pointing at the misconfigured field.

## Shared state across projects

The `vystak-scheduler-data` volume (SQLite-backed store for every schedule,
declarative and runtime) is **host-global**, not project-scoped, and it
survives `vystak destroy` by design — same caveat as the Vault and
Postgres data volumes elsewhere in this stack. Deploying a *different*
project on the same Docker host reuses that volume, so the previous
project's rows are still there: declarative tasks whose agent no longer
exists keep getting picked up as "due" and firing into
`scheduled_task.fired_failed` / `heartbeat.fired_failed` logs (the target
agent container isn't reachable), and they keep showing up in
`vystak schedules list` until pruned.

Remedy: once the old project's containers are gone, remove the volume by
hand — `docker volume rm vystak-scheduler-data` — before deploying the new
project. There's no automatic per-project isolation of this volume today.
