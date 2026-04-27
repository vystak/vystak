# Vystak

[![CI](https://github.com/vystak/vystak/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/vystak/vystak/actions/workflows/ci.yml)

Declarative, platform-agnostic orchestration for AI agents. Define once, deploy everywhere.

Vystak builds nothing. It wires everything. Define your agent in Python or YAML, and Vystak generates native framework code, provisions infrastructure, and deploys to Docker — from a single command.

## Quick Start

```bash
# Install
pip install vystak vystak-cli vystak-adapter-langchain vystak-provider-docker

# Create an agent
vystak init

# Preview what will be generated
vystak plan

# Deploy to Docker
export ANTHROPIC_API_KEY=your-key
vystak apply

# Talk to your agent (interactive REPL)
vystak-chat --url http://localhost:PORT

# Or one-shot
vystak-chat --url http://localhost:PORT -p "Hello!"

# Or via curl
curl -X POST http://localhost:PORT/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!"}'

# Tear down
vystak destroy
```

## Define an Agent

**YAML (simple on-ramp):**

```yaml
name: support-bot
instructions: |
  You are a helpful support agent. Be concise and friendly.
model:
  name: claude
  provider:
    name: anthropic
    type: anthropic
  model_name: claude-sonnet-4-20250514
  parameters:
    temperature: 0.7
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
skills:
  - name: support
    tools: [lookup_order, process_refund]
    prompt: Always verify the order before processing refunds.
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
```

**Python (code-first):**

```python
import vystak as ast

anthropic = ast.Provider(name="anthropic", type="anthropic")
docker = ast.Provider(name="docker", type="docker")
model = ast.Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")

agent = ast.Agent(
    name="support-bot",
    instructions="You are a helpful support agent.",
    model=model,
    platform=ast.Platform(name="docker", type="docker", provider=docker),
    sessions=ast.Postgres(provider=docker),
    skills=[ast.Skill(name="support", tools=["lookup_order", "process_refund"])],
    channels=[ast.Channel(name="api", type=ast.ChannelType.API)],
)
```

## What `vystak apply` Does

```
vystak.yaml
       |
   [1] Validate agent definition
       |
   [2] Generate code (LangGraph agent + FastAPI server)
       |
   [3] Provision resources (Postgres container, Docker network)
       |
   [4] Build Docker image
       |
   [5] Deploy container
       |
   Agent running at http://localhost:PORT
       /invoke                    — request-response
       /stream                    — SSE streaming
       /health                    — health check
       /.well-known/agent.json    — A2A Agent Card (discovery)
       /a2a                       — A2A JSON-RPC (agent-to-agent)
```

## Chat Client

Talk to your deployed agents from the terminal with `vystak-chat`:

```bash
# Interactive REPL — connect and chat
vystak-chat --url http://localhost:8080

# One-shot prompt
vystak-chat --url http://localhost:8080 -p "What is the weather in NYC?"
```

Inside the REPL, use slash commands:

| Command | Description |
|---------|-------------|
| `/connect <url>` | Connect to an agent |
| `/use <name>` | Connect to a saved agent |
| `/agents` | List saved agents |
| `/agents add <name> <url>` | Save an agent |
| `/sessions` | List chat sessions |
| `/new` | New session (same agent) |
| `/resume <id>` | Resume a previous session |
| `/status` | Show connection info |
| `/help` | Show all commands |

Features: streaming responses, tool call visibility, tab completion, persistent prompt history, token usage tracking in the status bar.

## Features

- **Schema-driven** — Pydantic models for Agent, Skill, Channel, Service, Workspace, Provider, Platform, McpServer, Secret
- **Hash-based change detection** — content-addressable hashing detects what changed, enables partial deploys
- **LangChain/LangGraph adapter** — generates native LangGraph react agents with FastAPI harness
- **Docker provider** — builds images, manages containers, provisions Postgres/SQLite resources
- **Session persistence** — conversations persist across container restarts (Postgres or SQLite)
- **Long-term memory** — agents remember facts across sessions, scoped to user/project/global
- **Chat client** — interactive REPL with streaming, tool visibility, slash commands, and token tracking
- **A2A protocol** — agents discover and communicate via Google's Agent-to-Agent standard (JSON-RPC 2.0)
- **Multi-agent** — deploy multiple agents that call each other in parallel via A2A with nested streaming
- **Real tool loading** — write plain Python functions in `tools/`, auto-scaffolded on first deploy
- **Gateway** — channel routing service for Slack and other integrations
- **YAML + Python** — define agents in YAML for simplicity or Python for power
- **CLI** — `init`, `plan`, `apply`, `destroy`, `status`, `logs`

### Secret Management (Azure Key Vault)

Declare a top-level `Vault` and vault-backed secrets are materialized into
per-container env via ACA `secretRef` + `lifecycle: None` UAMIs. Workspace
secrets are isolated from the agent container so the LLM cannot exfiltrate
them. See `examples/azure-vault/` and `examples/azure-workspace-vault/`.

```yaml
vault:
  name: vystak-vault
  provider: azure
  mode: deploy
  config: {vault_name: my-vault}
```

CLI: `vystak secrets list | push | set | diff`.

## Multi-Agent (A2A Protocol)

Vystak agents implement Google's [Agent-to-Agent (A2A)](https://github.com/google/A2A) protocol. Agents discover each other via Agent Cards and communicate via JSON-RPC 2.0 over HTTP.

**Deploy multiple agents:**

```bash
# Deploy a weather specialist
cd examples/multi-agent/weather && vystak apply

# Deploy a time specialist
cd examples/multi-agent/time && vystak apply

# Deploy an assistant that calls both
cd examples/multi-agent/assistant && vystak apply
```

**Agents call each other via A2A tools:**

```python
# tools/ask_weather_agent.py — async for parallel execution
async def ask_weather_agent(question: str) -> str:
    """Ask the weather agent via A2A protocol."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://vystak-weather-agent:8000/a2a",
            json={"jsonrpc": "2.0", "method": "tasks/send", ...}
        )
    return extract_response(response.json())
```

**Parallel agent calls with full streaming visibility:**

```
$ curl -N http://localhost:8082/stream -d '{"message": "Weather in Tokyo AND current time?"}'

data: {"type": "tool_call_start", "tool": "ask_weather_agent"}   ← both tools called
data: {"type": "tool_call_start", "tool": "ask_time_agent"}      ← in parallel!
data: {"type": "agent_call", "agent": "weather-agent", "status": "started"}
data: {"type": "agent_call", "agent": "time-agent", "status": "started"}
data: {"type": "agent_call", "agent": "time-agent", "status": "completed"}  ← finished first
data: {"type": "agent_call", "agent": "weather-agent", "status": "completed"}
data: {"type": "token", "token": "Here's the info..."}          ← combined response
data: {"type": "done"}
```

**A2A endpoints on every agent:**

| Endpoint | Description |
|----------|-------------|
| `GET /.well-known/agent.json` | Agent Card — name, skills, capabilities |
| `POST /a2a` `tasks/send` | Send a message, get response |
| `POST /a2a` `tasks/sendSubscribe` | Streaming response via SSE |
| `POST /a2a` `tasks/get` | Check task status |
| `POST /a2a` `tasks/cancel` | Cancel a running task |

## Architecture

```
                    ┌─────────────┐
                    │ Agent Schema│  ← Define once
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
     ┌────────▼──┐  ┌──────▼────┐  ┌───▼────────┐
     │ Framework │  │ Platform  │  │  Channel   │
     │  Adapter  │  │ Provider  │  │  Adapter   │
     └────────┬──┘  └──────┬────┘  └───┬────────┘
              │            │            │
        LangChain     Docker       REST API
        LangGraph   Kubernetes      Slack
        CrewAI     AWS AgentCore    Voice
        (raw)      Azure Foundry   Webhook
```

**Three independent choices:**
- **Framework adapter** — HOW the agent thinks (LangChain, raw, ...)
- **Platform provider** — WHERE the agent runs (Docker, AWS, ...)
- **Channel adapter** — HOW users reach it (API, Slack, ...)

## CLI Commands

| Command | Description |
|---------|-------------|
| `vystak init` | Create a starter `vystak.yaml` |
| `vystak plan` | Show what would change |
| `vystak apply` | Deploy or update the agent |
| `vystak destroy` | Stop and remove the agent |
| `vystak status` | Show running agent status |
| `vystak logs` | Tail agent container logs |

## Project Structure

```
packages/
  python/
    vystak/                  # Core SDK — schema, hash, loader, stores
    vystak-cli/              # CLI tool
    vystak-adapter-langchain/ # LangChain/LangGraph code generator
    vystak-provider-docker/  # Docker deployment provider
    vystak-gateway/          # Channel gateway (Slack routing)
    vystak-chat/             # Interactive chat client
    vystak-adapter-mastra/   # Mastra adapter (stub)
    vystak-channel-api/      # REST API channel (stub)
  typescript/
    core/                        # @vystak/core (stub)
    cli/                         # @vystak/cli (stub)
    adapter-mastra/              # @vystak/adapter-mastra (stub)
    provider-docker/             # @vystak/provider-docker (stub)
```

## Development

```bash
# Prerequisites: Python 3.11+, Node 20+, uv, pnpm, just

# Setup
uv sync
pnpm install

# Run all tests
just test

# Run Python tests only
just test-python

# Lint
just lint

# Format
just fmt
```

See [docs/getting-started.md](docs/getting-started.md) for the full contributor guide and [docs/principles.md](docs/principles.md) for the project philosophy.

## License

Apache 2.0
