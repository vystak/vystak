---
title: Agents
sidebar_label: Agents
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Agents

An **agent** is the central deployable unit in Vystak. An agent definition declares which model to use, what tools the agent has, how it persists state, and what backing services it needs. **Channels** (Slack, chat, Discord, webhook) are top-level deployables that route to one or more agents — they're not declared on the agent itself.

This page walks through the full agent schema using a working example.

## A complete agent

Here's a chatbot with persistent conversation memory backed by Postgres:

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
name: sessions-agent
instructions: |
  You are a helpful assistant with persistent memory of our conversation.
  If the user has told you something before, remember it.
  Refer back to earlier parts of the conversation when relevant.
default_model:
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
secrets:
  - name: ANTHROPIC_API_KEY
port: 8091
```

</TabItem>
<TabItem value="python" label="Python">

```python
import vystak

anthropic = vystak.Provider(name="anthropic", type="anthropic")
docker = vystak.Provider(name="docker", type="docker")

model = vystak.Model(
    name="minimax",
    provider=anthropic,
    model_name="MiniMax-M2.7",
    parameters={
        "temperature": 0.7,
        "anthropic_api_url": "https://api.minimax.io/anthropic",
    },
)

agent = vystak.Agent(
    name="sessions-agent",
    instructions=(
        "You are a helpful assistant with persistent memory of our conversation.\n"
        "If the user has told you something before, remember it.\n"
        "Refer back to earlier parts of the conversation when relevant."
    ),
    default_model=model,
    platform=vystak.Platform(name="docker", type="docker", provider=docker),
    sessions=vystak.Postgres(provider=docker),
    secrets=[vystak.Secret(name="ANTHROPIC_API_KEY")],
    port=8091,
)
```

</TabItem>
</Tabs>

Run it with `vystak apply` and Vystak will:
1. Provision a Postgres container.
2. Build the agent image with the Postgres checkpointer wired up.
3. Run the agent container on the shared `vystak-net` Docker network, exposing the A2A endpoint on `port`.

Conversations persist across restarts. Send the same `session_id` and the agent picks up where it left off.

## Required fields

The minimum agent has just two fields — `name` and `default_model`:

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
name: bare-bot
default_model:
  name: claude
  provider:
    name: anthropic
    type: anthropic
  model_name: claude-sonnet-4-20250514
```

</TabItem>
<TabItem value="python" label="Python">

```python
import vystak

agent = vystak.Agent(
    name="bare-bot",
    default_model=vystak.Model(
        name="claude",
        provider=vystak.Provider(name="anthropic", type="anthropic"),
        model_name="claude-sonnet-4-20250514",
    ),
)
```

</TabItem>
</Tabs>

- `name` — used as the container/app name and as the OpenAI-compatible model ID
- `default_model` — which LLM to call. See [Models](/docs/concepts/models)

Everything else is optional. Every agent automatically exposes an A2A (agent-to-agent) JSON-RPC endpoint on its HTTP port; no channel declaration is required to make the agent reachable in-cluster.

### Model pool

An agent can carry additional models beyond the default in `models:`. Names must be unique across `default_model` and `models`. Callers can pick a model per turn (and the choice is pinned to the session), which is how heartbeats and cost-tiered routing select cheaper or stronger models:

```yaml
default_model:
  name: sonnet
  provider: {name: anthropic, type: anthropic}
  model_name: claude-sonnet-4-20250514
models:
  - name: haiku
    provider: {name: anthropic, type: anthropic}
    model_name: claude-haiku-4-5-20251001
```

## Adding skills

A **skill** is a named capability. It comes in two forms:

- a **folder skill** — packaged instructions in `skills/<name>/SKILL.md`
  next to your `vystak.yaml`, loaded by the agent on demand
- an **inline skill** — a named bundle of tools (Python functions the
  agent can call), optionally with a short prompt

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
skills:
  - research                 # folder skill: skills/research/SKILL.md
  - name: ops                # inline skill: tool bundle
    tools:
      - lookup_order
      - process_refund
    prompt: Always verify the order before processing refunds.
```

</TabItem>
<TabItem value="python" label="Python">

```python
skills = [
    "research",              # folder skill: skills/research/SKILL.md
    vystak.Skill(
        name="ops",
        tools=["lookup_order", "process_refund"],
        prompt="Always verify the order before processing refunds.",
    ),
]
```

</TabItem>
</Tabs>

### Folder skills

A folder skill lives at `skills/<name>/SKILL.md` with YAML frontmatter:

```markdown
---
name: research
description: Product-research workflow — how to compare and cite sources.
tools: [web_search]        # optional, resolved from tools/
---
When asked to research a topic, follow this process...
```

`description` is required — it is the only thing the agent sees before
deciding to use the skill. The folder can hold extra resource files
(reference docs, templates) alongside SKILL.md.

At runtime the agent gets **progressive disclosure**: its system prompt
lists each skill's name and description, and two auto-provided tools —
`load_skill(name)` and `read_skill_file(skill, path)` — fetch the full
instructions and resource files only when needed. Editing any file in the
skill folder changes the agent's content hash, so `vystak plan` shows a
redeploy.

### Inline skills and tools

Tools are Python functions that live in a `tools/` directory next to your
`vystak.yaml`; each tool name maps to `tools/<name>.py` exporting a
function of the same name.

```python
# tools/lookup_order.py
from langchain_core.tools import tool

@tool
def lookup_order(order_id: str) -> str:
    """Look up an order by ID."""
    return f"Order {order_id}: shipped"
```

An inline skill's `prompt` field is appended to the agent's system prompt.

See `examples/docker-skills/` for a working project using both forms.

## Adding sessions (conversation memory)

Vystak supports three session backends:

| Engine | When to use |
|--------|-------------|
| (none — default) | Stateless agents; in-memory state lost on restart |
| `sqlite` | Single-instance agents that need persistence; backed by a Docker volume |
| `postgres` | Production; multi-instance and survives container replacement |

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
sessions:
  type: postgres
  provider:
    name: docker
    type: docker
```

</TabItem>
<TabItem value="python" label="Python">

```python
sessions = vystak.Postgres(provider=docker)
```

</TabItem>
</Tabs>

The Docker provider auto-provisions a Postgres container the first time. Connection string is injected into the agent as `SESSION_STORE_URL`.

To bring your own Postgres (e.g., a managed instance) instead of letting Vystak provision one:

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
sessions:
  type: postgres
  connection_string_env: DATABASE_URL
```

</TabItem>
<TabItem value="python" label="Python">

```python
sessions = vystak.Postgres(connection_string_env="DATABASE_URL")
```

</TabItem>
</Tabs>

The agent then reads `DATABASE_URL` from its environment.

## Adding long-term memory

Sessions remember a single conversation. **Memory** persists facts across all conversations for a given user:

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
memory:
  type: postgres
  provider:
    name: docker
    type: docker
```

</TabItem>
<TabItem value="python" label="Python">

```python
memory = vystak.Postgres(provider=docker)
```

</TabItem>
</Tabs>

When `memory` is set, the generated agent gets two extra tools: `save_memory` and `forget_memory`. The agent learns to use them based on context (you can also nudge it via `instructions`).

## Adding services

Use `services` for any other backing infrastructure:

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

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

</TabItem>
<TabItem value="python" label="Python">

```python
services = [
    vystak.Redis(name="cache", provider=docker),
    vystak.Qdrant(name="vectors", provider=docker),
]
```

</TabItem>
</Tabs>

Each service gets a connection string in the agent's environment (`<NAME>_URL`).

See [Services](/docs/concepts/services) for the full list of supported types.

## Adding a workspace

When an agent needs file I/O, shell access, or git operations, declare a [workspace](/docs/concepts/workspaces) — a standalone container the agent drives over SSH (JSON-RPC via an SSH subsystem), keeping tool execution isolated from the agent process:

<Tabs groupId="config-format">
<TabItem value="yaml" label="YAML" default>

```yaml
workspace:
  name: dev
  image: python:3.12-slim
  provision:
    - apt-get update && apt-get install -y git ripgrep
  persistence: volume
skills:
  - name: editing
    tools: [fs.readFile, fs.writeFile, fs.edit, exec.run, git.status]
```

</TabItem>
<TabItem value="python" label="Python">

```python
workspace = vystak.Workspace(
    name="dev",
    image="python:3.12-slim",
    provision=["apt-get update && apt-get install -y git ripgrep"],
    persistence="volume",
)
skills = [
    vystak.Skill(
        name="editing",
        tools=["fs.readFile", "fs.writeFile", "fs.edit", "exec.run", "git.status"],
    ),
]
```

</TabItem>
</Tabs>

Built-in `fs.*`, `exec.*`, `git.*`, and `search_project` tools become available — see [Workspaces](/docs/concepts/workspaces). Workspaces run on Docker and Azure Container Apps; on ACA, `persistence: volume` is backed by Azure Files (`bind` is rejected — there's no host filesystem).

## Adding subagents

An agent can declare **subagents** — full agent definitions it can delegate to. The parent gets a call tool per subagent, and calls flow over the same A2A transport as any agent-to-agent traffic:

```yaml
agents:
  - name: orchestrator
    default_model: sonnet
    platform: local
    subagents: [researcher, writer]
  - name: researcher
    default_model: sonnet
    platform: local
  - name: writer
    default_model: sonnet
    platform: local
```

Subagent names must be unique and an agent cannot reference itself. See [Multi-agent](/docs/concepts/multi-agent) for routing, session continuity, and restrictive-routing patterns.

## Exposing the agent through a channel

Channels are **top-level deployables** that route inbound traffic to one or more agents. They are siblings of agents in the multi-document layout, not nested fields. Here's a Slack channel routing to a single agent:

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
  - name: support-bot
    instructions: You are a customer support agent.
    default_model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}

channels:
  - name: slack-main
    type: slack
    platform: local
    secrets:
      - {name: SLACK_BOT_TOKEN}
      - {name: SLACK_APP_TOKEN}
    agents: [support-bot]
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

support = vystak.Agent(
    name="support-bot",
    instructions="You are a customer support agent.",
    default_model=sonnet,
    platform=local,
    secrets=[vystak.Secret(name="ANTHROPIC_API_KEY")],
)

slack = vystak.Channel(
    name="slack-main",
    type=vystak.ChannelType.SLACK,
    platform=local,
    secrets=[
        vystak.Secret(name="SLACK_BOT_TOKEN"),
        vystak.Secret(name="SLACK_APP_TOKEN"),
    ],
    agents=[support],
)
```

</TabItem>
</Tabs>

A channel with multiple `agents:` enables [self-serve routing](/docs/channels/slack) — the channel's runtime resolves which agent answers per Slack channel, with optional `default_agent`, `channel_overrides`, and `group_policy`/`dm_policy` gates.

See [Channels overview](/docs/channels/overview) for the full list of channel types (`slack`, `chat`, `discord`, `api`, `webhook`, `voice`, `cron`, `widget`).

## Multiline instructions

The `instructions` field is the agent's system prompt. You can use multiline strings, template variables, and reference per-skill prompts that get appended automatically.

```yaml
instructions: |
  You are a customer support agent for ACME Corp.
  Be concise and friendly.
  When handling refunds, follow the company refund policy.
```

## Python definition

YAML is the simple on-ramp. For programmatic agents, define them in Python in `vystak.py`:

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
    default_model=model,
    platform=vystak.Platform(name="docker", type="docker", provider=docker),
    sessions=vystak.Postgres(provider=docker),
    skills=[vystak.Skill(name="support", tools=["lookup_order", "process_refund"])],
)
```

Vystak picks up `vystak.yaml`, `vystak.yml`, or `vystak.py` automatically, and collects **every** module-level `Agent` in the Python form — so one file can define a whole fleet. The Python form earns you loops, conditionals, type checking, and reusable agent factories.

## Hash-based change detection

Vystak content-hashes your agent definition. `vystak apply` compares the new hash to the deployed hash and skips deploys that wouldn't change anything. To force a redeploy:

```bash
vystak apply --force
```

## What's next

- [Workspaces](/docs/concepts/workspaces) — standalone execution environments and built-in `fs.*`/`exec.*`/`git.*` tools
- [Multi-agent](/docs/concepts/multi-agent) — subagents, delegation, and routing
- [Models](/docs/concepts/models) — supported model providers and parameters
- [Services](/docs/concepts/services) — backing infrastructure types
- [Channels](/docs/channels/overview) — Slack, chat, Discord, and more
- [Transport](/docs/concepts/transport) — east-west messaging (HTTP, NATS) for A2A calls
- [Examples](/docs/examples/overview) — agents from minimal to multi-agent collaboration
- [Deploying to Docker](/docs/deploying/docker) — how `vystak apply` works under the hood
