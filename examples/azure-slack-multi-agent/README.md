# azure-slack-multi-agent

Same shape as `examples/docker-slack-multi-agent/` but deployed to Azure
Container Apps: 3 agents (weather, time, assistant) plus a Slack channel.

The assistant uses `subagents: [weather-agent, time-agent]` so the
LangChain adapter auto-generates `ask_weather_agent` /
`ask_time_agent` A2A delegation tools. Weather/time agents call local
`get_weather` / `get_time` tools.

## Prereqs

```bash
az login
export AZURE_SUBSCRIPTION_ID=<your-subscription-id>
```

Plus a Slack app with Socket Mode enabled (see `docs/channels/slack.md`)
and `ANTHROPIC_API_KEY` / `ANTHROPIC_API_URL` if you're routing through
a non-default Anthropic-compatible endpoint (e.g. MiniMax).

## Run

```bash
ln -sf ../../.env .env       # symlink the repo-root .env
vystak plan                   # ~30s — resolves resource group + ACR
vystak apply                  # ~5–8 min for cold deploy
```

The Azure provider provisions:
- One resource group (`vystak-slack-multi-rg`)
- Log Analytics workspace + ACA environment
- One ACR + image build per agent
- One Container App per agent + the Slack channel

When the Slack channel container starts, it establishes a Socket Mode
session and shows up in the channels you've invited the bot to.

## Cleanup

```bash
vystak destroy                # tears down the resource group
```

## Notes

- This example does NOT configure persistent `sessions:` or `memory:`.
  The LangChain adapter falls back to in-memory checkpointers, so chat
  history within a thread survives until the container restarts. To
  add durable memory on ACA, declare `memory:` (postgres only — ACA's
  serverless model doesn't fit sqlite's single-volume assumption);
  see `examples/azure-postgres-test/` for a sessions-on-postgres
  pattern that can be combined with this example.
- Compared to `examples/docker-slack-multi-agent/`, this swaps:
  - `provider: docker` → `provider: azure`
  - `platform: local` → `platform: aca` (`type: container-apps`)
  - `sessions: sqlite` removed (no per-container volume on ACA)
