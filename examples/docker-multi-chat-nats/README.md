# Docker multi-chat (NATS transport)

Mirror of `examples/docker-multi-chat` with `Transport(type="nats")` declared
on the platform. Proves the transport abstraction: same agents, same chat
channel, same OpenAI-compatible endpoint — but A2A traffic flows over NATS
JetStream instead of HTTP.

## What gets deployed

- `vystak-nats` — NATS server container (`nats:2.10-alpine` with JetStream).
- `vystak-time-agent`, `vystak-weather-agent` — agents speaking A2A over NATS
  subjects like `vystak-nats.multi-nats.agents.time-agent.tasks`.
- `vystak-channel-chat` — OpenAI-compatible endpoint on `localhost:18080`
  that dispatches to agents through the shared `NatsTransport`.

## Deploy

```bash
export ANTHROPIC_API_KEY=...  # required
uv run vystak apply --file examples/docker-multi-chat-nats/vystak.py
```

## Verify

```bash
# Agent env has NATS config:
docker exec vystak-time-agent env | grep VYSTAK_
# Expected: VYSTAK_TRANSPORT_TYPE=nats, VYSTAK_NATS_URL=nats://vystak-nats:4222

# Chat endpoint works (routes through NATS):
curl -s http://localhost:18080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"vystak/time-agent","messages":[{"role":"user","content":"what time is it?"}]}'

# Watch NATS activity (if the nats CLI is installed inside the container):
docker exec vystak-nats ls /data
```

## Tear down

```bash
uv run vystak destroy --file examples/docker-multi-chat-nats/vystak.py
```
