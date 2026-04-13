# `agentstack dev` — Design Spec

## Overview

A local development server that runs an agent without building a Docker image. It generates code to a local directory, runs it with uvicorn, watches for file changes, and auto-restarts. Resource containers (Postgres, Redis, Qdrant) still run in Docker. Agents expose A2A endpoints and can register with the gateway for full multi-agent development.

The goal is fast iteration: edit your agent definition or tools, see the change in 1-2 seconds.

## Decisions

| Decision | Choice |
|----------|--------|
| Agent process | Local uvicorn (no Docker) |
| Resources (Postgres, Redis, Qdrant) | Docker containers via existing provider |
| Hot reload | File watcher → regenerate code → restart uvicorn |
| Resource lifecycle | Persistent across restarts; `--clean` to tear down |
| A2A endpoints | Exposed (included in generated server.py) |
| Gateway registration | Auto-register via new `POST /register` API |
| Local gateway | `--gateway` flag runs gateway without Docker |
| Port strategy | Use `agent.port` field from schema, default 8000 |
| Code output | `.agentstack/dev/<agent-name>/` (gitignored, inspectable) |

## CLI Interface

```
agentstack dev              # run agent from agentstack.yaml
agentstack dev --file x.py  # run from specific file
agentstack dev --clean      # tear down resources first, then start
agentstack dev --gateway    # also run a local gateway on :8080
agentstack dev --port 9000  # override schema port
```

## Startup Sequence

1. Load agent definition (same discovery logic as `agentstack apply`: convention `agentstack.yaml/yml/py` + `--file` override)
2. Provision resource containers in Docker if needed (Postgres, Redis, Qdrant) — reuse existing containers if already running
3. Generate code to `.agentstack/dev/<agent-name>/` using the framework adapter (same code as `agentstack apply`)
4. Install dependencies (`pip install -r requirements.txt`) into the active Python environment
5. Start uvicorn on `0.0.0.0:<port>` where port comes from `agent.port` (default 8000)
6. Attempt gateway registration (see Gateway Registration section)
7. Print startup summary:
   ```
   Agent "hello-agent" running at http://localhost:8000
   Gateway: registered at http://localhost:8080
   Resources: postgres (agentstack-postgres-hello-agent)
   Watching: agentstack.yaml, tools/
   ```

## File Watching

**Watched paths:**
- Agent definition file (`agentstack.yaml`, `agentstack.py`, or `--file` target)
- `tools/` directory (recursive)
- External instructions file if `instructions` points to a file path

**On change detected:**
1. Debounce 500ms (avoid rapid-fire restarts on multi-file saves)
2. Re-load agent definition
3. Re-generate code to `.agentstack/dev/<agent-name>/`
4. Kill running uvicorn process
5. Start new uvicorn process
6. Print: `Reloaded — agent "hello-agent" restarted`

**Not watched:**
- Resource configuration changes (Postgres, Redis) — these require `--clean` and restart
- `requirements.txt` changes — user must Ctrl+C and restart

## Shutdown (Ctrl+C)

1. Send SIGTERM to uvicorn process
2. Deregister from gateway (if registered)
3. Print: `Agent "hello-agent" stopped. Resources still running — use --clean to tear down.`
4. Resource containers keep running

## Resource Management

Resources are persistent across dev restarts:

- Postgres, Redis, Qdrant containers are provisioned via the existing Docker provider resource logic
- Same container naming convention (`agentstack-postgres-<name>`, etc.)
- Same Docker network (`agentstack-net`) — resources are reachable from both Docker agents and localhost
- Environment variables (database URLs, secrets) are injected into the uvicorn process environment
- `agentstack dev --clean` stops and removes resource containers before starting fresh

**Resource reuse:** On startup, check if the resource container already exists and is running. If so, skip provisioning. If it exists but is stopped, start it. If it doesn't exist, create it.

**Health checks:** Wait for resources to be healthy before starting uvicorn (reuse existing `HealthCheck` classes from the provision graph).

## Gateway Registration

### Registration API (new gateway endpoints)

Two new endpoints on the gateway:

```
POST   /register          — register an agent
DELETE /register/{name}   — deregister an agent
```

**Register request:**
```json
{
  "name": "hello-agent",
  "url": "http://localhost:8000",
  "card": { ... }
}
```

**Behavior:**
- Registered agents appear in `GET /agents` alongside static `routes.json` agents
- Gateway proxies to registered agents identically to Docker agents (`/proxy/{name}/invoke`, `/proxy/{name}/stream`, `/a2a/{name}`)
- Registrations include a TTL (60 seconds). The dev server sends heartbeats every 30 seconds to keep the registration alive. If a dev server crashes without deregistering, the registration expires.
- Static routes in `routes.json` take precedence over dynamic registrations with the same name

### Dev Server Behavior

- On startup, check for a gateway at `http://localhost:8080` (default) or `AGENTSTACK_GATEWAY_URL` env var
- If found, register and start heartbeat loop
- If not found, print: `No gateway detected — running standalone. Use --gateway to start one.`
- On shutdown, send `DELETE /register/{name}` and stop heartbeat

### Local Gateway (`--gateway` flag)

- Runs the gateway as a local Python process (not Docker) on port 8080
- Uses the same gateway code from `agentstack-gateway`
- Other `agentstack dev` instances register with it
- Useful for fully Docker-free multi-agent development (resources aside)
- Stops when the dev server stops (Ctrl+C)

## Code Generation

- Same framework adapter (`agentstack-adapter-langchain`) generates the same code as `agentstack apply`
- Output directory: `.agentstack/dev/<agent-name>/` instead of a Docker build context
- Generated files: `agent.py`, `server.py`, `requirements.txt`, `tools/`, `store.py` (same as Docker deploy)
- `.agentstack/dev/` is added to `.gitignore`
- The directory is not cleaned between regenerations — files are overwritten in place
- User can inspect generated code for debugging

## Port Strategy

- Read `agent.port` from the agent schema (same field used for Docker port pinning)
- `--port` CLI flag overrides the schema value
- Default: 8000 if neither is set
- On port conflict: fail immediately with a clear error message including the conflicting port and suggestion to use `--port`

## Environment Variables

The dev server injects the same environment variables that the Docker provider would:

- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` — from secrets
- `SESSION_STORE_URL` — connection string for Postgres/SQLite session store
- `MEMORY_STORE_URL` — connection string for memory store
- `AGENT_NAME` — agent name from schema
- Resource-specific URLs (e.g., `POSTGRES_URL`, `REDIS_URL`)

Source: `.env` file in the agent directory (same as Docker deploy) + auto-generated resource URLs.

## Multi-Agent Development

To develop multiple agents locally:

```bash
# Terminal 1: start with gateway
cd agents/coordinator
agentstack dev --gateway

# Terminal 2: start researcher agent
cd agents/researcher
agentstack dev

# Terminal 3: start writer agent
cd agents/writer
agentstack dev

# Terminal 4: chat with coordinator (routes to others via gateway)
agentstack-chat --url http://localhost:8080
```

Each agent:
- Runs on its own port (from `agent.port`)
- Auto-registers with the gateway
- Can call other agents via A2A (URLs resolved through gateway or direct localhost)

## What It Does NOT Do

- No Docker image builds for the agent itself (that's the whole point)
- No container networking for the agent process
- No production-grade process management (no restart policies, no readiness probes)
- No `agentstack compose` support — one agent per `agentstack dev` invocation
- No dependency isolation — installs into the active Python environment
- No watching for dependency changes — must restart manually if `requirements.txt` changes

## Package

This command lives in `agentstack-cli` alongside the existing commands (`init`, `plan`, `apply`, `destroy`, `status`, `logs`). It imports from:
- `agentstack` — schema loading
- `agentstack-adapter-langchain` — code generation
- `agentstack-provider-docker` — resource provisioning (Postgres, Redis, Qdrant containers only)
- `agentstack-gateway` — gateway code (for `--gateway` flag)

## Dependencies

New dependencies for the CLI:
- `watchfiles` — file watching (async, cross-platform, used by uvicorn itself)
- No new dependencies for the gateway registration endpoints (FastAPI already available)
