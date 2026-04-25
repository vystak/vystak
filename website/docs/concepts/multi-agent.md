---
title: Multi-agent
sidebar_label: Multi-agent
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Multi-agent

A multi-agent system is two or more agents that talk to each other. In Vystak, every agent automatically exposes an A2A (agent-to-agent) JSON-RPC endpoint, and the [transport](/docs/concepts/transport) layer hands every container a route table — so an agent calls a peer by *name*, not by URL.

This page covers three common shapes:

1. **Specialist + coordinator** — one agent delegates to focused peers via `ask_agent()`.
2. **Channel fan-out** — a single channel routes user traffic to multiple agents (Slack self-serve routing, OpenAI-compatible model picker).
3. **Mesh** — agents call each other in arbitrary patterns over the same transport.

## When to split

Splitting an agent into peers is worth the extra container if you have:

- **Distinct skill domains** with non-overlapping tool sets (weather lookups vs. ticket triage vs. SQL).
- **Different models** per role (cheap fast model for a router, premium model for the specialist).
- **Independent deployment cadences** — one agent re-deployed shouldn't churn the others.
- **Different secret scopes** — the specialist holds the production API key; the coordinator never sees it.

Don't split for organisation alone — multiple skills inside one agent is cheaper and faster.

## Specialist + coordinator

The simplest pattern: a coordinator declares its peers via `subagents:`. Vystak auto-generates an `ask_<peer>` tool for each one — no hand-written delegation files, no manual `ask_agent()` calls.

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}

platforms:
  local: {type: docker, provider: docker}

models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-4-20250514

agents:
  - name: weather-agent
    instructions: You are a weather specialist. Use get_weather for real data.
    model: sonnet
    platform: local
    skills:
      - {name: weather, tools: [get_weather]}
    secrets:
      - {name: ANTHROPIC_API_KEY}

  - name: time-agent
    instructions: You are a time specialist. Use get_time.
    model: sonnet
    platform: local
    skills:
      - {name: time, tools: [get_time]}
    secrets:
      - {name: ANTHROPIC_API_KEY}

  - name: assistant-agent
    instructions: |
      You are a coordinator. For weather questions call ask_weather_agent;
      for time questions call ask_time_agent. When asked about both,
      call both tools and synthesise a single concise reply.
    model: sonnet
    platform: local
    subagents: [weather-agent, time-agent]
    secrets:
      - {name: ANTHROPIC_API_KEY}
```

</TabItem>
<TabItem value="python" label="Python">

```python
import vystak

docker = vystak.Provider(name="docker", type="docker")
anthropic = vystak.Provider(name="anthropic", type="anthropic")
local = vystak.Platform(name="local", type="docker", provider=docker)
sonnet = vystak.Model(
    name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514",
)

weather = vystak.Agent(
    name="weather-agent",
    instructions="You are a weather specialist. Use get_weather for real data.",
    model=sonnet,
    platform=local,
    skills=[vystak.Skill(name="weather", tools=["get_weather"])],
    secrets=[vystak.Secret(name="ANTHROPIC_API_KEY")],
)

time = vystak.Agent(
    name="time-agent",
    instructions="You are a time specialist. Use get_time.",
    model=sonnet,
    platform=local,
    skills=[vystak.Skill(name="time", tools=["get_time"])],
    secrets=[vystak.Secret(name="ANTHROPIC_API_KEY")],
)

assistant = vystak.Agent(
    name="assistant-agent",
    instructions=(
        "You are a coordinator. For weather questions call ask_weather_agent; "
        "for time questions call ask_time_agent. When asked about both, "
        "call both tools and synthesise a single concise reply."
    ),
    model=sonnet,
    platform=local,
    subagents=[weather, time],
    secrets=[vystak.Secret(name="ANTHROPIC_API_KEY")],
)
```

</TabItem>
</Tabs>

`vystak apply` builds three containers, computes a per-caller route table (only the assistant can reach `weather-agent` and `time-agent` — the specialists can't reach each other unless they declare `subagents:` of their own), and the LangChain adapter generates two `@tool` functions on the coordinator:

```python
# generated — do not edit
@tool
async def ask_weather_agent(question: str, config: RunnableConfig) -> str:
    """You are a weather specialist. Use get_weather for real data."""
    session_id = (config.get('configurable') or {}).get('thread_id')
    metadata = {'sessionId': session_id} if session_id else {}
    return await ask_agent('weather-agent', question, metadata=metadata)
```

The tool's docstring is taken from the peer's `instructions` (first paragraph, 200-char cap), so the LLM sees what each peer does when picking which to call.

### Session continuity across hops

The coordinator's active session id propagates to every peer it calls via `metadata.sessionId`. The receiving agent uses that id as its own LangGraph `thread_id` — so each peer maintains a private, correlated conversation history under the same id. The coordinator never sees the peer's chain of thought; the peer never sees the coordinator's chat with the human; but a second call from the same Slack thread or chat session reaches the same per-peer thread and remembers what was said before.

Sub-subagent calls (e.g., a peer that itself declares `subagents:`) inherit the id transitively — every hop's auto-generated tool reads its current `thread_id` and propagates.

### Escape hatch: hand-written delegation tools

When the auto-generated docstring isn't right (e.g., per-caller customisation, parameter shaping, structured arguments beyond a single `question` string), bypass auto-generation and write the tool yourself.

The langchain adapter raises a `ValueError` at codegen time if a user tool name collides with an auto-generated `ask_<peer>` name — that protects you from accidental shadowing but also means you cannot simply drop a `tools/ask_weather_agent.py` alongside `subagents: [weather-agent]` and expect it to override. The two are mutually exclusive: either Vystak generates the tool, or you do.

To take ownership of the delegation tool:

1. **Remove the peer from `subagents:`** so codegen no longer emits `ask_<peer>`.
2. **Write the manual tool** in `tools/`. The transport routes are still scoped by what's left in `subagents:`, so you'll need to keep the peer there OR use a different routing approach. The simplest path is to keep the peer in `subagents:` and rename your tool to avoid the auto-generated name (e.g., `ask_weather_with_region`):

```python
# tools/ask_weather_with_region.py
from vystak.transport import ask_agent

async def ask_weather_with_region(question: str, region: str = "global") -> str:
    """Ask the weather specialist, scoped to a region."""
    return await ask_agent(
        "weather-agent",
        f"[region={region}] {question}",
    )
```

This sits alongside the auto-generated `ask_weather_agent` (declared via `subagents: [weather-agent]`); both are available to the LLM, with their docstrings disambiguating intent. Restrictive routing is satisfied because `weather-agent` is in `subagents:`.

## Channel fan-out

To expose the system to humans, attach a [channel](/docs/channels/overview) and list every agent users can pick:

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
channels:
  - name: chat
    type: chat
    platform: local
    config: {port: 18080}
    agents: [weather-agent, time-agent, assistant-agent]
```

</TabItem>
<TabItem value="python" label="Python">

```python
chat = vystak.Channel(
    name="chat",
    type=vystak.ChannelType.CHAT,
    platform=local,
    config={"port": 18080},
    agents=[weather, time, assistant],
)
```

</TabItem>
</Tabs>

The chat channel exposes an OpenAI-compatible endpoint at `http://localhost:18080`. Clients select which agent answers via the `model` field:

```bash
curl http://localhost:18080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "vystak/assistant-agent",
    "messages": [{"role": "user", "content": "weather and time in Tokyo?"}]
  }'
```

For Slack, use `type: slack` instead — users pick agents per Slack channel via `/vystak route <agent>` (see [Slack channel](/docs/channels/slack)).

## Switching to NATS

When you want east-west traffic to flow over NATS instead of HTTP, declare it on the platform — no agent code changes:

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
platforms:
  local:
    type: docker
    provider: docker
    transport:
      type: nats
      config:
        subject_prefix: myapp
```

</TabItem>
<TabItem value="python" label="Python">

```python
local = vystak.Platform(
    name="local",
    type="docker",
    provider=docker,
    transport=vystak.Transport(
        name="bus",
        type="nats",
        config=vystak.NatsConfig(subject_prefix="myapp"),
    ),
)
```

</TabItem>
</Tabs>

`vystak apply --force` rebuilds containers with `vystak-transport-nats` installed and brings up a `vystak-nats` container on `vystak-net`. `ask_agent("weather-agent", ...)` now publishes to a NATS subject; the queue group ensures exactly-once delivery to one healthy replica.

See [Transport](/docs/concepts/transport) for the full transport reference and [`examples/docker-multi-chat-nats/`](https://github.com/vystak/vystak/tree/main/examples/docker-multi-chat-nats).

## Mesh patterns

The route table is bidirectional — any agent can call any peer. Common patterns:

| Pattern | Shape | Notes |
|---------|-------|-------|
| **Hub-and-spoke** | Coordinator → specialists | The example above. Coordinator owns user-facing instructions; specialists are leaf agents. |
| **Pipeline** | A → B → C | Each agent's output becomes the next agent's input. Useful for retrieve → reason → write workflows. |
| **Peer mesh** | Any-to-any | Agents call each other based on conversation state. Higher coordination cost; only when roles genuinely interleave. |
| **Swarm** | Coordinator → many specialists in parallel | Use `asyncio.gather(ask_agent(...), ask_agent(...))` in the coordinator's tool to fan out concurrently. |

Each shape is implemented the same way: tool functions calling `ask_agent()`. The transport handles addressing, retries, and reply correlation.

## Sessions across agents

Each agent owns its session store. When a coordinator calls a specialist via `ask_agent()`, the call carries a fresh session unless the coordinator's tool propagates one explicitly.

For continuity across hops (e.g., "remember what the user said three turns ago, even when the specialist answers"), pass the session id through the call:

```python
from vystak.transport import ask_agent

async def ask_weather_agent(question: str, session_id: str | None = None) -> str:
    return await ask_agent(
        "weather-agent",
        question,
        metadata={"sessionId": session_id} if session_id else {},
    )
```

The langchain adapter exposes the active `session_id` to tools via context — propagate it to keep specialist conversations correlated with the originating user thread.

## Naming and namespaces

Each agent's canonical name is `{name}.agents.{namespace}`, where `namespace` defaults to the platform's namespace (or `default`). The route table keys on the **short name** within a namespace — so `ask_agent("weather-agent")` works as long as `weather-agent` is unique in the platform.

Use distinct platform namespaces to deploy isolated multi-agent systems on the same Docker host:

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
platforms:
  staging: {type: docker, provider: docker, namespace: staging}
  prod:    {type: docker, provider: docker, namespace: prod}
```

</TabItem>
<TabItem value="python" label="Python">

```python
staging = vystak.Platform(
    name="staging", type="docker", provider=docker, namespace="staging",
)
prod = vystak.Platform(
    name="prod", type="docker", provider=docker, namespace="prod",
)
```

</TabItem>
</Tabs>

Both namespaces can host a `weather-agent` without name collisions; container names are derived from the canonical name.

## Hash-based redeploys

Each agent hashes independently. Editing one agent's instructions or tools triggers a redeploy of *that* container only — peers stay running. The route table is recomputed and re-injected when the topology changes (agent added/removed/renamed).

## What's next

- [Transport](/docs/concepts/transport) — HTTP vs. NATS, A2A envelope, contract testing
- [Channels overview](/docs/channels/overview) — exposing the system to users
- [Slack self-serve routing](/docs/channels/slack) — per-Slack-channel agent picking
- [`examples/multi-agent/`](https://github.com/vystak/vystak/tree/main/examples/multi-agent) — coordinator + two specialists over HTTP
- [`examples/docker-multi-chat-nats/`](https://github.com/vystak/vystak/tree/main/examples/docker-multi-chat-nats) — same shape over NATS
- [`examples/docker-slack/`](https://github.com/vystak/vystak/tree/main/examples/docker-slack) — Slack channel routing to two agents
