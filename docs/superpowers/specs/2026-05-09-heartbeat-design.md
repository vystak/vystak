# Heartbeat — periodic agent self-invocation

**Status:** design
**Date:** 2026-05-09
**Author:** Anatoliy Kolodkin
**Reference:** [OpenClaw Heartbeat](https://docs.openclaw.ai/gateway/heartbeat#heartbeat)

## Summary

Add a `heartbeat` field to `Agent` so an agent can be configured to wake up
on a cron schedule, run a synthetic turn through one of its channels, and
either surface an alert in the channel or stay silent (`HEARTBEAT_OK`).
Closely mirrors OpenClaw's design, with cron expressions instead of
duration strings.

The scheduler lives **in the channel runtime**, not in the agent process.
This reuses existing thread bindings, the `agent_client` A2A path, and
`post_reply` delivery — the heartbeat fires by synthesizing an
`InboundEvent` and running it through the existing pipeline.

## Goals

1. Match OpenClaw's heartbeat semantics closely so users can port mental
   models and `HEARTBEAT.md` checklists between the two systems.
2. Reuse Vystak's existing channel runtime — no new deployable, no new
   outbound surface on the agent process.
3. Make heartbeat config part of the agent's identity hash so changes
   trigger redeploys correctly.
4. Configurable enough to support all three of: reactive monitoring,
   scheduled summaries, long-running task progress reports.

## Non-goals

- Per-user opt-in (heartbeat targets channels/threads, not users).
- Catch-up on missed fires after restart (cron resumes from `now`).
- Coordination with concurrent user turns (`skip_when_busy` only guards
  back-to-back heartbeat fires; documented limitation).
- Tool-based ack (`heartbeat_respond` tool). Text sentinel only for v1.
- Auto-mounting or auto-creating `HEARTBEAT.md` (user responsibility).

## Architecture

```
Agent (declares: heartbeat with target_channel + cron)
  │
  └─▶ ChannelRuntime (matches target_channel == self.canonical_name)
        │
        ├─ HeartbeatScheduler (one per matching agent)
        │    │
        │    └─ on cron tick: synthesize InboundEvent → handle_event()
        │
        └─ existing pipeline:
             agent_client.call → reply
               │
               ├─ heartbeat metadata + reply matches HEARTBEAT_OK → drop
               └─ otherwise → post_reply to deliver_thread
```

Channels declare which agents they route. An agent's `heartbeat.target_channel`
is a back-reference (by canonical_name) that the channel runtime resolves
on startup. Plan-time validation ensures the target exists and routes
this agent.

## Schema

New module `packages/python/vystak/src/vystak/schema/heartbeat.py`:

```python
from pydantic import BaseModel, field_validator
from croniter import croniter


class Heartbeat(BaseModel):
    """Periodic agent self-invocation, configured per-agent and fired by
    the channel runtime named in `target_channel`."""

    schedule: str                       # 5-field cron, e.g. "*/30 * * * *"
    timezone: str = "UTC"               # IANA TZ for cron evaluation
    target_channel: str                 # channel canonical_name
    target_thread: str | None = None    # if None, channel resolves at fire time
    prompt: str | None = None           # None → built-in default
    isolated_session: bool = True       # synthetic thread_id per fire
    skip_when_busy: bool = True         # skip if previous fire still running
    ack_max_chars: int = 300            # max length to scan for HEARTBEAT_OK
    enabled: bool = True

    @field_validator("schedule")
    @classmethod
    def _validate_cron(cls, v: str) -> str:
        if not croniter.is_valid(v):
            raise ValueError(f"invalid cron expression: {v!r}")
        return v
```

`Agent` gets one new optional field:

```python
class Agent(NamedModel):
    ...
    heartbeat: Heartbeat | None = None
```

`active_hours` is **not** a separate field — cron expresses time gating
directly (`*/30 9-22 * * 1-5`).

### Plan-time validation

Cross-deployable validation happens in `vystak.provisioning` graph
builder, not in the Pydantic model. For every agent with `heartbeat`:

1. Resolve `target_channel` against the deployment's channel set.
2. Confirm the resolved channel routes this agent (`agent in channel.agents`).
3. Re-validate the cron expression.

Failures block `vystak plan`/`apply` with a clear error.

### Hash contribution

`Heartbeat` field set is included in the agent's identity hash
(`vystak/hash/tree.py`) and in the channel's hash (since the channel
container hosts the scheduler). Result: changing the schedule, prompt,
target, isolation, or ack settings triggers redeploy of the channel
container.

## Channel runtime

New module `packages/python/vystak-channel-runtime/src/vystak_channel_runtime/heartbeat.py`:

```python
class HeartbeatScheduler:
    """Per-(channel, agent) scheduler. Owned by ChannelRuntime."""

    def __init__(self, runtime, agent_name: str, config: Heartbeat) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def _run(self) -> None:
        """Loop: croniter → asyncio.sleep until next fire → _fire()."""

    async def _fire(self) -> None:
        """Resolve thread, synthesize InboundEvent, hand to runtime.handle_event."""
```

The fire produces **two events**, separating the *session scope* (where
the agent stores its turn) from the *delivery scope* (where the alert
gets posted):

**Session event** — passed to `agent_client.call`:

| Field | Value |
|---|---|
| `channel_type` | `runtime.channel_type` |
| `scope_id` | synthetic `__heartbeat__<ts>_<rand>` if `isolated_session` else real `target_channel` scope |
| `thread_id` | synthetic if `isolated_session` else real `target_thread` |
| `user_id` | `__heartbeat__` |
| `text` | `config.prompt or DEFAULT_PROMPT` |
| `is_dm` | `False` |
| `mentions_bot` | `True` |
| `metadata` | `{"heartbeat": True, "ack_max_chars": <n>, "deliver_scope": <real>, "deliver_thread": <real>}` |

**Delivery event** — synthesized by the runtime *only if* `is_heartbeat_ok`
returns False, and passed to subclass `post_reply`. Has real
`scope_id`/`thread_id` so platform-specific code (Slack `chat.postMessage`,
Discord `channel.send`, etc.) hits the right destination. No subclass
changes required.

**`after_reply` is skipped for heartbeat events** — no thread binding
write, since synthetic scopes shouldn't pollute the binding store.

### Three hooks added to `ChannelRuntime`

1. **Startup** — after subclass `start()`, scan routes for
   `heartbeat.target_channel == self.canonical_name and heartbeat.enabled`,
   instantiate one `HeartbeatScheduler` per match, store on
   `self._heartbeats: list[HeartbeatScheduler]`, call `start()` on each.
2. **Shutdown** — call `stop()` on each before subclass `stop()`.
3. **Ack stripping** — in `handle_event` (or right before `post_reply`),
   if `event.metadata.get("heartbeat")`, evaluate the reply with
   `is_heartbeat_ok(text, ack_max_chars)`. If True → log "heartbeat ok"
   and drop. Else → post normally to `metadata["deliver_thread"]`.

### Ack-stripping rules (`is_heartbeat_ok` pure function)

| Reply | Result |
|---|---|
| `"HEARTBEAT_OK"` | True (drop) |
| `"  HEARTBEAT_OK\n"` (whitespace) | True |
| `"All good. HEARTBEAT_OK"` (length ≤ `ack_max_chars`) | True |
| `"<long body...HEARTBEAT_OK>"` (length > `ack_max_chars`) | False (post anyway) |
| `""` or whitespace-only | False (do not silently swallow bugs) |

### New store method

One method on `ChannelStore`:

```python
async def last_binding_for_agent(
    self, channel_type: str, agent_name: str
) -> ThreadBinding | None: ...
```

SQL: `SELECT ... WHERE channel_type=? AND agent_name=? ORDER BY updated_at DESC LIMIT 1`.
Implemented for both SQLite and Postgres backends.

### New dependency

`croniter` — added to `vystak` and `vystak-channel-runtime`'s
`pyproject.toml`.

## Default prompt and HEARTBEAT.md convention

When `heartbeat.prompt` is `None`, the runtime uses:

```
Read HEARTBEAT.md if it exists in your workspace. Follow it strictly.
If nothing needs attention, reply with only HEARTBEAT_OK.
Otherwise, reply with a short message describing what needs attention —
do not include HEARTBEAT_OK in that case.
```

`HEARTBEAT.md` is a documented pattern, not a Vystak feature:
- Lives at the workspace root (e.g. `/workspace/HEARTBEAT.md` on Docker).
- Read by the agent via its existing file-reading tool
  (`vystak-workspace-rpc` already exposes the file ops).
- Agent may rewrite it across cycles. Vystak does not manage the file.

Agents without a workspace can still use heartbeat — they just need a
custom `prompt` that doesn't reference `HEARTBEAT.md`.

## Restart behavior

When a channel container restarts, schedulers compute their next fire
from `now`. **No catch-up of missed fires, no persistence of last-fire
time.** This matches `croniter` defaults and is correct for monitoring
patterns: a missed 09:00 standup should not fire at 09:07 after a
restart.

## Error handling

| Failure | Behavior |
|---|---|
| Cron eval throws mid-loop | Log error, sleep 60s, recompute next fire. Loop survives. |
| Agent A2A call returns 5xx / times out | Log + telemetry counter, `_busy=False`, wait next fire. No retry within fire. |
| Reply matches `is_heartbeat_ok` | Log at INFO, drop. |
| `target_thread=None` and store has no binding | Skip silently, log at DEBUG. |
| Channel container restart | Schedulers recompute from `now`. |
| Plan-time: target_channel typo / channel doesn't route agent | `vystak plan` fails with helpful error. |

Telemetry: three new structured-log events: `heartbeat.fired`,
`heartbeat.skipped` (with reason), `heartbeat.acked`. No new metrics
infrastructure.

`skip_when_busy` scope: only reflects the scheduler's own in-flight fire.
It does **not** check whether a real user turn is in flight on the same
thread. Documented limitation; no coordination with user turns in v1.

## Examples

### Python — `examples/heartbeat-agent/vystak.py`

```python
from vystak.schema import (
    Agent, Channel, ChannelType, Heartbeat, Model, Platform,
    Provider, Secret, Skill,
)

anthropic = Provider(name="anthropic", type="anthropic")
docker = Provider(name="docker", type="docker")
local = Platform(name="local", type="docker", provider=docker, namespace="dev")

model = Model(
    name="claude",
    provider=anthropic,
    model_name="claude-sonnet-4-6",
    parameters={"temperature": 0.3},
)

ops_agent = Agent(
    name="ops-bot",
    instructions=(
        "You are an ops assistant. On every heartbeat, scan the workspace's "
        "HEARTBEAT.md checklist and surface anything that needs attention. "
        "If nothing is wrong, reply with HEARTBEAT_OK and nothing else."
    ),
    model=model,
    platform=local,
    skills=[Skill(name="ops", tools=[])],
    secrets=[Secret(name="ANTHROPIC_API_KEY")],
    heartbeat=Heartbeat(
        schedule="*/30 9-18 * * 1-5",
        timezone="America/New_York",
        target_channel="slack-main.channels.dev",
        target_thread="C0123456789",
        isolated_session=True,
        skip_when_busy=True,
        ack_max_chars=300,
    ),
)

slack = Channel(
    name="slack-main",
    type=ChannelType.SLACK,
    platform=local,
    config={"port": 8081},
    secrets=[Secret(name="SLACK_BOT_TOKEN"), Secret(name="SLACK_APP_TOKEN")],
    agents=[ops_agent],
    default_agent=ops_agent,
)
```

### YAML — `examples/heartbeat-agent/vystak.yaml`

```yaml
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}

platforms:
  local: {type: docker, provider: docker, namespace: dev}

models:
  claude:
    provider: anthropic
    model_name: claude-sonnet-4-6
    parameters: {temperature: 0.3}

agents:
  - name: ops-bot
    instructions: |
      You are an ops assistant. On every heartbeat, scan the workspace's
      HEARTBEAT.md checklist and surface anything that needs attention.
      If nothing is wrong, reply with HEARTBEAT_OK and nothing else.
    model: claude
    platform: local
    skills:
      - {name: ops, tools: []}
    secrets:
      - {name: ANTHROPIC_API_KEY}
    heartbeat:
      schedule: "*/30 9-18 * * 1-5"
      timezone: America/New_York
      target_channel: slack-main.channels.dev
      target_thread: C0123456789
      isolated_session: true
      skip_when_busy: true
      ack_max_chars: 300

channels:
  - name: slack-main
    type: slack
    platform: local
    config: {port: 8081}
    secrets:
      - {name: SLACK_BOT_TOKEN}
      - {name: SLACK_APP_TOKEN}
    agents: [ops-bot]
    default_agent: ops-bot
```

## Testing

### Unit — `vystak-channel-runtime/tests/test_heartbeat.py`

`HeartbeatScheduler` with a fake runtime (mock `handle_event`, mock store):
- Cron schedule produces correct next-fire delay (`freezegun`).
- `enabled=False` → no task spawned.
- `skip_when_busy=True` + back-to-back fires → second skipped.
- `target_thread=None` + empty store → skip.
- `target_thread=None` + populated store → uses `last_binding_for_agent`.
- `isolated_session=True` → synthetic `__heartbeat__*` thread_id.
- Cron error mid-loop → loop survives, retries.

Ack stripping (pure function `is_heartbeat_ok(text, max_chars)`):
- `"HEARTBEAT_OK"`, `"  HEARTBEAT_OK\n"` → True.
- `"All good. HEARTBEAT_OK"` (≤ max_chars) → True.
- Long reply containing `HEARTBEAT_OK` (> max_chars) → False.
- Empty / whitespace-only → False.

### Schema + plan-time — `vystak/tests/test_heartbeat_schema.py`

- `Heartbeat` round-trips through Pydantic + YAML loader.
- Invalid cron → `ValidationError` at schema load.
- Hash-tree: schedule/prompt/enabled changes propagate to agent and channel hashes.
- Provisioning graph builder:
  - `target_channel` typo → plan-time error.
  - `target_channel` exists but doesn't route this agent → plan-time error.
  - Valid config → scheduler wired correctly.

### Integration — `vystak-provider-docker/tests/release/test_heartbeat.py`

One new release cell, marked `release_integration`:
- Deploy `ops-bot` + `chat` channel with `schedule: "* * * * *"` and
  custom `prompt: "Reply HEARTBEAT_OK"`.
- Wait ~70s, assert via channel logs that ≥1 heartbeat fired and was acked.
- Hot-edit prompt to `"Reply: standup time"`, `vystak apply`, assert
  channel container restarted (hash changed).
- Wait next minute, assert message posted to chat scope with
  `"standup time"`.
- `vystak destroy` (handled by `project` fixture).

Skipped in CI default; runs locally with the marker. ~90s, no external services beyond Docker.

### Out of scope for v1 tests

- Slack/Discord cells with heartbeat (`post_reply` already exercised by `test_multi_channel`).
- Cross-restart "no catch-up" assertion (documented; would need a 2-minute test).
- Concurrent user turn vs heartbeat race (no coordination promised).

## Documentation

New page `docs/heartbeat.md`:
- Quick start using the example agent.
- Default prompt + ack contract (`HEARTBEAT_OK`, `ack_max_chars` semantics).
- `HEARTBEAT.md` convention with a small sample.
- Custom prompt examples (digest, monitoring, scheduled summary).
- Operational notes: restart behavior, timezone handling, `skip_when_busy` scope.

## Open questions

None. All design choices made during brainstorming.
