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
