# docker-chat example

Minimum smoke test for the channel-as-top-level-deployable architecture.

Deploys one agent and one `ChannelType.CHAT` channel. The chat container
exposes an OpenAI-compatible endpoint on port 8080 and proxies completions
to the agent via A2A on the shared `vystak-net` Docker network.

## Run

```bash
export ANTHROPIC_API_KEY=sk-ant-...

cd examples/docker-chat
vystak apply

# Test the chat endpoint
curl -s http://localhost:8080/health

curl -s -X POST http://localhost:8080/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "vystak/weather-agent",
        "messages": [{"role": "user", "content": "hi"}]
    }'

# Tear down
vystak destroy
```

## What happens

1. CLI loads `vystak.py`, sees one agent + one channel.
2. `weather-agent` container is built and started as `vystak-weather-agent` on port 8000.
3. CLI resolves route: `weather-agent → http://vystak-weather-agent:8000`.
4. Chat plugin generates a FastAPI app with that route baked into `routes.json`.
5. `vystak-channel-chat` container is built, started as `vystak-channel-chat`, host port 8080.
6. Incoming `POST /v1/chat/completions` parses `model="vystak/weather-agent"`, proxies to the agent's `/a2a` endpoint, translates the response.
