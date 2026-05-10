# Heartbeat

A heartbeat is a periodic synthetic turn — the agent wakes up on a cron
schedule, runs a check-in prompt, and either surfaces an alert into a
configured channel/thread or stays silent.

## Quick start

Add a `heartbeat` block to any agent that has at least one channel
routing to it:

```yaml
agents:
  - name: ops-bot
    framework: langchain-python
    model: claude
    platform: local
    heartbeat:
      schedule: "*/30 9-18 * * 1-5"     # every 30m, 9-18, Mon-Fri
      timezone: America/New_York
      target_channel: chat-main.channels.dev
      target_thread: standup-room

channels:
  - name: chat-main
    type: chat
    platform: local
    agents: [ops-bot]
```

The channel runtime named in `target_channel` hosts the scheduler. On
every cron tick, the runtime synthesizes a turn, calls the agent, and
applies the ack contract (below).

See the full example: [`examples/heartbeat-agent/`](../examples/heartbeat-agent/).

## Configuration reference

| Field | Type | Default | Notes |
|---|---|---|---|
| `schedule` | string | required | 5-field cron (e.g. `"*/30 * * * *"`). Validated at schema load. |
| `timezone` | string | `"UTC"` | IANA timezone (e.g. `"America/New_York"`). Validated at schema load. |
| `target_channel` | string | required | Channel canonical_name (`<channel-name>.channels.<platform-namespace>`). Validated at plan time. |
| `target_thread` | string \| null | `null` | Specific delivery thread/scope id. If `null`, the runtime resolves at fire time from the most recent ThreadBinding for this agent. |
| `prompt` | string \| null | `null` | Override the built-in prompt. `null` uses the default. |
| `isolated_session` | bool | `true` | When true, fires use a synthetic session id and don't appear in the user thread's history. |
| `skip_when_busy` | bool | `true` | Skip a fire if the previous one is still running. |
| `ack_max_chars` | int | `300` | Max length to scan for `HEARTBEAT_OK`. Replies longer than this are always delivered. |
| `enabled` | bool | `true` | Set false to keep config but disable scheduling. |

## Ack contract

When the agent's reply (after stripping whitespace):

- Is **empty** → posted as-is. An empty reply signals a real bug; we
  don't silently swallow it.
- Is **longer than `ack_max_chars`** (default 300) → always posted, even
  if it contains `HEARTBEAT_OK`. Long replies override the ack.
- Contains `HEARTBEAT_OK` → silently dropped, logged at INFO.
- Anything else → posted into `target_thread` on `target_channel`.

## HEARTBEAT.md convention

If your agent has a workspace, place a `HEARTBEAT.md` file in it
describing the per-cycle check-in:

```markdown
# Ops checklist
On every heartbeat:
1. Check the deploy queue.
2. Check error-rate alerts.

Reply only when something needs human attention. Otherwise reply with
HEARTBEAT_OK.
```

Then leave `prompt: null` (the default) and the runtime will use:

> Read HEARTBEAT.md if it exists in your workspace. Follow it strictly.
> If nothing needs attention, reply with only HEARTBEAT_OK. Otherwise,
> reply with a short message describing what needs attention — do not
> include HEARTBEAT_OK in that case.

`HEARTBEAT.md` is a documented pattern, not a Vystak feature. The agent
itself reads (and may rewrite) the file via the workspace tooling.
Vystak does not auto-create or auto-mount it.

## Cron + timezone

`schedule` is a 5-field cron expression evaluated against `timezone`
(IANA name, default UTC). All standard cron features apply:

| Expression | Meaning |
|---|---|
| `*/30 * * * *` | every 30 minutes |
| `0 9 * * 1-5` | 9:00 AM Mon-Fri |
| `*/15 9-18 * * 1-5` | every 15m, 9-18, weekdays |
| `0 0 1 * *` | midnight on the 1st of each month |

Active-hours behavior (e.g. "only fire 9-22") is expressed directly in
cron — there is no separate `active_hours` field.

## Session isolation

By default (`isolated_session: true`), each fire uses a synthetic
session id so the heartbeat never appears in your user-facing thread
history. Only the *result* (the alert) gets posted into
`target_thread`.

Set `isolated_session: false` to make the heartbeat turn appear inline
in `target_thread`'s session — useful for digest patterns where the
agent should remember its previous summaries.

## Operational notes

- **Restart behaviour:** the scheduler resumes from `now`. Missed fires
  are not replayed (a missed 9:00 standup will not fire at 9:07 after
  a restart). This is intentional; for catch-up semantics, store state
  in your agent's memory and reason from there.
- **`skip_when_busy`:** prevents back-to-back fires from overlapping if
  the previous fire is still running. It does **not** coordinate with
  concurrent user turns. A real user message that arrives while a
  heartbeat is in flight is processed normally.
- **Multiple channels:** each agent has at most one heartbeat target.
  If you want the same agent to ping multiple channels, declare two
  agents (sharing model + skills) with different `target_channel`
  values.
- **Hash propagation:** heartbeat is part of the agent's identity hash.
  Changing `schedule`, `prompt`, `target_channel`, etc. triggers a
  redeploy of the channel container that hosts the scheduler.

## Telemetry

The runtime emits structured log events at the `vystak.channel.runtime.heartbeat`
logger:

| Event | Level | When |
|---|---|---|
| `heartbeat.fired` | INFO | Each fire dispatched into the pipeline |
| `heartbeat.acked` | INFO | Reply matched `HEARTBEAT_OK` and was dropped |
| `heartbeat.skipped` | INFO/DEBUG | Skipped due to `skip_when_busy` (INFO) or no resolved thread (DEBUG) |
| `heartbeat.fired_failed` | ERROR | `_fire` raised an exception; loop continues |

## Plan-time validation

`vystak plan` and `vystak apply` validate that:

1. Every `heartbeat.target_channel` matches a declared channel's
   `canonical_name`.
2. The named channel actually routes the agent (i.e. the agent appears
   in `channel.agents`).
3. The cron expression and timezone are valid.

Failures block deploy with a helpful error pointing at the misconfigured
field.
