# test-multi-channel

End-to-end smoke for the channel-runtime + Discord branch:
3 agents (assistant + weather + time) reachable via 3 channels
(Chat HTTP API, Slack, Discord) on a single local Docker deploy.

## Setup

```bash
# Symlink to the repo root .env (which has ANTHROPIC_API_KEY,
# SLACK_BOT_TOKEN, SLACK_APP_TOKEN, DISCORD_BOT_TOKEN).
ln -s ../../.env .env
```

## Deploy

```bash
uv run vystak apply
```

Brings up 6 Docker containers:
- `vystak-weather-agent`, `vystak-time-agent`, `vystak-assistant-agent` (agents)
- `vystak-channel-chat-api` on host port 8080
- `vystak-channel-slack-main` on 8081 (Socket Mode — no inbound port needed)
- `vystak-channel-discord-main` on 8082 (gateway WebSocket — same)

## Test the Chat HTTP API

```bash
# Direct to time-agent
curl -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"vystak/time-agent","messages":[{"role":"user","content":"what time is it?"}]}'

# Direct to weather-agent
curl -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"vystak/weather-agent","messages":[{"role":"user","content":"weather in Paris?"}]}'

# Through the assistant (it routes to the right subagent)
curl -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"vystak/assistant-agent","messages":[{"role":"user","content":"what time is it AND weather in Tokyo?"}]}'
```

## Test Slack / Discord

@-mention the bot in a Slack channel where it's been invited, or DM it.
Same for Discord — mention the bot user in any guild channel where it's
a member, or DM it.

## Tear down

```bash
uv run vystak destroy
```
