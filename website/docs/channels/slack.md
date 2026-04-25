---
title: Slack
sidebar_label: Slack
sidebar_position: 2
---

# Slack channel

A **`type: slack`** channel deploys a Slack Socket Mode runner that:

- Greets each new channel with a welcome message naming the routable agents
- Persists per-channel and per-user bindings to a SQLite file on a named volume (or external Postgres)
- Dispatches messages via a single resolution function — deploy-time channel pin → runtime `/vystak route` binding → user preference (DMs) → optional LLM router → `default_agent`
- Optionally pulls thread context via Slack's [`conversations.replies`](https://docs.slack.dev/reference/methods/conversations.replies/) on cold-start mentions
- Handles slash commands `/vystak route|prefer|status|unroute|unprefer` for self-serve runtime routing

## Quick start

The minimal Slack channel with a single agent:

```yaml
agents:
  - name: weather-agent
    model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}

channels:
  - name: slack-main
    type: slack
    platform: local
    secrets:
      - {name: SLACK_BOT_TOKEN}
      - {name: SLACK_APP_TOKEN}
    agents: [weather-agent]
```

With one declared agent, the channel auto-binds on bot invite and falls back to that agent for DMs without a user preference. No slash commands required for the trivial case.

For multiple agents, every Slack channel must be explicitly bound:

```yaml
channels:
  - name: slack-main
    type: slack
    platform: local
    secrets:
      - {name: SLACK_BOT_TOKEN}
      - {name: SLACK_APP_TOKEN}
    agents: [weather-agent, support-agent, docs-agent]
    # Optional deploy-time pin (overrides any runtime binding)
    channel_overrides:
      C12345678:
        agent: support-agent
        system_prompt: "In #support, always triage first."
        tools: [create_ticket, search_kb]
```

## Slack app setup

Create the bot once at https://api.slack.com/apps. Required configuration:

**Socket Mode** — enabled.

**OAuth & Permissions → Bot Token Scopes:**
- `app_mentions:read` — receive `@bot` events in channels
- `chat:write` — post replies
- `commands` — handle `/vystak` slash command
- `im:history`, `im:read`, `im:write` — DMs
- `channels:read`, `groups:read` — resolve channel names
- `reactions:write` — optional, for the in-flight 🕒/✅/⚠️ reactions

**Event Subscriptions → Subscribe to bot events:**
- `app_mention`
- `message.channels`
- `message.im`
- `member_joined_channel` — required for the welcome + auto-bind flow

**Slash Commands → Create New Command:**
- Command: `/vystak`
- Request URL: leave blank (Socket Mode handles it)
- Short description: `Vystak agent routing`
- Usage hint: `route <agent> | prefer <agent> | status | unroute | unprefer`

After changing scopes, **reinstall the app to your workspace** to get a new bot token. Copy the bot token (`xoxb-…`) and the app-level token (`xapp-…`) into your `.env`.

## Schema

Full surface, every field optional unless marked:

```yaml
channels:
  - name: slack-main                    # required
    type: slack                         # required
    platform: <platform-ref>            # required

    secrets:                            # required: SLACK_BOT_TOKEN + SLACK_APP_TOKEN
      - {name: SLACK_BOT_TOKEN}
      - {name: SLACK_APP_TOKEN}

    agents: [agent-a, agent-b]          # required: which agents are routable

    # --- Resolution fallback ---
    default_agent: agent-a              # used when nothing else binds; auto = single agent
    ai_fallback:                        # optional LLM router before default_agent
      type: llm_router
      model: sonnet

    # --- Deploy-time pinning + per-channel behaviour ---
    channel_overrides:
      C12345678:                        # exact Slack channel ID
        agent: agent-a                  # short-circuits the resolver
        system_prompt: "..."            # per-channel system prompt
        tools: [tool-a, tool-b]         # restrict tools in this channel
        skills: [skill-a]               # restrict skills in this channel
        users: [U987]                   # per-channel sender allowlist
        require_mention: true           # only respond to explicit @mentions

    # --- Policy gates (mirrors openclaw) ---
    group_policy: open                  # open | allowlist | disabled
    dm_policy: open                     # open | allowlist | disabled
    allow_from: [U987]                  # user IDs for allowlist policies
    allow_bots: false
    dangerously_allow_name_matching: false  # use channel names instead of IDs

    # --- Conversation conventions ---
    reply_to_mode: first                # off | first | all | batched
    reply_to_mode_by_chat_type:         # per-type override
      direct: off
      channel: first
    thread:
      history_scope: thread             # thread | off
      initial_history_limit: 20         # 0 disables conversations.replies fetch
      inherit_parent: false             # reserved
      require_explicit_mention: false

    # --- Runtime state ---
    state:                              # default: SQLite at /data/channel-state.db
      type: sqlite
      path: /data/channel-state.db
    # Or external Postgres:
    # state:
    #   type: postgres
    #   connection_string_env: SLACK_STATE_URL

    # --- Authority ---
    route_authority: inviter            # inviter | admins | anyone

    # --- Onboarding UX ---
    welcome_on_invite: true
    welcome_message: |
      I'm Vystak. Routing options:
      • @mention an agent: {agent_mentions}
      • `/vystak route <agent>` — pin this channel
      • `/vystak prefer <agent>` — your personal default (DMs)
      • `/vystak status` — show current routing
```

## Resolution algorithm

A pure function evaluated per inbound event:

```
1. Policy gate
   - group_policy/dm_policy disabled  → drop silently
   - allowlist + user not in allow_from → drop silently
   - bot message + allow_bots=false → drop

2. DM
   - return user_pref(team, user) ?? default_agent

3. Channel message
   - channel_overrides[<channel_id>].agent  → use it (deploy-time pin)
   - runtime channel_binding(team, channel) → use it (/vystak route)
   - ai_fallback                            → ask the router LLM
   - default_agent                          → fall back

4. None of the above → post welcome_message + drop
```

Thread session continuity is **not** routing. Once an agent answers in a thread, subsequent replies inside that thread stay with the same agent via the session key `agent:<id>:slack:channel:<channel_id>:thread:<thread_ts>`, regardless of what step 3 returns.

## Slash commands

The bot's container handles these inline (no agent involvement):

| Command | Effect | Authorization |
|---|---|---|
| `/vystak route <agent>` | Pin `(team, channel) → agent` | `route_authority` |
| `/vystak unroute` | Clear the channel binding | `route_authority` |
| `/vystak prefer <agent>` | Set personal `(team, user) → agent` (DMs) | the user themself |
| `/vystak unprefer` | Clear personal preference | the user themself |
| `/vystak status` | Show resolved agent + binding source | anyone |

`route_authority="inviter"` (the default) records whoever ran `/invite @<bot>` in the channel and only lets that user run `route` / `unroute`. `admins` requires Slack workspace admin (TODO; falls back to inviter today). `anyone` opens routing to every channel member.

## Welcome flow

On the `member_joined_channel` event for the bot:

1. The bot's own user ID is resolved at startup via Slack's `auth.test` API.
2. Channel inviter is recorded in the SQLite store (used by `route_authority="inviter"`).
3. `welcome_message` is posted in the channel with `{agent_mentions}` substituted to backtick-quoted agent names.
4. **Single-agent shortcut**: if `agents` has exactly one entry, the bot also auto-binds the channel to it — no `/vystak route` needed.

## Thread context

When the bot is `@mentioned` inside an existing thread (i.e. the event has a `thread_ts` distinct from its own `ts`), the runtime calls `conversations.replies` to fetch prior messages and prepends them to the agent's input wrapped in `<thread_history>...</thread_history>`. Bot's own past replies are labeled `bot` so the agent can distinguish them from user input.

**Follow-the-thread behavior** — Once the bot has replied in a thread, every subsequent non-bot message in that thread is forwarded to the same agent without requiring re-mention. Each Slack thread is its own conversation session (the agent's session key is `slack:<channel>:<thread_ts>`), so memory stays scoped to the thread. Mentioning a different `@<agent>` inside the thread does **not** transfer the binding — the bound agent reads the new message verbatim and decides what to do.

To require an explicit `@mention` on every message and disable thread following:

```yaml
thread:
  require_explicit_mention: true
```

Disable per channel:

```yaml
thread:
  history_scope: off            # disables the fetch
  # OR
  initial_history_limit: 0      # equivalent
```

Limit per channel:

```yaml
thread:
  initial_history_limit: 5      # only fetch most recent 5 prior messages
```

## State and persistence

The Slack channel container ships with `VOLUME /data`. The Docker provider mounts a named volume `vystak-<channel>-state` there automatically. SQLite tables (`channel_bindings`, `user_prefs`, `inviters`) are migrated on startup.

Override the location:

```yaml
state:
  type: sqlite
  path: /data/custom/slack.db
```

Move to Postgres (required for multi-replica channels — out of scope today):

```yaml
state:
  type: postgres
  connection_string_env: SLACK_STATE_URL
# Or provider-managed:
state:
  type: postgres
  name: slack-state-db
```

## Destroy semantics

```bash
vystak destroy                              # stops + removes channel container; volume preserved
vystak destroy --delete-channel-data        # also removes vystak-<channel>-state volume — wipes bindings + prefs
```

Mirrors `--delete-workspace-data` for workspace volumes.

## Multi-agent routing example

Two agents, channel-pinned per use case, A2A delegation between agents:

```yaml
agents:
  - name: weather-agent
    instructions: You are a weather specialist.
    model: sonnet
    platform: local
    skills: [{name: weather, tools: []}]
    secrets:
      - {name: ANTHROPIC_API_KEY}

  - name: assistant-agent
    instructions: |
      Friendly general-purpose assistant. For weather questions call
      ask_weather_agent and return the reply verbatim.
    model: sonnet
    platform: local
    skills:
      - {name: general, tools: [ask_weather_agent]}
    secrets:
      - {name: ANTHROPIC_API_KEY}

channels:
  - name: slack-main
    type: slack
    platform: local
    secrets:
      - {name: SLACK_BOT_TOKEN}
      - {name: SLACK_APP_TOKEN}
    agents: [weather-agent, assistant-agent]
```

Add `tools/ask_weather_agent.py` next to `vystak.yaml`:

```python
"""Delegate a weather question to the peer weather-agent via A2A."""

from vystak.transport import ask_agent


async def ask_weather_agent(question: str) -> str:
    """Ask the weather specialist agent a question."""
    return await ask_agent("weather-agent", question)
```

`vystak apply` builds both agents and the Slack channel, populates each agent's peer-route table (`VYSTAK_ROUTES_JSON`), and the LangChain adapter discovers `ask_weather_agent` from `tools/` and binds it as a `@tool` on assistant-agent. In Slack: `/vystak route assistant-agent` in any channel, then ask anything — weather questions transparently delegate to weather-agent.

See [`examples/docker-slack/`](https://github.com/vystak/vystak/tree/main/examples/docker-slack) for the full working example.

## Health and observability

```bash
curl http://localhost:8080/health
# {"status":"ok","agents":["weather-agent","assistant-agent"],"socket_mode":true}
```

Container logs include a Slack-event middleware that prints every inbound event:

```
slack event=app_mention channel=C... user=U...
mention resolve channel=C... user=U... text='...' -> agent=weather-agent
mention forward agent=weather-agent session=slack:C...:1745596...
```

Useful filter:

```bash
docker logs -f vystak-channel-slack-main 2>&1 | \
  grep -E "mention|dm |thread_history|welcome|member_joined|forward|resolve|command"
```

## Known limitations

- **Single-replica only.** Multi-replica Slack channel containers would need to coordinate routing state via Postgres (the SQLite default is single-process). The schema supports the swap; the runtime hasn't been hardened for multi-replica yet.
- **`route_authority="admins"`** falls back to inviter-only today. A real `users.info` admin check is a TODO.
- **`reply_to_mode` and `reply_to_mode_by_chat_type`** are stored in `channel_config.json` but the runtime currently always replies "first" (bot reply on the originating thread/message). Honoring these knobs is future work.
