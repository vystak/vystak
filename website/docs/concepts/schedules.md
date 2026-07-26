---
title: Scheduled Tasks
sidebar_label: Scheduled Tasks
---

# Scheduled Tasks

A **scheduled task** fires a prompt at an agent on a schedule — a cron
expression, a one-shot timestamp, or a recurring interval — and
optionally delivers the reply into a channel thread.

It generalizes [`heartbeat`](#heartbeat-is-a-scheduled-task): a
declarative `heartbeat:` block compiles internally into a scheduled task
named `"heartbeat"` with a stricter, always-on delivery contract.
Unlike heartbeat, scheduled tasks can also be created and cancelled at
**runtime** — by an operator via the CLI/REST API, or by the agent
itself via a tool — without editing `vystak.yaml` or redeploying.

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
`vystak-heartbeat` container — the same one that hosts heartbeat — as the
platform's scheduler. No extra platform config is required.

`examples/docker-schedules/` is a complete working setup: one agent
scheduled three ways (declarative, CLI, agent tool) delivering into a
chat channel.

## The three shapes

Exactly one of `cron`, `at`, `every` must be set — a model validator
rejects zero or multiple:

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

## Configuration reference

`ScheduledTask` fields:

| Field | Type | Default | Notes |
|---|---|---|---|
| `name` | string | required | Unique per agent; reconciliation identity for `vystak apply`. The literal name `"heartbeat"` is reserved — it's what a declarative `heartbeat:` block compiles to. |
| `cron` \| `at` \| `every` | — | `null` | Exactly one shape, see above. |
| `timezone` | string | `"UTC"` | IANA name. Applies to `cron` evaluation and a timezone-naive `at`. |
| `prompt` | string \| null | `null` | Prompt sent on fire. `null` → a generated default (or the heartbeat default prompt, for the task named `"heartbeat"`). |
| `target_channel` | string \| null | `null` | Channel `canonical_name` for delivery. `null` → the fire still happens, but nothing is delivered — visible only in logs/traces. |
| `target_thread` | string \| null | `null` | Delivery thread/scope id. Delivery requires **both** `target_channel` and `target_thread` to be set. |
| `isolated_session` | bool | `true` | `true` → each fire uses a synthetic session, invisible in user-facing history. `false` → the fire's session is `target_thread` (or `name`), so it appears inline. |
| `skip_when_busy` | bool | `true` | Skip a fire if the previous fire of the *same task* is still in flight. |
| `ack_max_chars` | int \| null | `null` | `null` → every reply is delivered. When set, a reply containing `HEARTBEAT_OK` within that length is suppressed — same ack contract heartbeat uses, opt-in here instead of on by default. |
| `model` | string \| null | `null` | Model name from the agent's pool (`default_model` + `models`). `null` → the agent's `default_model`. |
| `enabled` | bool | `true` | `false` keeps the row but excludes it from firing. |

## Runtime scheduling

### CLI

```bash
vystak schedules list [--agent <canonical>] [--all]
vystak schedules add --agent <canonical> --name <name> \
  [--cron <expr> | --at <iso8601> | --every <dur>] \
  [--timezone UTC] [--prompt <text>] \
  [--channel <canonical>] [--thread <id>]
vystak schedules show <task-id>
vystak schedules pause <task-id>
vystak schedules resume <task-id>
vystak schedules remove <task-id>
```

Talks to the scheduler's REST API — see [CLI Reference](../cli/reference#vystak-schedules)
for the full flag list and per-command notes. Declarative tasks are
**read-only** through this CLI: `pause`/`resume`/`remove` against a task
whose `source` is `declarative` return an error — edit `schedules:` in
`vystak.yaml` and `vystak apply` again instead.

### REST API

Every scheduler exposes a small REST API, internal to the platform
network and also published on the host at `http://127.0.0.1:9797`
(unauthenticated, consistent with agent↔channel traffic today):

| Method | Path | Notes |
|---|---|---|
| `GET` | `/tasks?agent=&source=&status=` | List, optionally filtered. |
| `POST` | `/tasks` | Create a runtime task. `409` if `name` collides with an existing task for that agent. |
| `GET` | `/tasks/{id}` | Detail, incl. `next_fire_at`, `last_fire_at`, `last_result`. |
| `PATCH` | `/tasks/{id}` | Edit/enable/disable — runtime tasks only (`409` on a declarative task). |
| `DELETE` | `/tasks/{id}` | Cancel — runtime tasks only. |
| `GET` | `/healthz` | `{"status": "ok"}`. |

The CLI's `add` only exposes the flags above; to set `model`,
`isolated_session`, `skip_when_busy`, or `ack_max_chars` on a runtime
task, `POST` this API directly — it accepts the full `ScheduledTask` shape.

### Agent tool

The langchain template gives every scheduler-enabled agent three tools,
scoped to itself:

- `schedule_task(name, cron=None, at=None, every=None, prompt=None, timezone="UTC", deliver_here=True)` —
  creates a task for the calling agent. With `deliver_here=True` (the
  default), it reads the originating channel/thread from the current
  turn and sets `target_channel`/`target_thread` to point back at that
  conversation — e.g. "remind me in 2 hours to check the deploy" delivers
  the reminder into the same chat thread it was asked from.
- `list_scheduled_tasks()` — lists the calling agent's own tasks.
- `cancel_scheduled_task(task_id)` — cancels one of its own tasks;
  refuses tasks belonging to another agent.

These tools are available automatically whenever the deployment has a
scheduler — i.e. the agent declares `heartbeat`/`schedules`.

## Reconciliation (`vystak apply`)

- Declarative tasks are **upserted** by `(agent, name)` on every apply.
- A declarative task removed from `vystak.yaml` is **deleted** from the
  store on the next apply.
- Runtime tasks (CLI- or agent-created) are **never touched** by apply —
  they survive redeploys.
- If a declarative task's name already belongs to a runtime task for
  that agent, the declarative entry is **skipped with a warning** — the
  runtime row is left untouched. The reverse is rejected outright:
  creating a runtime task with a colliding name fails with `409`.
- Declarative `schedules` contribute to the agent's identity hash, so
  `vystak plan`/`apply` detects changes and redeploys accordingly.
  Runtime-created tasks are pure data — they never contribute to the
  hash and never cause drift.

## Missed-fire policy

On scheduler startup, every active row is reclassified:

- **Recurring** (`cron`/`every`): `next_fire_at` is always recomputed
  strictly from *now* — missed fires while the scheduler was down are
  never replayed.
- **One-shot** (`at`): if the timestamp already passed but is within a
  **24-hour grace window**, it fires on the next poll pass. Older than
  24 hours, it's marked `status=missed` instead — surfaced via
  `vystak schedules show`/`list --all`, never silently dropped.

## Heartbeat is a scheduled task

A declarative `heartbeat:` block compiles into a `ScheduledTask` named
`"heartbeat"`, run by the same scheduler as every other scheduled task —
with a stricter, always-on delivery contract: `target_channel` is
required (vs. optional) and `ack_max_chars` defaults to `300`, ack on
(vs. opt-in). It keeps heartbeat's ack contract: a reply that's empty or
longer than `ack_max_chars` is always delivered; a reply containing
`HEARTBEAT_OK` within that length is silently dropped.

If you need a one-shot reminder, a runtime-created schedule, or an agent
that schedules tasks for itself, reach for `schedules:` directly instead
of `heartbeat:`.

## Shared state across projects

The scheduler's data volume (SQLite-backed store for every schedule,
declarative and runtime) is **host-global**, not project-scoped, and it
survives `vystak destroy` by design — same caveat as the Vault and
Postgres data volumes elsewhere in this stack. Deploying a *different*
project on the same Docker host reuses that volume, so the previous
project's rows are still there: declarative tasks whose agent no longer
exists keep getting picked up as due and firing into failure logs, and
keep showing up in `vystak schedules list` until pruned.

Remedy: once the old project's containers are gone, remove the volume
by hand (`docker volume rm vystak-scheduler-data`) before deploying the
new project. There's no automatic per-project isolation of this volume
today.

## Related

- [Channels](./channels) — where scheduled task results get delivered
- [CLI Reference](../cli/reference) — `vystak schedules` command details
