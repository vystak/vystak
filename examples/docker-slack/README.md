# docker-slack example

Smoke test for the Slack channel plugin. Deploys:

- `weather-agent` — LangChain agent container on Docker
- `slack-main` — Slack Socket Mode runner container routing `@weather-agent`
  mentions and DMs to the agent via A2A

## Prereqs

1. Create a Slack app (https://api.slack.com/apps) with:
   - Socket Mode enabled
   - Bot scopes: `app_mentions:read`, `chat:write`, `im:history`,
     `im:read`, `im:write`
   - Event subscriptions (Socket Mode) for `app_mention` and `message.im`
   - A bot token (`xoxb-...`) and an app-level token (`xapp-...`)
2. Install the app to your workspace
3. Invite the bot into a channel, note its channel ID (`Cxxxx`)
4. Replace `C0000000000` in `vystak.py` with the real ID

## Run

Put the tokens in an `.env` file alongside `vystak.py` (or pass `--env-file`
pointing at your existing env file). `vystak apply` reads them from
`--env-file` (defaults to `.env` in the current directory).

```env
ANTHROPIC_API_KEY=sk-ant-...
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...

# Optional — only if you're routing the Anthropic SDK to a non-default
# endpoint such as MiniMax. If set, also add
# `ast.Secret(name="ANTHROPIC_API_URL")` to weather_agent.secrets in
# vystak.py so the value reaches the container.
# ANTHROPIC_API_URL=https://api.minimax.io/anthropic
```

```bash
cd examples/docker-slack
vystak apply
```

Then mention the bot in Slack:

```
@weather-agent what is the weather like?
```

Or DM the bot directly.

## Tear down

```bash
vystak destroy
```
