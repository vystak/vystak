---
title: Chat
sidebar_label: Chat
sidebar_position: 3
---

# Chat channel

A **`type: chat`** channel deploys a single FastAPI container exposing OpenAI-compatible HTTP endpoints. Any client that speaks the OpenAI Chat Completions API — `curl`, the `openai` Python SDK, Cline, Continue, LibreChat, etc. — can talk to your agents over it. Multiple agents share one endpoint; the client picks which agent to call by setting `model="vystak/<agent-name>"`.

## Quick start

```yaml
agents:
  - name: weather-agent
    instructions: You are a weather specialist. Answer concisely.
    model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}

channels:
  - name: chat
    type: chat
    platform: local
    agents: [weather-agent]
    config: {port: 8080}
```

```bash
vystak apply
curl -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "vystak/weather-agent",
    "messages": [{"role":"user","content":"What is the weather like today?"}]
  }'
```

## Endpoints

The chat channel container exposes:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness; returns `{"status":"ok","agents":[...]}`  |
| `GET /v1/models` | OpenAI-compatible model list. Each declared agent appears as `id="vystak/<agent-name>"` |
| `POST /v1/chat/completions` | Chat completions; supports `stream=true` for SSE token streaming |
| `POST /v1/responses` | OpenAI Responses API; A2A-native (no translation layer) |
| `GET /v1/responses/{id}` | Responses retrieval |

The model field selects the agent: `model="vystak/weather-agent"` dispatches to `weather-agent` via A2A.

## Schema

```yaml
channels:
  - name: chat                          # required
    type: chat                          # required
    platform: <platform-ref>            # required
    agents: [agent-a, agent-b]          # required: routable agents
    config:
      port: 8080                        # default 8080
    secrets: []                         # usually none — model creds live on agents
```

The chat channel itself doesn't hold credentials. Each declared agent's secrets (e.g. `ANTHROPIC_API_KEY`) are wired into the agent container at apply time; the chat channel only needs to know how to *reach* the agents over the internal A2A network.

## How clients pick an agent

Set `model` to `vystak/<agent-short-name>`:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-required",
)

response = client.chat.completions.create(
    model="vystak/weather-agent",
    messages=[{"role": "user", "content": "what's the weather?"}],
)
print(response.choices[0].message.content)
```

Streaming works the same way:

```python
stream = client.chat.completions.create(
    model="vystak/weather-agent",
    messages=[{"role": "user", "content": "explain in detail..."}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

`GET /v1/models` enumerates every routable agent so OpenAI-compatible UIs can show a model picker:

```json
{
  "object": "list",
  "data": [
    {"id": "vystak/weather-agent", "object": "model", "owned_by": "vystak"},
    {"id": "vystak/support-agent", "object": "model", "owned_by": "vystak"}
  ]
}
```

## Multi-agent example

```yaml
agents:
  - name: weather-agent
    model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}

  - name: support-agent
    model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}

channels:
  - name: chat
    type: chat
    platform: local
    agents: [weather-agent, support-agent]
    config: {port: 8080}
```

Same `:8080/v1/chat/completions` endpoint, two different `model` values, two distinct agent containers behind the scenes.

## Sessions

Pass an OpenAI-compatible `user` field (or a `session_id` parameter your agent's session-store reads) to bind a conversation:

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "vystak/weather-agent",
    "messages": [{"role":"user","content":"hi"}],
    "user": "alice"
  }'
```

If the agent declares `sessions: {type: postgres, ...}`, conversations persist across restarts. See [Services](../concepts/services) for session-store options.

## A2A under the hood

A `POST /v1/chat/completions` request to the chat channel container becomes:

```
client                 chat container               agent container
  │                          │                           │
  │ POST /v1/chat/completions│                           │
  ├─────────────────────────►│                           │
  │                          │ A2A: tasks/send           │
  │                          ├──────────────────────────►│
  │                          │                           │ run langgraph
  │                          │ A2A: result               │
  │                          │◄──────────────────────────┤
  │ OpenAI ChatCompletion    │                           │
  │◄─────────────────────────┤                           │
```

For `/v1/responses` the chat channel skips the translation step — agents already emit response objects natively over A2A.

## NATS variant

For multi-channel deployments where you don't want HTTP between containers, declare NATS transport at the platform level:

```yaml
platforms:
  local:
    type: docker
    provider: docker
    transport:
      type: nats
```

`vystak apply` provisions a NATS server and the chat channel uses NATS subjects instead of HTTP for its A2A calls. Client-facing HTTP (`/v1/chat/completions`) is unchanged. See [`examples/docker-multi-chat-nats/`](https://github.com/vystak/vystak/tree/main/examples/docker-multi-chat-nats).

## Lifecycle

```bash
vystak apply        # build + run the chat channel container alongside agents
vystak status       # confirm running and agents reachable
vystak destroy      # stop and remove the channel container
```

The chat channel is stateless — no `--delete-channel-data` flag because there's nothing to persist.

## Health and observability

```bash
curl http://localhost:8080/health
# {"status":"ok","agents":["weather-agent","support-agent"]}
```

Container logs show every request:

```bash
docker logs -f vystak-channel-chat 2>&1
```

## See also

- [`examples/docker-chat/`](https://github.com/vystak/vystak/tree/main/examples/docker-chat) — single-agent demo
- [`examples/docker-multi-chat/`](https://github.com/vystak/vystak/tree/main/examples/docker-multi-chat) — multi-agent over HTTP
- [`examples/docker-multi-chat-nats/`](https://github.com/vystak/vystak/tree/main/examples/docker-multi-chat-nats) — multi-agent over NATS
- [`examples/azure-chat/`](https://github.com/vystak/vystak/tree/main/examples/azure-chat) — same shape on Azure Container Apps
- [Slack channel →](./slack)
