---
title: Agents
sidebar_label: Agents
---

# Agents

An **agent** is the central deployable unit in Vystak. An agent definition declares which model to use, what tools the agent has, how it persists state, and how users reach it.

This page walks through the full agent schema using a working example.

## A complete agent

Here's a chatbot with persistent conversation memory backed by Postgres:

```yaml
name: sessions-agent
instructions: |
  You are a helpful assistant with persistent memory of our conversation.
  If the user has told you something before, remember it.
  Refer back to earlier parts of the conversation when relevant.
model:
  name: minimax
  provider:
    name: anthropic
    type: anthropic
  model_name: MiniMax-M2.7
  parameters:
    temperature: 0.7
    anthropic_api_url: https://api.minimax.io/anthropic
platform:
  name: docker
  type: docker
  provider:
    name: docker
    type: docker
sessions:
  type: postgres
  provider:
    name: docker
    type: docker
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
port: 8091
```

Run it with `vystak apply` and Vystak will:
1. Provision a Postgres container.
2. Build the agent image with the Postgres checkpointer wired up.
3. Run the agent container on the shared `vystak-net` Docker network.

Conversations persist across restarts. Send the same `session_id` and the agent picks up where it left off.

## Required fields

The minimum agent has just three fields:

```yaml
name: bare-bot
model:
  name: claude
  provider:
    name: anthropic
    type: anthropic
  model_name: claude-sonnet-4-20250514
channels:
  - name: api
    type: api
```

- `name` — used as the container/app name and as the OpenAI-compatible model ID
- `model` — which LLM to call. See [Models](/docs/concepts/models) (placeholder)
- `channels` — at least one channel; `api` is the simplest

Everything else is optional.

## Adding skills (tools)

A **skill** is a named bundle of tools (Python functions the agent can call):

```yaml
skills:
  - name: ops
    tools:
      - lookup_order
      - process_refund
    prompt: Always verify the order before processing refunds.
```

Tools are Python functions that live in a `tools/` directory next to your `vystak.yaml`. The first time you run `vystak apply`, Vystak scaffolds stub files for any tool referenced in `skills` that doesn't exist.

```python
# tools/lookup_order.py
def lookup_order(order_id: str) -> dict:
    """Look up an order by ID."""
    # Your implementation here
    return {"id": order_id, "status": "shipped"}
```

The `prompt` field is appended to the agent's instructions when this skill's tools are in use.

## Adding sessions (conversation memory)

Vystak supports three session backends:

| Engine | When to use |
|--------|-------------|
| (none — default) | Stateless agents; in-memory state lost on restart |
| `sqlite` | Single-instance agents that need persistence; backed by a Docker volume |
| `postgres` | Production; multi-instance and survives container replacement |

```yaml
sessions:
  type: postgres
  provider:
    name: docker
    type: docker
```

The Docker provider auto-provisions a Postgres container the first time. Connection string is injected into the agent as `SESSION_STORE_URL`.

To bring your own Postgres (e.g., a managed instance) instead of letting Vystak provision one:

```yaml
sessions:
  type: postgres
  connection_string_env: DATABASE_URL
```

The agent then reads `DATABASE_URL` from its environment.

## Adding long-term memory

Sessions remember a single conversation. **Memory** persists facts across all conversations for a given user:

```yaml
memory:
  type: postgres
  provider:
    name: docker
    type: docker
```

When `memory` is set, the generated agent gets two extra tools: `save_memory` and `forget_memory`. The agent learns to use them based on context (you can also nudge it via `instructions`).

## Adding services

Use `services` for any other backing infrastructure:

```yaml
services:
  - name: cache
    type: redis
    provider:
      name: docker
      type: docker
  - name: vectors
    type: qdrant
    provider:
      name: docker
      type: docker
```

Each service gets a connection string in the agent's environment (`<NAME>_URL`).

See [Services](/docs/concepts/services) (placeholder) for the full list of supported types.

## Adding channels

The `api` channel exposes the standard agent endpoints. To add Slack:

```yaml
channels:
  - name: api
    type: api
  - name: support-channel
    type: slack
    provider:
      name: my-slack
      type: slack
      gateway:
        name: main
      config:
        bot_token:
          name: SLACK_BOT_TOKEN
        signing_secret:
          name: SLACK_SIGNING_SECRET
    channels: ["#support"]
    listen: mentions
```

Slack channels go through the [gateway](/docs/deploying/gateway) (placeholder), which routes events to the right agent.

See [Channels](/docs/concepts/channels) (placeholder) for the full list of channel types.

## Multiple instructions

The `instructions` field is the agent's system prompt. You can use multiline strings, template variables, and reference per-skill prompts that get appended automatically.

```yaml
instructions: |
  You are a customer support agent for ACME Corp.
  Be concise and friendly.
  When handling refunds, follow the company refund policy.
```

## Python definition

YAML is the simple on-ramp. For programmatic agents, define them in Python:

```python
import vystak

anthropic = vystak.Provider(name="anthropic", type="anthropic")
docker = vystak.Provider(name="docker", type="docker")

model = vystak.Model(
    name="claude",
    provider=anthropic,
    model_name="claude-sonnet-4-20250514",
)

agent = vystak.Agent(
    name="support-bot",
    instructions="You are a helpful support agent.",
    model=model,
    platform=vystak.Platform(name="docker", type="docker", provider=docker),
    sessions=vystak.Postgres(provider=docker),
    skills=[vystak.Skill(name="support", tools=["lookup_order", "process_refund"])],
    channels=[vystak.Channel(name="api", type=vystak.ChannelType.API)],
)
```

Save as `vystak.py` (Vystak picks up either `vystak.yaml` or `vystak.py` automatically).

The advantage: loops, conditionals, type checking, and reusable agent factories.

## Hash-based change detection

Vystak content-hashes your agent definition. `vystak apply` compares the new hash to the deployed hash and skips deploys that wouldn't change anything. To force a redeploy:

```bash
vystak apply --force
```

## What's next

- [Models](/docs/concepts/models) (placeholder) — supported model providers and parameters
- [Services](/docs/concepts/services) (placeholder) — backing infrastructure types
- [Channels](/docs/concepts/channels) (placeholder) — REST, Slack, webhook, and more
- [Examples](/docs/examples/overview) — agents from minimal to multi-agent collaboration
- [Deploying to Docker](/docs/deploying/docker) — how `vystak apply` works under the hood
