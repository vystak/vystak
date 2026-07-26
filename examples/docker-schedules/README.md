# docker-schedules example

Demonstrates Vystak's scheduled-tasks feature — the generalized mechanism
behind `heartbeat:` (see `docs/schedules.md`). One agent, three ways to get
a prompt fired at it on a schedule:

1. **Declarative** — `ops-bot` declares a `schedules:` entry in
   `vystak.yaml`: a weekly digest every Monday 9am, delivered into the
   `chat-main` channel.
2. **Operator, at runtime** — `vystak schedules add` creates a recurring
   task via the CLI without touching `vystak.yaml` or redeploying.
3. **Agent, at runtime** — the agent's own `schedule_task` tool, so a user
   can just ask it to remind them about something later.

This directory ships the scaffolded `_vystak/` runtime already (like
`examples/docker-chat`), so `vystak apply` works directly — no `vystak
init` step needed.

## What's declared

```yaml
agents:
  - name: ops-bot
    schedules:
      - name: monday-digest
        cron: "0 9 * * 1"
        timezone: America/New_York
        prompt: "Summarize last week's deploys and any outstanding alerts."
        target_channel: chat-main.channels.dev
        target_thread: digest-room
```

Declaring `schedules:` (or `heartbeat:`) on any agent auto-provisions the
`vystak-heartbeat` scheduler container — no extra platform config needed.

## Run

```bash
cd examples/docker-schedules
export ANTHROPIC_API_KEY=sk-ant-...
vystak apply
```

Three containers come up: `vystak-ops-bot` (agent), `vystak-channel-chat-main`
(chat channel, host port 8080), `vystak-heartbeat` (scheduler — REST API on
`127.0.0.1:9797`).

## List schedules

```bash
vystak schedules list
```

```
a1b2c3d4  ops-bot.agents.dev             monday-digest        declarative active    0 9 * * 1  next=2026-08-03T13:00:00+00:00
```

The declarative `monday-digest` task is there from `vystak apply` — no
manual creation needed.

## Add a runtime schedule via the CLI

```bash
vystak schedules add --agent ops-bot.agents.dev --name deploy-check \
  --every 30m --prompt "Check the deploy queue for stuck jobs." \
  --channel chat-main.channels.dev --thread digest-room
```

Prints the new task's id. `vystak schedules list` now shows a second row,
`source=runtime`, alongside the declarative one.

## Ask the agent to schedule something for itself

```bash
curl -s -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "vystak/ops-bot",
    "messages": [{"role": "user", "content": "remind me in 2 hours to check the deploy"}]
  }'
```

The agent's `schedule_task` tool creates an `every`/`at` task for itself
and, by default (`deliver_here=True`), targets it back at this same chat
thread — when it fires, the reply is delivered here, not just logged.

Inspect what it created:

```bash
vystak schedules list --agent ops-bot.agents.dev --all
```

## Remove a schedule

```bash
vystak schedules remove <task-id>
```

Only works on runtime tasks (CLI-created or agent-created) — the
declarative `monday-digest` task returns a 409 ("declarative task — change
the YAML definition and re-apply"). To change or remove it, edit
`vystak.yaml`'s `schedules:` block and run `vystak apply` again.

## Tear down

```bash
vystak destroy
```

`vystak-scheduler-data` (the SQLite volume backing every schedule, declarative
and runtime) is intentionally left behind, same as the session/memory
volumes — remove it by hand (`docker volume rm vystak-scheduler-data`) for a
truly clean slate.

## See also

- [`docs/schedules.md`](../../docs/schedules.md) — full field reference,
  reconciliation rules, missed-fire policy.
- [`docs/heartbeat.md`](../../docs/heartbeat.md) — the `heartbeat:` shorthand,
  which compiles to a schedule with a stricter ack contract.
- [`examples/heartbeat-agent/`](../heartbeat-agent/) — the single-schedule,
  ack-contract-focused sibling example.
