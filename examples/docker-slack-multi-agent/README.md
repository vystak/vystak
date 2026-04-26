# docker-slack-multi-agent

Three agents (`weather-agent`, `time-agent`, `assistant-agent`) plus one Slack
channel. Exercises the new "agent threads" follow-the-thread behavior:
once an agent replies in a Slack thread, subsequent messages in that thread
route to the same agent without re-mention.

## Topology

- `weather-agent` calls the local `get_weather` tool (wttr.in, no API key).
- `time-agent` calls the local `get_time` tool (system clock).
- `assistant-agent` declares `subagents: [weather-agent, time-agent]`, which
  auto-generates `ask_weather_agent` / `ask_time_agent` A2A delegation tools.
  It's the default agent for the Slack channel.

## Run

```bash
ln -sf ../../.env .env       # symlink the repo-root .env
vystak apply
```

In Slack, invite the bot to a channel. The bot welcomes and (since this has
multiple agents) the channel-binding goes to the `default_agent`:
`assistant-agent`. Then:

```
@<bot> what's the weather in Lisbon and the time?
```

The assistant calls both subagents in parallel, returns one reply. Now reply
in that thread without mentioning the bot:

```
and how about Berlin weather?
```

The bot replies again — that's the new agent-threads feature.

## Cleanup

```bash
vystak destroy
```
