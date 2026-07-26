---
title: CLI Reference
sidebar_label: Reference
---

# CLI Reference

The `vystak` command-line interface.

*Detailed reference for `init` / `plan` / `apply` / `destroy` / `status` /
`logs` / `secrets` / `update` coming soon.*

## `vystak schedules`

Manage [scheduled tasks](/docs/concepts/schedules) at runtime — list,
create, inspect, pause, resume, and remove them without editing
`vystak.yaml` or redeploying. Talks to the scheduler's REST API at
`http://127.0.0.1:9797` by default (override with `VYSTAK_SCHEDULER_URL`).
If nothing is deployed with schedules, every subcommand fails with
`scheduler is not running — is anything deployed with schedules?` rather
than a raw connection error.

**Declarative tasks are read-only through this CLI** — `pause` / `resume`
/ `remove` against a task whose source is `declarative` return an error;
edit `schedules:` in `vystak.yaml` and run `vystak apply` again instead.

### `vystak schedules list`

```bash
vystak schedules list [--agent <canonical>] [--all]
```

| Flag | Notes |
|---|---|
| `--agent` | Filter to one agent's canonical name (e.g. `ops-bot.agents.dev`). |
| `--all` | Include `completed` / `missed` / `cancelled` tasks. Default shows only `active`. |

```
a1b2c3d4  ops-bot.agents.dev             monday-digest        declarative active    0 9 * * 1  next=2026-08-03T13:00:00+00:00
```

### `vystak schedules add`

```bash
vystak schedules add --agent <canonical> --name <name> \
  [--cron <expr> | --at <iso8601> | --every <dur>] \
  [--timezone UTC] [--prompt <text>] \
  [--channel <canonical>] [--thread <id>]
```

| Flag | Required | Notes |
|---|---|---|
| `--agent` | yes | Agent canonical name. |
| `--name` | yes | Unique per agent. `409` if it collides with an existing task (declarative or runtime) for that agent. |
| `--cron` | one of `--cron`/`--at`/`--every` | 5-field cron expression. |
| `--at` | one of `--cron`/`--at`/`--every` | ISO-8601 one-shot time. |
| `--every` | one of `--cron`/`--at`/`--every` | Interval duration — `30s`, `20m`, `2h`, `1d`. |
| `--timezone` | no | IANA name. Default `UTC`. |
| `--prompt` | no | Prompt sent to the agent on fire. |
| `--channel` | no | Target channel canonical name for delivery. |
| `--thread` | no | Target thread/scope id. Delivery requires both `--channel` and `--thread`. |

Prints the new task's id. Created tasks always get `source=runtime`.
This command only exposes the flags above; to set `model`,
`isolated_session`, `skip_when_busy`, or `ack_max_chars`, `POST` the
scheduler's REST API directly with the full `ScheduledTask` shape (see
[Scheduled Tasks](/docs/concepts/schedules)).

### `vystak schedules show`

```bash
vystak schedules show <task-id>
```

Prints the full task record as JSON, including `next_fire_at`,
`last_fire_at`, and `last_result`.

### `vystak schedules pause` / `vystak schedules resume`

```bash
vystak schedules pause <task-id>   # sets enabled=false
vystak schedules resume <task-id>  # sets enabled=true
```

Runtime tasks only — `409` on a declarative task.

### `vystak schedules remove`

```bash
vystak schedules remove <task-id>
```

Cancels (deletes) a runtime task. Runtime tasks only — `409` on a
declarative task.
