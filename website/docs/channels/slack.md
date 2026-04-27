---
title: Slack
sidebar_label: Slack
sidebar_position: 2
---

# Slack channel

A **`type: slack`** channel deploys a Slack Socket Mode runner that:

- Greets each new channel with a welcome message naming the routable agents
- Persists per-channel, per-user, and per-thread bindings to a SQLite file on a named volume (or external Postgres)
- Dispatches messages via a single resolution function — thread binding → deploy-time channel pin → runtime `/vystak route` binding → user preference (DMs) → optional LLM router → `default_agent`
- Follows threads after first reply: once an agent answers in a thread, every subsequent message in that thread routes to the same agent without re-mention
- Treats each Slack thread as its own conversation session (`slack:<channel>:<thread_ts>`)
- Scopes long-term memory per Slack user **and** per Slack channel — channel-shared facts (`scope="project"`) recall across users and threads in the same channel
- Optionally pulls thread context via Slack's [`conversations.replies`](https://docs.slack.dev/reference/methods/conversations.replies/) on cold-start mentions
- Handles slash commands `/vystak route|prefer|status|unroute|unprefer` for self-serve runtime routing
- Flattens GFM markdown tables into em-dash-joined lines so they render readably in Slack mrkdwn

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

    config:                             # optional channel-runtime knobs
      stream_tool_calls: false          # see "Tool-call streaming" below

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
   - thread_binding(team, channel, thread_ts) → use it (sticky thread)
   - channel_overrides[<channel_id>].agent  → use it (deploy-time pin)
   - runtime channel_binding(team, channel) → use it (/vystak route)
   - ai_fallback                            → ask the router LLM
   - default_agent                          → fall back

4. None of the above → post welcome_message + drop
```

Thread bindings are sticky: once an agent has replied in a thread, that thread is bound to the same agent (`team`, `channel`, `thread_ts`) → `agent_name`. The binding is consulted before resolving any later mention in the thread, and is also the gate that lets non-mention messages in the thread route to the bound agent (see [Thread context](#thread-context)). The session key is `slack:<channel>:<thread_ts>`, so memory stays scoped to the thread regardless of how the agent was first chosen.

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

## Tool-call streaming

When the agent invokes tools — e.g. delegating to a peer agent (`ask_weather_agent`), calling an MCP server, or hitting an external API — the user otherwise sees a single placeholder message until the final reply arrives. For multi-tool turns this looks identical to a stalled run.

Set `config.stream_tool_calls: true` to surface a live progress trail instead:

```yaml
channels:
  - name: slack-main
    type: slack
    config:
      stream_tool_calls: true
    # ...
```

While the agent works, the bot's reply message edits live to show:

```
🔧 *ask_weather_agent*
🔧 *ask_time_agent*
_Working..._
```

…and as each tool finishes:

```
🔧 *ask_weather_agent* ✓ _(2.1s)_
🔧 *ask_time_agent* ✓ _(0.4s)_
_Working..._
```

When the agent emits its final reply, the entire trail is replaced by the reply text in a single `chat.update`.

Mechanics:

- Edits are **rate-limited to ≤ 1/sec per turn** to honour Slack's tier-3 `chat.update` cap. Updates within the throttle window coalesce; the final update is exempt.
- **No tool arguments or return values are shown** — only the tool name + duration. Privacy-sensitive content (user IDs, addresses, API responses) doesn't appear in the trail.
- **Errors** replace the trail with the same `Sorry, I hit an error talking to *<agent>*: …` text the non-streaming path uses.
- DMs intentionally stay one-shot in v1 — only `app_mention` and follow-the-thread paths are streamed.

Default `false` preserves today's one-shot UX exactly. Switching the flag is a non-disruptive opt-in: agents that don't fire tools render a single edit (just the final reply) regardless.

## Memory namespacing

When the agent has `sessions:` and/or `memory:` configured, every message from Slack carries metadata that scopes memory writes/recall to the right namespace:

| Metadata field | Slack value | Memory namespace |
|---|---|---|
| `sessionId` | `slack:<channel>:<thread_ts>` (thread) or `slack:dm:<user>` (DM) | LangGraph checkpointer thread ID — chat-history continuity within a single thread or DM |
| `user_id` | `slack:<U_user>` | `("user", "slack:U...", "memories")` — personal facts (the user's name, role, preferences). Scoped to one Slack user across every channel and thread. |
| `project_id` | `slack:<team>:<channel>` (channel messages only; `None` in DMs) | `("project", "slack:T...:C...", "memories")` — shared facts. Every member of the same Slack channel sees these on recall regardless of which thread or user is asking. |

The agent's `save_memory` tool takes a `scope` argument (`"user"` / `"project"` / `"global"`) and the runtime routes each save into the matching namespace.

**Example interaction:**

```
[in #engineering, thread A]
@VyStack our deploy schedule is Tuesdays at 10am
→ saves to ("project", "slack:T123:Cengineering", "memories")

[in #engineering, thread B, different user]
@VyStack when do we deploy?
→ recalls "deploy schedule is Tuesdays at 10am" — the project memory
  is shared across users and threads inside the same channel.

[in #engineering, same user]
@VyStack my name is Anatoly
→ saves to ("user", "slack:UANATOLY", "memories")

[any channel, same user]
@VyStack do you know my name?
→ recalls "Anatoly" — user memory follows the user across channels.
```

**Prompt nudge.** A capable model (Claude, MiniMax) chooses the right scope from the wording — "my X is Y" → user, "we / our / the team's X" → project. Make this explicit in the agent's `instructions:` to reduce variance:

```yaml
instructions: |
  ...
  When the user shares a personal fact about themselves, call save_memory
  with scope="user". When they share a fact about the team, the channel
  topic, conventions, deployment schedule, or anything the whole channel
  should remember, use scope="project". Don't ask permission — just save
  and confirm.
```

See `examples/docker-slack-multi-agent/` for a full working example with both scopes wired up.

**DMs** carry no `project_id` — there is no shared "channel" in a DM, so saves with `scope="project"` will silently no-op when triggered from a DM. Use `scope="user"` in DMs.

## State and persistence

The Slack channel container ships with `VOLUME /data`. The Docker provider mounts a named volume `vystak-<channel>-state` there automatically. SQLite tables (`channel_bindings`, `user_prefs`, `inviters`, `thread_bindings`) are migrated on startup.

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

Three agents — a generalist `assistant-agent` that fans out to specialist `weather-agent` and `time-agent` peers via A2A. The `subagents` field auto-generates `ask_<peer>_agent` delegation tools — no `tools/ask_*.py` files required.

```yaml
agents:
  - name: weather-agent
    instructions: |
      You are a weather specialist. Use get_weather to fetch real data.
    model: sonnet
    platform: local
    skills:
      - {name: weather, tools: [get_weather]}
    secrets:
      - {name: ANTHROPIC_API_KEY}

  - name: time-agent
    instructions: You are a time specialist. Use get_time.
    model: sonnet
    platform: local
    skills:
      - {name: time, tools: [get_time]}
    secrets:
      - {name: ANTHROPIC_API_KEY}

  - name: assistant-agent
    instructions: |
      Friendly general-purpose assistant.
      For weather questions call ask_weather_agent.
      For time questions call ask_time_agent.
      For mixed questions call BOTH in parallel.
      Return each agent's reply verbatim.
    model: sonnet
    platform: local
    subagents: [weather-agent, time-agent]
    secrets:
      - {name: ANTHROPIC_API_KEY}

channels:
  - name: slack-main
    type: slack
    platform: local
    secrets:
      - {name: SLACK_BOT_TOKEN}
      - {name: SLACK_APP_TOKEN}
    agents: [assistant-agent, weather-agent, time-agent]
    default_agent: assistant-agent
```

Add the leaf agents' tools next to `vystak.yaml`:

```python
# tools/get_weather.py
import json
from urllib.request import urlopen

def get_weather(city: str) -> str:
    """Get current weather for a city via wttr.in (no API key needed)."""
    with urlopen(f"https://wttr.in/{city}?format=j1") as r:
        c = json.loads(r.read())["current_condition"][0]
        return f"{city}: {c['weatherDesc'][0]['value']}, {c['temp_C']}°C"
```

```python
# tools/get_time.py
from datetime import datetime, timezone

def get_time(location: str = "UTC") -> str:
    """Get the current UTC time."""
    return f"Current UTC time: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S UTC}"
```

`vystak apply` builds all three agents and the Slack channel, populates each agent's peer-route table (`VYSTAK_ROUTES_JSON`), and binds `ask_weather_agent` / `ask_time_agent` as A2A delegation tools on `assistant-agent`. Because `default_agent: assistant-agent` is set, every Slack channel auto-binds to the assistant on bot invite.

In Slack:

```
@<bot> what's the weather in Lisbon and the time?
```

The assistant calls both subagents in parallel and replies in a thread. Then in the same thread, no mention needed:

```
and how about Berlin weather?
```

The bot replies again — the thread is sticky-bound to `assistant-agent`. See [`examples/docker-slack-multi-agent/`](https://github.com/vystak/vystak/tree/main/examples/docker-slack-multi-agent) for the full working example, or [`examples/docker-slack/`](https://github.com/vystak/vystak/tree/main/examples/docker-slack) for a single-agent variant.

To enable cross-thread memory on the assistant, add `sessions:` (and optionally `memory:`):

```yaml
  - name: assistant-agent
    instructions: |
      ...your instructions, including the user/project scope guidance from
      "Memory namespacing" above...
    sessions:
      type: sqlite
      provider: {name: docker, type: docker}
    # Optional: postgres for long-term memory (see examples/memory-agent/).
    # memory:
    #   type: postgres
    #   provider: {name: docker, type: docker}
```

With `sessions:` set, the LangChain adapter auto-generates `save_memory` and `forget_memory` tools, and the Slack runtime's `user_id` / `project_id` metadata routes each save into the right namespace.

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
  grep -E "mention|dm |thread_history|thread-follow|welcome|member_joined|forward|resolve|command"
```

## Known limitations

- **Single-replica only.** Multi-replica Slack channel containers would need to coordinate routing state via Postgres (the SQLite default is single-process). The schema supports the swap; the runtime hasn't been hardened for multi-replica yet.
- **`route_authority="admins"`** falls back to inviter-only today. A real `users.info` admin check is a TODO.
- **`reply_to_mode` and `reply_to_mode_by_chat_type`** are stored in `channel_config.json` but the runtime currently always replies "first" (bot reply on the originating thread/message). Honoring these knobs is future work.
