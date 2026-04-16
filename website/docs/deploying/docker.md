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
