# Slack Self-Serve Routing — Design

**Date:** 2026-04-24
**Status:** Approved
**Supersedes:** the deploy-time `routes=[RouteRule(...)]` model in
`vystak.schema.channel.Channel` for `type: slack`.

## Goal

Replace deploy-time channel-ID hardcoding with a self-serve runtime model:
the bot greets each new channel with instructions, users pin a channel to
an agent via a slash command, and bindings persist across container
restarts. Deploy-time pinning + per-channel behavior overrides remain
available for cases where config-as-code is preferred.

## Why

Today every Slack channel needs its `Cxxxxxxxxxx` ID hand-copied into
`vystak.yaml`/`vystak.py` before deploy. Adding a new channel requires a
redeploy. This is brittle, terrible for multi-tenant workspaces, and not
how any other production Slack bot works.

## Schema

```yaml
channels:
  - name: slack-main
    type: slack
    platform: local
    secrets:
      - {name: SLACK_BOT_TOKEN}
      - {name: SLACK_APP_TOKEN}

    agents: [weather-agent, support-agent, docs-agent]

    # Policy gates — is this surface allowed to interact at all?
    group_policy: open       # open | allowlist | disabled
    dm_policy: open          # open | allowlist | disabled
    allow_from: []           # user IDs for allowlist policies
    allow_bots: false
    dangerously_allow_name_matching: false

    # Conversation conventions (orthogonal to routing)
    reply_to_mode: first     # off | first | all | batched
    thread_require_explicit_mention: false

    # Deploy-time per-channel overrides — pinning AND behavior shaping.
    # If `agent` is set here, runtime binding is overridden for this
    # channel. Other fields apply regardless of how the agent is chosen.
    channel_overrides:
      C12345678:
        agent: support-agent
        require_mention: true
        users: [U87654321]
        system_prompt: "You're in #support. Always triage first."
        tools: [create_ticket, search_kb]
        skills: [support]

    # Persistent state for runtime bindings + user prefs. Omit → SQLite at
    # /data/channel-state.db (provider mounts a named volume at /data).
    state: {type: sqlite, path: /data/channel-state.db}
    # Or: {type: postgres, connection_string_env: SLACK_STATE_URL}
    # Or: {type: postgres, name: slack-state-db}  # provider-managed

    # Who can run /vystak route and /vystak prefer.
    route_authority: inviter   # inviter | admins | anyone

    # Resolution fallback (no chain — just three levels)
    default_agent: weather-agent
    # ai_fallback: {type: llm_router, model: sonnet}    # optional

    # Onboarding UX
    welcome_on_invite: true
    welcome_message: |
      I'm Vystak. Routing options:
      • @mention an agent: {agent_mentions}
      • /vystak route <agent>  — pin this channel
      • /vystak prefer <agent> — personal default (DMs)
      • /vystak status         — show current routing
```

### Minimal form (single-agent, defaults everywhere)

```yaml
channels:
  - name: slack-main
    type: slack
    platform: local
    secrets:
      - {name: SLACK_BOT_TOKEN}
      - {name: SLACK_APP_TOKEN}
    agents: [weather-agent]
```

Implied defaults: `group_policy=open`, `dm_policy=open`,
`reply_to_mode=first`, `state=sqlite:/data/channel-state.db`,
`default_agent=agents[0]`, `welcome_on_invite=true`,
auto-generated `welcome_message`.

### Python form

```python
slack = ast.Channel(
    name="slack-main",
    type=ast.ChannelType.SLACK,
    platform=platform,
    secrets=[
        ast.Secret(name="SLACK_BOT_TOKEN"),
        ast.Secret(name="SLACK_APP_TOKEN"),
    ],
    agents=[weather_agent, support_agent, docs_agent],

    group_policy=ast.Policy.OPEN,
    dm_policy=ast.Policy.OPEN,

    channel_overrides={
        "C12345678": ast.SlackChannelOverride(
            agent=support_agent,
            system_prompt="You're in #support. Always triage first.",
            tools=["create_ticket", "search_kb"],
        ),
    },

    # state defaults to SQLite at /data/channel-state.db when omitted
    route_authority="inviter",
    default_agent=weather_agent,
    welcome_on_invite=True,
)
```

## Resolution

A pure function, ~12 lines, no pluggable steps:

```python
def resolve(event, cfg, store):
    if not policy_allows(event, cfg): return None
    if not sender_allowed(event, cfg): return None

    if event.is_dm:
        return store.user_pref(event.team, event.user) or cfg.default_agent

    cid = event.channel_id
    ov = cfg.channel_overrides.match(cid)   # exact, then glob (if enabled)
    if ov and ov.agent:
        return ov.agent                     # deploy-time pin short-circuits
    if binding := store.channel_binding(event.team, cid):
        return binding                      # /vystak route
    if cfg.ai_fallback:
        return cfg.ai_fallback.pick(event, cfg.agents)
    return cfg.default_agent                # may be None → welcome
```

Thread continuity is **not** routing. It's session continuity: once an
agent answers in a thread, the session key
`agent:<agentId>:slack:channel:<channelId>:thread:<threadTs>` keeps that
agent's context for any reply in that thread, regardless of what `resolve`
returns. Resolve still runs but its result is overridden when an in-flight
thread session exists. (Mirrors openclaw's session convention.)

## Slash commands

Handled by the channel container, not the agent.

| Command | Effect | Authorization |
|---|---|---|
| `/vystak route <agent>` | Set `(team, channel) → agent` in store | `route_authority` |
| `/vystak prefer <agent>` | Set `(team, user) → agent` in store | the user themself |
| `/vystak status` | Show resolved agent + binding source for this channel | anyone |
| `/vystak unroute` | Remove channel binding | `route_authority` |
| `/vystak unprefer` | Remove user pref | the user themself |

`route_authority="inviter"` resolves via `member_joined_channel` event for
the bot — whichever user invited the bot is the authority. Stored next to
the binding in the same SQLite/Postgres tables.

## Welcome UX

On `member_joined_channel` for the bot:

1. Post `welcome_message` (templated; `{agent_mentions}` expands to the
   agents list as backtick-quoted names).
2. If `agents` has exactly one entry and no `channel_overrides` block
   targets this channel, auto-bind to that single agent and DM the
   inviter "auto-bound to @weather-agent — change with /vystak route".
3. Otherwise wait for explicit `/vystak route` or an `@<agent>` mention.

If a message arrives in an unbound channel before `/vystak route` runs:
post the welcome message inline and route to `default_agent` if set,
otherwise drop with no reply (and a debug log line).

## State store

Schema (SQLite or Postgres):

```sql
CREATE TABLE channel_bindings (
  team_id     TEXT NOT NULL,
  channel_id  TEXT NOT NULL,
  agent_name  TEXT NOT NULL,
  inviter_id  TEXT,                -- whoever set the binding
  created_at  TIMESTAMP NOT NULL,
  PRIMARY KEY (team_id, channel_id)
);

CREATE TABLE user_prefs (
  team_id     TEXT NOT NULL,
  user_id     TEXT NOT NULL,
  agent_name  TEXT NOT NULL,
  created_at  TIMESTAMP NOT NULL,
  PRIMARY KEY (team_id, user_id)
);

CREATE TABLE inviters (
  team_id     TEXT NOT NULL,
  channel_id  TEXT NOT NULL,
  user_id     TEXT NOT NULL,        -- who invited the bot
  joined_at   TIMESTAMP NOT NULL,
  PRIMARY KEY (team_id, channel_id)
);
```

State backend:
- **Default** (`state` omitted): `Service(type="sqlite", path="/data/channel-state.db")`. Channel container Dockerfile declares `VOLUME /data`; provider mounts a named volume there.
- **Custom SQLite path**: `Service(type="sqlite", path="...")`.
- **External Postgres**: `Service(type="postgres", connection_string_env="X")`.
- **Provider-managed Postgres**: `Service(type="postgres", name="slack-state-db")` — same pattern as `sessions`/`memory` on agents. Provider provisions and injects the connection string as a secret env.

`vystak destroy` preserves the channel volume / DB by default;
`--delete-channel-data` removes it. Mirrors `--delete-workspace-data`.

## Migration from deploy-time `routes=[]`

The current schema:

```yaml
channels:
  - name: slack-main
    routes:
      - match: {slack_channel: C12345678}
        agent: weather-agent
      - match: {dm: true}
        agent: weather-agent
```

becomes:

```yaml
channels:
  - name: slack-main
    agents: [weather-agent]
    channel_overrides:
      C12345678: {agent: weather-agent}
    default_agent: weather-agent     # covers DMs and any other channel
```

Two approaches:
1. **Hard cut**: drop `routes` entirely, add the new fields. Existing
   `examples/docker-slack/` updated to the new shape. One commit.
2. **Soft cut with deprecation**: keep `routes` parsing for one release,
   emit a deprecation warning, plan removal in the next.

Recommendation: **hard cut**. Vystak hasn't shipped a stable release;
nobody has prod deploys depending on the existing `routes` shape.

## Out of scope

- Multi-replica channel containers (would force Postgres for state coordination).
- Cross-environment binding sharing (dev and prod against the same Slack workspace).
- LLM router selecting from agents not in `agents[]` (always restricted to the declared list).
- Block Kit / interactive UI for routing (a `/vystak route` modal would be nicer than a slash arg, but command-line first).
- Per-DM thread continuity (DMs don't have threads in the same sense; user_pref + session key cover the case).
- Discord, Teams, etc. — same model can apply but each has its own welcome / slash-command surface; out of scope here.

## Risks

- **State drift on `vystak destroy` then re-apply**: if `--delete-channel-data` is forgotten, old bindings come back when the channel app redeploys with the same volume name. Documented; `vystak channels list-routes <name>` (later) will help audit.
- **`route_authority="inviter"` ambiguity**: the bot may be invited to a channel and then the inviter leaves the workspace. Behavior: existing bindings remain valid; new `/vystak route` calls fall back to `admins` if the original inviter is no longer in the workspace. (Detail to confirm in implementation.)
- **`{agent_mentions}` template injection**: `welcome_message` is operator-controlled, not user-input. Safe.

## Validation / test plan

1. **Schema tests** — load `examples/docker-slack/vystak.yaml` (post-migration), confirm Pydantic shape; confirm `routes` field is rejected with a clear deprecation error.
2. **Resolution tests** — table-driven test of `resolve()` covering policy gates, channel overrides, runtime bindings, user prefs, default fallback, and ai_fallback.
3. **Store tests** — SQLite migrations, idempotent inserts, cross-process visibility.
4. **Slash command tests** — `/vystak route` → store write → next message routes correctly. Authorization rejected when sender isn't the inviter.
5. **Welcome flow tests** — `member_joined_channel` event triggers welcome post; single-agent auto-bind path.
6. **End-to-end** (docker-marked) — deploy `examples/docker-slack/`, invite bot to a real Slack channel, run `/vystak route`, send a message, verify routing.
