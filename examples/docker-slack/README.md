# docker-slack example

Slack channel with **self-serve runtime routing**. Deploys:

- `weather-agent` — LangChain agent container on Docker
- `slack-main` — Slack Socket Mode runner container that:
  - greets each new channel with a welcome message + slash-command help
  - persists `(team, channel) → agent` and `(team, user) → agent` bindings to a SQLite file at `/data/channel-state.db` on a named volume
  - dispatches messages via the resolver chain: deploy-time channel override → runtime `/vystak route` binding → `default_agent`

## Prereqs

1. Create a Slack app (https://api.slack.com/apps) with:
   - **Socket Mode** enabled
   - **Bot scopes**: `app_mentions:read`, `chat:write`, `commands`, `im:history`, `im:read`, `im:write`, `channels:read`, `groups:read`
   - **Event subscriptions** (Socket Mode): `app_mention`, `message.channels`, `message.im`, `member_joined_channel`
   - **Slash command** `/vystak` with usage hint `route <agent> | prefer <agent> | status | unroute | unprefer`
   - A bot token (`xoxb-...`) and an app-level token (`xapp-...`)
2. Install the app to your workspace.
3. Invite the bot to any channel — no channel IDs in the YAML are required.

## Run

```bash
cp .env.example .env  # then edit
cd examples/docker-slack
vystak apply
```

In Slack, invite the bot to a channel. Because this example declares only one routable agent, the channel **auto-binds** on invite — the bot will post a welcome and start handling `@mention`s right away. With more than one agent, users run `/vystak route <agent>` to pick.

```
/vystak route weather-agent
/vystak status
@weather-agent what's the weather like?
```

DMs use a per-user preference (`/vystak prefer weather-agent`); without one set, they fall through to `default_agent` (or the only declared agent when there's exactly one).

## Configuration knobs (optional)

In `vystak.py` / `vystak.yaml`:

```python
slack = ast.Channel(
    ...,
    agents=[weather_agent, support_agent],
    default_agent=weather_agent,           # DM fallback
    route_authority="inviter",             # | "admins" | "anyone"
    welcome_on_invite=True,
    welcome_message="...{agent_mentions}...",
    channel_overrides={
        "C12345678": ast.SlackChannelOverride(
            agent=support_agent,
            system_prompt="Triage first.",
            tools=["create_ticket", "search_kb"],
        ),
    },
    # state defaults to SQLite at /data/channel-state.db. Override:
    # state=ast.Service(type="postgres", connection_string_env="SLACK_STATE_URL"),
)
```

## Tear down

```bash
vystak destroy                            # preserves bindings
vystak destroy --delete-channel-data      # also wipes the state volume
```
