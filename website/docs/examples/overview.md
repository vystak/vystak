---
title: Examples
sidebar_label: Overview
---

# Examples

Working agent definitions you can clone and run. All examples live in the [`examples/` directory](https://github.com/vystak/AgentsStack/tree/main/examples) of the repository.

The four featured examples below cover the typical learning path: simplest possible agent → persistence → multi-agent collaboration → cloud deployment.

## Featured

### `minimal` — Hello World

The smallest possible agent: a model, instructions, and an API channel. No tools, no persistence. Use this to verify your install works and to get a feel for the deploy loop.

```yaml
name: minimal-agent
instructions: |
  You are a minimal agent. Just chat.
model:
  name: minimax
  provider: { name: anthropic, type: anthropic }
  model_name: MiniMax-M2.7
  parameters:
    anthropic_api_url: https://api.minimax.io/anthropic
platform:
  name: docker
  type: docker
  provider: { name: docker, type: docker }
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
port: 8090
```

**Run it:**
```bash
cd examples/minimal
export ANTHROPIC_API_KEY=...
vystak apply
vystak-chat --url http://localhost:8090
```

**What it teaches:** the minimal agent shape and the Vystak deploy loop.

---

### `sessions-postgres` — Persistent conversations

Same agent shape as `minimal`, but with `sessions: postgres`. Vystak provisions a Postgres container alongside the agent and wires up the LangGraph Postgres checkpointer. Conversations survive restarts.

```yaml
name: sessions-agent
instructions: |
  You are a helpful assistant with persistent memory of our conversation.
model: { ... }   # same as minimal
platform: { ... }
sessions:
  type: postgres
  provider:
    name: docker
    type: docker
channels:
  - name: api
    type: api
```

**Run it:**
```bash
cd examples/sessions-postgres
vystak apply
# Talk to it, exit, redeploy — your conversation is still there
```

**What it teaches:** session persistence and how Vystak provisions backing services automatically.

---

### `docker-compaction` — Long sessions without context overflow

Builds on `sessions-postgres`: same Postgres-backed agent, plus
[compaction](../concepts/compaction) so the conversation stays bounded
no matter how many turns it runs. The example uses an artificial 5K
context window and `trigger_pct: 0.3` so you can observe compaction
fire after ~5 turns instead of needing hundreds.

```yaml
agents:
  - name: chatty
    model: agent_model
    sessions:
      type: postgres
      provider: { name: docker, type: docker }
    compaction:
      mode: aggressive
      context_window: 5000
      trigger_pct: 0.3
      keep_recent_pct: 0.2
      summarizer:
        name: summarizer
        provider: { name: anthropic, type: anthropic }
        model_name: MiniMax-M2.7
        api_keys: { name: ANTHROPIC_API_KEY }
```

**Run it:**
```bash
cd examples/docker-compaction
cp .env.example .env  # then edit with your real keys
uv run vystak apply
# Drive a multi-turn conversation, then:
curl http://localhost:18080/v1/sessions/$THREAD/compactions | jq
```

**What it teaches:** the three-layer compaction model (pre-call prune,
threshold summarize, manual `/compact`), the `vystak_compactions`
inspection table, and the dev-tight knobs for fast iteration.

---

### `multi-agent` — A2A collaboration

Three agents in one deployment: a `weather` specialist, a `time` specialist, and an `assistant` that calls both. The assistant's tools (`ask_weather_agent`, `ask_time_agent`) use Vystak's A2A (agent-to-agent) protocol over HTTP.

Vystak deploys all three agents to the shared `vystak-net` Docker network and stands up a gateway that knows how to route to each one.

**Run it:**
```bash
cd examples/multi-agent
vystak apply weather time assistant
vystak-chat --gateway http://localhost:8080 \
  -p "Weather in NYC and what time is it there?"
```

The assistant calls weather and time in parallel, then synthesizes a single answer.

**What it teaches:** multi-agent orchestration, the A2A protocol, and the gateway.

---

### `azure-multi-agent` — Cloud deployment

The same multi-agent pattern, deployed to Azure Container Apps instead of Docker. The only difference from the Docker version is the `platform` and `provider` fields:

```yaml
platform:
  name: aca
  type: container-apps
  provider:
    name: azure
    type: azure
    config:
      location: eastus2
```

Vystak provisions a resource group, an Azure Container Registry, an ACA Environment, and the three Container Apps. Same agent definitions, different target.

**Run it:**
```bash
cd examples/azure-multi-agent
az login
vystak apply
```

**What it teaches:** that "define once, deploy everywhere" is real. The agent definitions are nearly identical to the Docker version.

---

## All examples

Beyond the featured four, the [`examples/` directory](https://github.com/vystak/AgentsStack/tree/main/examples) also includes:

- **`hello-agent`** — a slightly richer "hello world" with a couple of tools, useful for tinkering.
- **`code-first`** — the same agents defined in Python (`vystak.py`) instead of YAML.
- **`memory-agent`** — long-term memory across sessions (Postgres-backed).
- **`mcp-files`** — exposes a filesystem MCP server as agent tools.
- **`docker-slack`** / **`docker-slack-multi-agent`** — Slack channel exposing one or many agents over Socket Mode.
- **`azure-minimal`** — the simplest possible Azure deploy (single agent, no extras).
- **`azure-postgres-test`** — Azure Container App with a managed Postgres Flexible Server.
- **`azure-vault`** / **`azure-workspace-vault`** — full Azure Key Vault wiring (per-principal UAMI + Secrets User grants).
- **`azure-slack-multi-agent`** — the cloud-grade combo: Slack channel + KV + Postgres sessions + 3-agent A2A delegation, with `stream_tool_calls: true` for live tool-call progress.

Each is a standalone directory with its own `vystak.yaml` (or `vystak.py`).

## What's next

- [Quickstart](/docs/getting-started/quickstart) — the fastest path to your first deploy
- [Agents](/docs/concepts/agents) — the agent schema in depth
- [Deploying to Docker](/docs/deploying/docker) — multi-agent and gateway details
