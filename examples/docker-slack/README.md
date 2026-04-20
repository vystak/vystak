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

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...

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
