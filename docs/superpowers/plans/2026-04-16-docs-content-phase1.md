# Vystak Docs Content Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 6 placeholder pages in `website/docs/` with real content (intro, installation, quickstart, agents, docker, examples overview), so a new user can evaluate Vystak and ship a working agent in under 10 minutes.

**Architecture:** Content writing — no schema or code changes to the Vystak packages themselves. Each task replaces one markdown file's content. After all 6 are written, verify the build is clean and links resolve.

**Tech Stack:** Markdown + MDX (Docusaurus), existing source material in `README.md`, `docs/getting-started.md`, `docs/principles.md`, and `examples/`.

---

## Critical context for the engineer

Read this before starting any task.

### Working directory and branch

- **Repo root:** `/Users/akolodkin/Developer/work/AgentsStack`
- **Branch:** `feat/docs-portal` (already created — do not switch)
- All file paths in this plan are relative to the repo root unless prefixed with `~`.

### Site structure

- The Docusaurus site lives in `website/`.
- Doc pages are markdown files in `website/docs/<category>/<slug>.md`.
- Each page has frontmatter (`title`, `sidebar_label`, optional `sidebar_position`).
- Sidebar config: `website/sidebars.js` (already correct — don't edit).
- Run dev server with `just docs-dev` (serves on `http://localhost:3000/AgentsStack/`).
- Build with `just docs-build`. **The build must succeed with zero broken-link errors before each commit** — the Docusaurus config sets `onBrokenLinks: 'throw'`.

### Source material to draw from

| Source | Use for |
|--------|---------|
| `README.md` (lines 1-303) | Quick start commands, full YAML/Python examples, feature list |
| `docs/principles.md` (lines 1-83) | Philosophy (declarative, code-over-config, etc.) |
| `docs/getting-started.md` (lines 1-234) | Installation steps, deployment workflow, contributor guide |
| `examples/minimal/vystak.yaml` | Minimal agent config for Quickstart |
| `examples/sessions-postgres/vystak.yaml` | Postgres sessions example for Agents page |
| `examples/multi-agent/{weather,time,assistant}/agentstack.yaml` | Multi-agent for Docker page (see "Known issue" below) |
| `examples/azure-multi-agent/vystak.yaml` | Azure multi-agent for Examples page |

### Known issues to be aware of

1. **Naming inconsistency** — `examples/multi-agent/{weather,time,assistant}/` still use `agentstack.yaml` instead of `vystak.yaml`. **Rename them as part of Task 5 (Docker page)** — they're referenced by that page. Update the file names with `git mv` so history is preserved. Also confirm `vystak apply` accepts both names; if not, document `agentstack.yaml` as legacy and stick to `vystak.yaml` going forward.
2. **Module name** — examples use `import vystak as ast`. The `as ast` alias is a holdover from when the package was `agentstack` and `ast` was a sensible short alias. New docs should use `import vystak` directly without the alias for clarity.

### Cross-link conventions

- Use Docusaurus relative links: `[Quickstart](/docs/getting-started/quickstart)` (note: leading `/docs/` and no `.md` extension).
- For placeholder pages that exist but have no real content yet, link them anyway — they render as the placeholder. Add a `:::note` admonition next to the link saying "(detailed page coming soon)" if it would surprise the reader.
- For pages that don't exist (none in this phase), don't fabricate links. Use plain text instead.

### Voice and style

- Tutorial depth: ~300-500 lines per page, working code blocks, conversational prose.
- Pulumi/Stripe-inspired: direct and concrete. Open with what the user can do, not the philosophy.
- Use `:::tip`, `:::note`, `:::warning` admonitions for callouts.
- Every page ends with a "What's next" section listing 2-4 related pages.

### After every task

1. Run `just docs-build` from the repo root.
2. Verify no broken-link errors and no markdown warnings.
3. Open the page in `just docs-dev` to skim it once.
4. Commit only after the build is clean.

---

## Task list

There are 6 content tasks, plus a final verification task. Each content task is self-contained — you can do them in any order, but they're listed in the order users will read them.

---

### Task 1: Write `getting-started/intro.md`

**Files:**
- Replace: `website/docs/getting-started/intro.md`

**Source material:**
- `README.md` lines 1-5 (intro tagline)
- `README.md` lines 139-153 (features list)
- `README.md` lines 211-234 (architecture diagram)
- `docs/principles.md` lines 1-30 (the seven principles, condensed)

- [ ] **Step 1: Replace `website/docs/getting-started/intro.md` with the following content**

````markdown
---
title: Introduction
sidebar_label: Introduction
sidebar_position: 1
slug: /getting-started/intro
---

# Introduction

**Vystak is to AI agents what Pulumi is to cloud infrastructure.** Define your agent once in YAML or Python, and Vystak generates the framework code, provisions the infrastructure, and deploys the agent — to Docker, Azure Container Apps, or any future platform.

Vystak builds nothing. It wires everything.

## What you can do with Vystak

- **Define agents declaratively** — one YAML or Python file describes the model, tools, sessions, channels, and where to run.
- **Deploy anywhere** — Docker locally, Azure Container Apps in production. Same definition, different target.
- **OpenAI-compatible API** — every agent exposes `/v1/chat/completions` and `/v1/responses` out of the box. Drop-in replacement for any OpenAI client.
- **Multi-agent collaboration** — built-in A2A protocol, gateway routing, and registry. Agents discover and call each other natively.
- **Persistence built in** — Postgres sessions, long-term memory, all auto-provisioned alongside the agent.
- **Hash-based change detection** — `vystak apply` only redeploys what changed.

## How it works

```
   ┌──────────────────────┐
   │  vystak.yaml or .py  │   ← Define once
   └──────────┬───────────┘
              │
   ┌──────────▼───────────┐
   │   Framework adapter  │   ← Generates LangGraph + FastAPI code
   │       (LangChain)    │
   └──────────┬───────────┘
              │
   ┌──────────▼───────────┐
   │  Platform provider   │   ← Provisions infra, builds image, deploys
   │  (Docker, Azure,...) │
   └──────────┬───────────┘
              │
   ┌──────────▼───────────┐
   │   Running agent      │   ← /invoke /stream /v1/chat/completions
   └──────────────────────┘
```

Three independent choices for every deployment:

- **Framework adapter** — *how* the agent thinks (LangChain/LangGraph today, others coming)
- **Platform provider** — *where* it runs (Docker, Azure Container Apps)
- **Channel adapter** — *how* users reach it (REST API, Slack, webhook)

Any combination works. The agent definition doesn't change — only the platform target does.

## Core concepts

| Concept | What it is |
|---------|------------|
| **Agent** | The deployable unit — model, tools, sessions, channels |
| **Model** | Which LLM and how to call it (Anthropic, OpenAI-compatible, MiniMax) |
| **Provider** | A cloud account or service (`docker`, `azure`, `anthropic`) |
| **Platform** | Where the agent runs (`docker`, `container-apps`) |
| **Service** | Backing infrastructure (Postgres, Redis, Qdrant) |
| **Channel** | How users reach the agent (REST, Slack, webhook) |

Each gets its own page — for now, the [Agents](/docs/concepts/agents) page covers the basics. The other concept pages have placeholders we'll expand soon.

## What's next

- [Installation](/docs/getting-started/installation) — install the CLI and Python packages
- [Quickstart](/docs/getting-started/quickstart) — deploy your first agent in five minutes
- [Agents](/docs/concepts/agents) — the agent schema in depth
````

- [ ] **Step 2: Build and verify**

```bash
just docs-build
```

Expected: build succeeds with zero broken-link warnings.

- [ ] **Step 3: Spot-check in dev server**

```bash
just docs-dev
```

Open `http://localhost:3000/AgentsStack/docs/getting-started/intro`. Verify:
- Title renders as "Introduction"
- ASCII diagram renders inside a code block
- Concept table renders correctly
- "What's next" links work

Stop the dev server when done.

- [ ] **Step 4: Commit**

```bash
git add website/docs/getting-started/intro.md
git commit -m "docs: write Introduction page"
```

---

### Task 2: Write `getting-started/installation.md`

**Files:**
- Replace: `website/docs/getting-started/installation.md`

**Source material:**
- `README.md` lines 9-12 (pip install command)
- `docs/getting-started.md` (full install section if it exists; otherwise use README)

- [ ] **Step 1: Replace `website/docs/getting-started/installation.md`**

````markdown
---
title: Installation
sidebar_label: Installation
sidebar_position: 2
---

# Installation

Vystak is a set of Python packages plus a CLI. You'll install the core SDK, the CLI, the LangChain adapter, and at least one platform provider.

## Prerequisites

- **Python 3.11 or later**
- **Docker** — required for the [Quickstart](/docs/getting-started/quickstart) and any Docker deploy
- **An LLM API key** — Anthropic, OpenAI, or any compatible endpoint (we use [MiniMax](https://www.minimax.io) in our examples)

Optional, depending on your target:
- **Azure CLI** (`az login`) — if you plan to deploy to Azure Container Apps

## Install the core packages

```bash
pip install vystak vystak-cli vystak-adapter-langchain vystak-provider-docker
```

That's the minimum to deploy a Docker agent. For Azure, also install:

```bash
pip install vystak-provider-azure
```

For the interactive chat client:

```bash
pip install vystak-chat
```

:::tip Use `uv` if you can
[uv](https://github.com/astral-sh/uv) is significantly faster than pip:

```bash
uv pip install vystak vystak-cli vystak-adapter-langchain vystak-provider-docker
```
:::

## Verify the install

```bash
vystak --version
vystak --help
```

You should see the version string and a list of subcommands (`init`, `plan`, `apply`, `destroy`, `status`, `logs`).

## Set your API key

The agent runtime reads its model API key from an environment variable. The variable name is whatever you declare in your agent's `secrets` field — by convention `ANTHROPIC_API_KEY` for Anthropic-compatible models:

```bash
export ANTHROPIC_API_KEY=your-key-here
```

Add it to your shell profile (`~/.zshrc`, `~/.bashrc`) so it persists across sessions.

## What's next

- [Quickstart](/docs/getting-started/quickstart) — deploy your first agent
````

- [ ] **Step 2: Build and verify**

```bash
just docs-build
```

Expected: clean build.

- [ ] **Step 3: Commit**

```bash
git add website/docs/getting-started/installation.md
git commit -m "docs: write Installation page"
```

---

### Task 3: Write `getting-started/quickstart.md`

**Files:**
- Replace: `website/docs/getting-started/quickstart.md`

**Source material:**
- `examples/minimal/vystak.yaml` — copy this verbatim into the Quickstart
- `README.md` lines 7-36 (quick start commands)

- [ ] **Step 1: Replace `website/docs/getting-started/quickstart.md`**

````markdown
---
title: Quickstart
sidebar_label: Quickstart
sidebar_position: 3
---

# Quickstart

By the end of this page, you'll have a chatbot running on your machine that you can talk to via curl, the Vystak chat client, or any OpenAI-compatible client.

This takes about five minutes.

## Prerequisites

- [Vystak installed](/docs/getting-started/installation)
- Docker running
- An Anthropic-compatible API key (we use [MiniMax](https://www.minimax.io) in this example because they offer a generous free tier)

## Step 1: Create a project

```bash
mkdir my-first-agent
cd my-first-agent
```

## Step 2: Define the agent

Create a file named `vystak.yaml` with this content:

```yaml
name: hello-bot
instructions: |
  You are a friendly assistant. Be concise.
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
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
port: 8090
```

A quick tour:
- `name` — your agent's name; also the container name prefix
- `instructions` — the system prompt
- `model` — the LLM to call. We're using MiniMax through their Anthropic-compatible endpoint
- `platform` — where to run. We're targeting Docker
- `channels` — how users reach the agent. `api` exposes a REST endpoint
- `secrets` — env vars the agent needs at runtime
- `port` — host port to bind on (optional; Docker picks one if omitted)

## Step 3: Set your API key

```bash
export ANTHROPIC_API_KEY=your-key-here
```

## Step 4: Deploy

```bash
vystak apply
```

You'll see output like:

```
Loaded 1 agent(s)

Agent: hello-bot
  Validating... OK
  Generating code... OK
  Deploying:
    Building Docker image... OK
    Starting container... OK

============================================================
Deployment complete — 1 agent(s) deployed
============================================================

Shared Infrastructure:
  Provider:     Docker (local)
  Network:      vystak-net

Agents:
  hello-bot    http://localhost:8090

Connect:
  vystak-chat --url http://localhost:8090
```

Vystak just generated a LangGraph agent + FastAPI server, packaged them in a Docker image, and started a container.

## Step 5: Talk to it

The simplest way is the interactive chat client:

```bash
vystak-chat --url http://localhost:8090
```

Or one-shot:

```bash
vystak-chat --url http://localhost:8090 -p "Hello!"
```

Or via curl:

```bash
curl -X POST http://localhost:8090/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!"}'
```

Or via any OpenAI-compatible client — the agent serves `/v1/chat/completions`:

```bash
curl http://localhost:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hello-bot",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Step 6: Iterate

Edit `vystak.yaml` — change the `instructions`, add `temperature: 0.5`, whatever — then run `vystak apply` again. Vystak hashes the definition and only redeploys if something actually changed.

## Step 7: Tear down

```bash
vystak destroy
```

This stops and removes the container. The Docker network and any volumes stick around so a redeploy is fast.

## What you just did

1. **Defined an agent** in 17 lines of YAML.
2. **Generated** a LangGraph agent + FastAPI harness from that definition.
3. **Built and deployed** the agent as a Docker container.
4. **Talked to it** via three different clients.

Vystak handled the LangChain integration, the Dockerfile, the networking, and the lifecycle. You wrote infrastructure as code.

## What's next

- [Agents](/docs/concepts/agents) — add tools, sessions, memory, multiple channels
- [Examples](/docs/examples/overview) — more complex setups including multi-agent
- [Deploying to Docker](/docs/deploying/docker) — how the Docker provider works
````

- [ ] **Step 2: Build and verify**

```bash
just docs-build
```

Expected: clean build.

- [ ] **Step 3: Commit**

```bash
git add website/docs/getting-started/quickstart.md
git commit -m "docs: write Quickstart page"
```

---

### Task 4: Write `concepts/agents.md`

**Files:**
- Replace: `website/docs/concepts/agents.md`

**Source material:**
- `examples/sessions-postgres/vystak.yaml` — primary example
- `README.md` lines 38-86 (full agent YAML + Python definition)
- Schema source for accuracy: `packages/python/vystak/src/vystak/schema/agent.py` (only check if a field's behavior is unclear — don't paste the full schema)

- [ ] **Step 1: Replace `website/docs/concepts/agents.md`**

````markdown
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
````

- [ ] **Step 2: Build and verify**

```bash
just docs-build
```

Expected: clean build, no broken links.

- [ ] **Step 3: Commit**

```bash
git add website/docs/concepts/agents.md
git commit -m "docs: write Agents concept page"
```

---

### Task 5: Write `deploying/docker.md` (and rename multi-agent example configs)

**Files:**
- Replace: `website/docs/deploying/docker.md`
- Rename: `examples/multi-agent/weather/agentstack.yaml` → `examples/multi-agent/weather/vystak.yaml`
- Rename: `examples/multi-agent/time/agentstack.yaml` → `examples/multi-agent/time/vystak.yaml`
- Rename: `examples/multi-agent/assistant/agentstack.yaml` → `examples/multi-agent/assistant/vystak.yaml`

**Source material:**
- `examples/multi-agent/{weather,time,assistant}/agentstack.yaml` — the three agents
- `README.md` agents section + Docker provider details

- [ ] **Step 1: Rename the multi-agent config files**

```bash
git mv examples/multi-agent/weather/agentstack.yaml examples/multi-agent/weather/vystak.yaml
git mv examples/multi-agent/time/agentstack.yaml examples/multi-agent/time/vystak.yaml
git mv examples/multi-agent/assistant/agentstack.yaml examples/multi-agent/assistant/vystak.yaml
```

- [ ] **Step 2: Verify the rename didn't break anything**

```bash
ls examples/multi-agent/weather/ examples/multi-agent/time/ examples/multi-agent/assistant/
```

Expected: each shows `vystak.yaml` and a `tools/` directory.

- [ ] **Step 3: Replace `website/docs/deploying/docker.md`**

````markdown
---
title: Deploying to Docker
sidebar_label: Docker
---

# Deploying to Docker

Docker is Vystak's default deployment target. It's the fastest way to iterate locally and the easiest way to share an agent with a teammate — they just need Docker installed.

This page covers everything from a single agent to a multi-agent system with a shared gateway.

## How it works

When you run `vystak apply`, the Docker provider:

1. Generates a LangGraph agent and FastAPI server from your `vystak.yaml`.
2. Writes them into `.vystak/<agent-name>/` along with a `Dockerfile`.
3. Builds a Docker image (`vystak-<agent-name>:latest`).
4. Provisions any backing services (Postgres, Redis) as separate containers.
5. Creates a shared network (`vystak-net`) if it doesn't exist.
6. Starts the agent container on that network with the right env vars and volumes.

You can inspect the generated code at `.vystak/<agent-name>/`. It's regular Python — debug it like any other FastAPI app.

## Single agent

The [Quickstart](/docs/getting-started/quickstart) covers the basic case. The same `vystak apply` command works for any single-agent project. Run `vystak status` to see what's running, `vystak logs` to tail container logs, and `vystak destroy` to tear everything down.

## Multiple agents

Vystak handles multi-agent deployments natively. Put each agent in its own subdirectory and run `vystak apply` against the parent. Vystak deploys all agents and provisions a shared gateway that registers each one.

The `examples/multi-agent/` example has three agents: `weather`, `time`, and `assistant`. The assistant agent calls the weather and time agents via Vystak's A2A (agent-to-agent) protocol.

```
examples/multi-agent/
├── weather/
│   ├── vystak.yaml
│   └── tools/get_weather.py
├── time/
│   ├── vystak.yaml
│   └── tools/get_time.py
└── assistant/
    ├── vystak.yaml
    └── tools/
        ├── ask_weather_agent.py
        └── ask_time_agent.py
```

Deploy them all:

```bash
cd examples/multi-agent
vystak apply weather time assistant
```

You'll get output like:

```
Loaded 3 agent(s)

Agent: weather-agent
  Deploying... OK

Agent: time-agent
  Deploying... OK

Agent: assistant-agent
  Deploying... OK

Gateway:
  Deploying... OK
  http://localhost:8080
  Registering agents...
    weather-agent: registered
    time-agent: registered
    assistant-agent: registered

Connect:
  vystak-chat --gateway http://localhost:8080
```

The assistant can now call the other agents:

```bash
vystak-chat --gateway http://localhost:8080 \
  -p "What's the weather in Tokyo and what time is it there?"
```

The assistant routes both questions to the right specialist agents in parallel.

## Sessions and persistence

Add `sessions: postgres` to any agent's YAML and Vystak provisions a Postgres container automatically:

```yaml
sessions:
  type: postgres
  provider:
    name: docker
    type: docker
```

The Postgres container is named `vystak-resource-<service-name>` and lives on `vystak-net`. The agent gets its connection string via the `SESSION_STORE_URL` env var.

Run `docker ps` after `vystak apply` and you'll see both containers.

## Updating an agent

Vystak content-hashes your agent definition. Re-running `vystak apply` after a change does the smallest possible update:

- **Definition unchanged** → skip deploy entirely.
- **Tools or instructions changed** → rebuild image and restart agent container. Postgres stays up.
- **Provider config changed** → may require destroying and recreating the network or services.

To force a redeploy regardless of hash:

```bash
vystak apply --force
```

## Plan before apply

`vystak plan` shows what `vystak apply` would do without making changes:

```bash
vystak plan
```

Output shows agents to deploy, services to provision, and infrastructure that would be created.

## Tearing down

To stop and remove the agent containers (keep volumes):

```bash
vystak destroy
```

To also remove backing services (Postgres, gateway):

```bash
vystak destroy --include-resources
```

The Docker network (`vystak-net`) is left alone so other Vystak deployments aren't affected.

## Troubleshooting

**"Cannot connect to the Docker daemon"** — Docker isn't running. Start Docker Desktop or `systemctl start docker`.

**"port is already allocated"** — another container or process is using the agent's port. Pick a different `port:` in your YAML or stop the conflicting process.

**Agent runs but errors with "ANTHROPIC_API_KEY not set"** — you forgot to `export` your API key before running `vystak apply`. Re-export and re-run.

**Stale container after edit** — if you suspect the agent didn't pick up your changes, run `vystak apply --force`.

## What's next

- [Examples](/docs/examples/overview) — more deployment patterns
- [Deploying to Azure Container Apps](/docs/deploying/azure) (placeholder) — same agents, cloud target
- [Gateway](/docs/deploying/gateway) (placeholder) — how the gateway works in detail
````

- [ ] **Step 4: Build and verify**

```bash
just docs-build
```

Expected: clean build.

- [ ] **Step 5: Commit (rename + content together so the rename is documented in one place)**

```bash
git add website/docs/deploying/docker.md examples/multi-agent/
git commit -m "docs: write Docker deploying page; rename multi-agent example configs to vystak.yaml"
```

---

### Task 6: Write `examples/overview.md`

**Files:**
- Replace: `website/docs/examples/overview.md`

**Source material:**
- `examples/minimal/vystak.yaml`
- `examples/sessions-postgres/vystak.yaml`
- `examples/multi-agent/{weather,time,assistant}/vystak.yaml` (after Task 5 renames them)
- `examples/azure-multi-agent/vystak.yaml`
- All other `examples/` subdirectories for the "All examples" section

- [ ] **Step 1: Replace `website/docs/examples/overview.md`**

````markdown
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
- **`azure-minimal`** — the simplest possible Azure deploy (single agent, no extras).
- **`azure-postgres-test`** — Azure Container App with a managed Postgres Flexible Server.

Each is a standalone directory with its own `vystak.yaml` (or `vystak.py`).

## What's next

- [Quickstart](/docs/getting-started/quickstart) — the fastest path to your first deploy
- [Agents](/docs/concepts/agents) — the agent schema in depth
- [Deploying to Docker](/docs/deploying/docker) — multi-agent and gateway details
````

- [ ] **Step 2: Build and verify**

```bash
just docs-build
```

Expected: clean build.

- [ ] **Step 3: Commit**

```bash
git add website/docs/examples/overview.md
git commit -m "docs: write Examples Overview page"
```

---

### Task 7: Final verification

**Files:** None (verification only)

- [ ] **Step 1: Clean build**

```bash
rm -rf website/build website/.docusaurus
just docs-build
```

Expected: full build succeeds, "Generated static files in 'build'." message.

- [ ] **Step 2: Check for broken links explicitly**

```bash
just docs-build 2>&1 | grep -i "broken\|warn\|error" | grep -v "deprecat" || echo "Clean"
```

Expected: prints "Clean" (no warnings or errors after filtering deprecation notices).

- [ ] **Step 3: Spot-check each new page in dev server**

```bash
just docs-dev
```

Visit each in the browser and verify it renders:
- `http://localhost:3000/AgentsStack/docs/getting-started/intro`
- `http://localhost:3000/AgentsStack/docs/getting-started/installation`
- `http://localhost:3000/AgentsStack/docs/getting-started/quickstart`
- `http://localhost:3000/AgentsStack/docs/concepts/agents`
- `http://localhost:3000/AgentsStack/docs/deploying/docker`
- `http://localhost:3000/AgentsStack/docs/examples/overview`

For each, check:
- Title and frontmatter render correctly.
- Code blocks have syntax highlighting.
- Cross-links navigate to the correct page (try at least one per page).
- "What's next" section is present.

Stop the dev server.

- [ ] **Step 4: Verify the example renames worked**

```bash
git log --oneline --diff-filter=R | head -5
ls examples/multi-agent/{weather,time,assistant}/
```

Expected: each multi-agent subdirectory contains `vystak.yaml` (not `agentstack.yaml`).

- [ ] **Step 5: Done**

The 6 critical-path docs pages are written. The remaining 7 placeholder pages can be filled in Phase 2 as needed.

If you found issues during writing (bugs in examples, inaccurate README, missing CLI flags), they should already be either fixed in commits or logged in `docs/superpowers/followups.md`. Verify with:

```bash
git log --oneline feat/docs-portal ^main | head -20
```

The branch is ready to be merged or pushed for review.
