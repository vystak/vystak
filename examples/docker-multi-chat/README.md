# docker-multi-chat example

Two agents (weather, time) + one chat channel routing to both. The chat
container exposes a single OpenAI-compatible endpoint; the `model` field
picks which agent answers.

## Run

```bash
export ANTHROPIC_API_KEY=sk-ant-...

cd examples/docker-multi-chat
vystak apply

# Check the deployment
curl -s http://localhost:18080/health | jq
curl -s http://localhost:18080/v1/models | jq

# Talk to the weather agent
curl -s -X POST http://localhost:18080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "vystak/weather-agent",
    "messages": [{"role": "user", "content": "whats the weather in tokyo?"}]
  }' | jq

# Talk to the time agent
curl -s -X POST http://localhost:18080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "vystak/time-agent",
    "messages": [{"role": "user", "content": "what time is it?"}]
  }' | jq

# Streaming version
curl -N -X POST http://localhost:18080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "vystak/weather-agent",
    "messages": [{"role": "user", "content": "weather in berlin"}],
    "stream": true
  }'
```

## Tear down

```bash
vystak destroy
```

## What's running

| Container | Role | Port |
|---|---|---|
| `vystak-weather-agent` | LangGraph agent with `get_weather` tool | 8000 (internal) |
| `vystak-time-agent` | LangGraph agent with `get_time` tool | 8000 (internal) |
| `vystak-channel-chat` | OpenAI-compatible chat router | 18080 (host) |

The chat container resolves agent URLs via Docker's network DNS on the
shared `vystak-net` network (e.g. `http://vystak-weather-agent:8000`).
These URLs are baked into the chat container's `routes.json` at
`vystak apply` time.
