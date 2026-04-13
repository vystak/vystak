# AgentStack — Project Plan

## What Is AgentStack

AgentStack is a declarative, platform-agnostic orchestration layer for AI agents. It defines, provisions, deploys, updates, and manages agents across any framework, any platform, and any cloud — from a single codebase.

**AgentStack builds nothing. It wires everything.**

Terraform/Pulumi didn't build AWS. They gave you one language to describe what you want and provisioned it. AgentStack does the same for AI agents.

---

## Current State

**Status:** MVP complete and running in production-like Docker deployments.

**Numbers:**
- 123 commits
- 319 tests across 40 test files
- ~4,400 lines of Python source code
- 8 Python packages + 4 TypeScript stubs
- 2 design sessions (April 11-12, 2026)

## What We Built

### Phase 1: Foundation (Complete)

**Monorepo scaffold:**
- Polyglot monorepo (Python + TypeScript) with uv and pnpm workspaces
- Justfile for cross-language task running
- GitHub Actions CI (Python 3.11-3.13 × Node 20-22 matrix)
- GitHub Actions Release (PyPI + npm publishing via changesets)
- Pre-commit hooks (ruff, eslint, prettier, conventional commits)

**Core SDK (`agentstack`):**
- Pydantic v2 schema models for all 7 concepts: Agent, Skill, Channel, Resource, Workspace, Provider, Platform
- Plus: McpServer, Secret, Model, Embedding, Gateway, ChannelProvider, SlackChannel
- Content-addressable hash engine (SHA-256 hash tree for change detection)
- YAML/JSON loader (`load_agent`, `dump_agent`)
- AsyncSqliteStore for long-term memory persistence
- Provider ABCs: FrameworkAdapter, PlatformProvider, ChannelAdapter

### Phase 2: LangChain Adapter (Complete)

**Code generation (`agentstack-adapter-langchain`):**
- Generates native LangGraph react agents from schema definitions
- Generated files: `agent.py`, `server.py`, `requirements.txt`, `tools/`, `store.py`
- FastAPI harness with `/invoke`, `/stream` (SSE), `/health` endpoints
- Supports Anthropic and OpenAI model providers
- Custom base URL support (tested with MiniMax's Anthropic-compatible API)
- `instructions` field for agent system prompt
- Real tool loading from `tools/` directory with scaffold-on-first-deploy
- MCP server integration via `langchain-mcp-adapters` (stdio + SSE/HTTP)
- Session persistence via LangGraph checkpointers:
  - In-memory (`MemorySaver`) — default
  - SQLite (`AsyncSqliteSaver`) — survives container restarts
  - Postgres (`AsyncPostgresSaver`) — production-grade
- Long-term memory with three scopes (user, project, global):
  - `save_memory` and `forget_memory` tools
  - Automatic memory recall on each request
  - Backed by AsyncPostgresStore or AsyncSqliteStore

### Phase 3: Docker Provider (Complete)

**Container management (`agentstack-provider-docker`):**
- Build Docker images from generated code
- Deploy, update, and destroy agent containers
- Hash-based change detection (skip deploy if nothing changed)
- Docker network management (`agentstack-net`)
- Resource provisioning:
  - Postgres containers with auto-generated passwords
  - SQLite volumes
  - Secrets stored in `.agentstack/secrets.json`
- Port pinning (optional fixed host port)
- MCP install commands in Dockerfile
- Environment variable injection (secrets, session store URLs)
- Docker Desktop socket auto-detection (macOS)

### Phase 4: CLI (Complete)

**Commands (`agentstack-cli`):**

| Command | Description |
|---------|-------------|
| `agentstack init` | Create starter `agentstack.yaml` |
| `agentstack plan` | Show what would change |
| `agentstack apply` | Deploy or update agent |
| `agentstack destroy` | Stop and remove agent |
| `agentstack status` | Show running agent status |
| `agentstack logs` | Tail container logs |

- Agent definition discovery: convention (`agentstack.yaml/yml/py`) + `--file` override
- Python file loading (`agentstack.py` with `agent` variable)
- `--include-resources` flag for destroy

### Phase 5: A2A Protocol (Complete)

**Agent-to-Agent communication:**
- A2A protocol server on every agent:
  - `GET /.well-known/agent.json` — Agent Card (auto-generated from schema)
  - `POST /a2a` — JSON-RPC 2.0 handler
  - Methods: `tasks/send`, `tasks/get`, `tasks/cancel`, `tasks/sendSubscribe`
- Task lifecycle: submitted → working → completed/failed/canceled/input_required
- Interrupt/resume support via LangGraph `interrupt()` and `Command(resume=...)`
- SSE streaming for `tasks/sendSubscribe`
- Context propagation across agent calls:
  - `trace_id` — root trace for OpenTelemetry
  - `user_id` — identity for memory scoping
  - `project_id` — project context
  - `parent_task_id` — call tree reconstruction
  - `agent_name` — current agent identification

### Phase 6: Multi-Agent (Complete)

**Agent collaboration:**
- Multiple agents on shared Docker network (`agentstack-net`)
- Agents call each other via A2A protocol tools (async httpx)
- Parallel agent calls (LangGraph runs async tools concurrently)
- Nested streaming — client sees full activity across agent chain:
  - `tool_call_start` → `agent_call started` → `agent_call completed` → `tool_result` → `token`
- Custom streaming events via LangGraph `get_stream_writer()`

### Phase 7: Gateway (Complete)

**Unified entry point (`agentstack-gateway`):**
- Routes requests to agents on the Docker network
- Agent discovery via Agent Cards (`GET /agents`)
- Proxy endpoints: `/proxy/{agent}/invoke`, `/proxy/{agent}/stream`
- A2A proxy: `/a2a/{agent}`
- Slack channel provider with route-based dispatching
- `routes.json` for static configuration

### Phase 8: Chat Client (Complete)

**Interactive terminal client (`agentstack-chat`):**
- Streaming responses with tool call visibility
- Auto-detects gateway vs direct agent connection
- Slash commands: `/connect`, `/use`, `/agents`, `/gateway`, `/sessions`, `/new`, `/resume`, `/status`, `/help`
- Interactive agent picker (arrow keys)
- Session management (create, list, resume)
- Tab completion for agent names and commands
- Persistent prompt history
- Token usage tracking
- Rich markdown rendering for agent responses
- One-shot mode (`-p "question"`) for scripting

---

## Architecture

```
                    ┌─────────────────┐
                    │  Agent Schema   │  ← Define once (YAML or Python)
                    └────────┬────────┘
                             │
                ┌────────────┼────────────┐
                │            │            │
       ┌────────▼──┐  ┌─────▼─────┐  ┌───▼────────┐
       │ Framework  │  │ Platform  │  │  Channel   │
       │  Adapter   │  │ Provider  │  │  Adapter   │
       └────────┬──┘  └─────┬─────┘  └───┬────────┘
                │            │            │
          LangChain     Docker       REST API
          LangGraph   Kubernetes      Slack
          (future)   AWS AgentCore   (future)

                    ┌─────────────────┐
                    │    Gateway      │  ← Unified entry point
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼──┐  ┌───────▼───┐  ┌───────▼───┐
     │ Agent A   │  │  Agent B  │  │  Agent C  │
     │           │←→│           │←→│           │
     └───────────┘  └───────────┘  └───────────┘
                    A2A Protocol
```

## Packages

| Package | Description | Status |
|---------|-------------|--------|
| `agentstack` | Core SDK — schema, hash, loader, stores | Complete |
| `agentstack-cli` | CLI tool — init, plan, apply, destroy, status, logs | Complete |
| `agentstack-adapter-langchain` | LangChain/LangGraph code generator | Complete |
| `agentstack-provider-docker` | Docker deployment provider | Complete |
| `agentstack-gateway` | Channel gateway (Slack, API routing) | Complete |
| `agentstack-chat` | Interactive chat client | Complete |
| `agentstack-adapter-mastra` | Mastra framework adapter | Stub |
| `agentstack-channel-api` | REST API channel adapter | Stub |
| `@agentstack/core` | TypeScript core SDK | Stub |
| `@agentstack/cli` | TypeScript CLI | Stub |
| `@agentstack/adapter-mastra` | TypeScript Mastra adapter | Stub |
| `@agentstack/provider-docker` | TypeScript Docker provider | Stub |

---

## What's Planned

### Near Term (Next Sprint)

**Publishing:**
- [ ] Publish to PyPI (`pip install agentstack agentstack-cli`)
- [ ] Publish to npm (`npm install @agentstack/core`)
- [ ] Proper versioning with changesets

**Developer Experience:**
- [ ] `agentstack dev` — local dev server without Docker (fast iteration)
- [ ] `agentstack compose` — deploy multiple agents from a single YAML file
- [ ] `agentstack generate` — write generated code to disk without deploying
- [ ] Agent registry — agents auto-register with gateway on deploy

**Documentation:**
- [ ] Documentation site (VitePress or Starlight)
- [ ] API reference
- [ ] Tutorial: "Build your first agent in 5 minutes"
- [ ] Tutorial: "Multi-agent system with A2A"

### Near-Medium Term

**Authentication & Security:**
- [ ] Gateway authentication — API key or JWT for client → gateway
- [ ] `agentstack login` — CLI authentication command
- [ ] Agent endpoint protection — bearer token on `/invoke`, `/stream`, `/a2a`
- [ ] mTLS between agents on `agentstack-net` (under discussion — adds complexity vs container network isolation)
- [ ] Secret rotation for auto-generated resource passwords
- [ ] Audit log for agent access (who called which agent, when)

**Token Optimization:**
- [ ] Session compaction — summarize older messages to fit context window
- [ ] Configurable context window limits per agent
- [ ] Token budget per request (max_tokens enforcement)
- [ ] Message pruning strategies (sliding window, summarize, truncate)
- [ ] Token usage tracking per agent/user/project (already captured, needs storage)
- [ ] Cost estimation in `agentstack plan` (model pricing × estimated tokens)

**LLM Cache Optimization:**
- [ ] Prompt caching — leverage Anthropic/OpenAI prompt caching for system prompts and tool definitions
- [ ] Response caching — cache identical requests (same message + context hash) with TTL
- [ ] Semantic caching — cache similar queries (embedding-based similarity) to avoid redundant LLM calls
- [ ] Tool result caching — cache deterministic tool outputs (e.g., weather for same city within 5 min)
- [ ] Shared cache across agents — common tool results available to all agents on the network
- [ ] Cache configuration in agent schema (`cache: {strategy: semantic, ttl: 300}`)

**Knowledge / RAG:**
- [ ] Knowledge resource type — declare vector stores as agent resources (`engine: pinecone/chroma/qdrant/pgvector`)
- [ ] Auto-provisioning — Docker provider spins up Chroma/Qdrant container or pgvector extension
- [ ] Document ingestion — `agentstack ingest` CLI command to load docs into the knowledge base
- [ ] Generated retrieval tool — adapter generates a `search_knowledge` tool wired to the vector store
- [ ] Embedding model configuration — specify embedding provider/model in the knowledge resource
- [ ] Chunking strategies — configurable chunk size, overlap, splitter (recursive, semantic)
- [ ] Source tracking — retrieved chunks include source metadata (file, page, URL)
- [ ] Multi-knowledge support — agent can have multiple knowledge bases (e.g., docs + codebase)
- [ ] Knowledge sync — `agentstack sync` re-indexes changed documents
- [ ] Hybrid search — combine vector similarity with keyword search (BM25)

**Queue-Based Transport:**
- [ ] Agent-to-agent communication via message queues (SQS, RabbitMQ, Redis Streams, Kafka)
- [ ] Async task dispatch — fire-and-forget agent calls that don't block the caller
- [ ] Task result delivery — callee posts result back via queue or callback URL
- [ ] Dead letter queues — failed tasks routed for retry or human review
- [ ] Priority queues — urgent tasks processed before background work
- [ ] Fan-out patterns — one message triggers multiple agents in parallel
- [ ] Queue resource type — declare queues in agent schema (`engine: sqs/rabbitmq/redis/kafka`)
- [ ] Auto-provisioning — Docker provider spins up RabbitMQ/Redis container
- [ ] Backpressure handling — agents signal when overloaded, queue throttles
- [ ] Queue monitoring — message depth, processing rate, error rate in `agentstack status`
- [ ] Durable workflows — multi-step agent pipelines with guaranteed delivery (retry, exactly-once)

**Workspaces:**
- [ ] Sandbox workspace — isolated execution environment (e2b, Daytona, Docker) for code execution agents
- [ ] Persistent workspace — survives across sessions, agent accumulates work (S3, GCS, local volume)
- [ ] Mounted workspace — connect to existing storage (Google Drive, SharePoint, S3)
- [ ] Workspace capabilities: filesystem, terminal, browser, network, GPU
- [ ] Skill validation against workspace — skills declare what they need, `agentstack plan` validates
- [ ] Workspace lifecycle management (per-session, per-request, persistent, shared)
- [ ] Workspace providers: e2b, Daytona, Docker volumes, cloud storage

### Medium Term

**Observability:**
- [ ] OpenTelemetry integration (trace_id → real OTel spans)
- [ ] Cost tracking per agent (model usage)
- [ ] `agentstack dashboard` — web UI for monitoring agents

**Production Hardening:**
- [ ] Health check retries and readiness probes
- [ ] Graceful shutdown handling
- [ ] Container restart policies
- [ ] Rate limiting on endpoints
- [ ] Authentication/authorization on agent endpoints

**More Adapters:**
- [ ] Raw adapter (direct Anthropic/OpenAI SDK, no framework)
- [ ] CrewAI adapter
- [ ] Mastra adapter (TypeScript)

**More Providers:**
- [ ] AWS AgentCore provider
- [ ] Kubernetes provider
- [ ] Docker Compose provider
- [ ] DigitalOcean Gradient provider

**More Channels:**
- [ ] Discord channel adapter
- [ ] WhatsApp channel adapter
- [ ] Voice (Twilio) channel adapter
- [ ] Webhook (generic) channel adapter

### Long Term

**Fleet Management:**
- [ ] `agentstack fleet status` — what's running, versions, costs
- [ ] `agentstack fleet upgrade` — bulk update models or frameworks
- [ ] `agentstack fleet rollback` — roll back to previous hash
- [ ] `agentstack fleet promote` — staging → production promotion
- [ ] Replay testing (replay production traces against new config)

**Skill Marketplace:**
- [ ] Skill packaging and distribution (`pip install agentstack-skill-*`)
- [ ] Skill registry and discovery
- [ ] Skill validation (requirements check at plan time)

**Enterprise:**
- [ ] SSO integration
- [ ] RBAC for agent management
- [ ] Audit logging
- [ ] On-prem deployment guide
- [ ] SOC 2 compliance considerations

**TypeScript SDK:**
- [ ] Full TypeScript implementation mirroring Python SDK
- [ ] TypeScript adapter for Mastra framework
- [ ] Cross-language agent definitions

---

## Design Documents

All design specs and implementation plans are in `docs/superpowers/`:

**Specs:**
- `specs/2026-04-11-monorepo-scaffold-design.md`
- `specs/2026-04-11-getting-started-docs-design.md`
- `specs/2026-04-11-core-sdk-schema-design.md`
- `specs/2026-04-11-langchain-adapter-design.md`
- `specs/2026-04-11-docker-provider-cli-design.md`
- `specs/2026-04-12-persisted-resources-design.md`
- `specs/2026-04-12-long-term-memory-design.md`
- `specs/2026-04-12-real-tool-loading-design.md`
- `specs/2026-04-12-a2a-server-design.md`
- `specs/2026-04-12-mcp-integration-design.md`

**Plans:**
- `plans/2026-04-11-monorepo-scaffold.md`
- `plans/2026-04-11-core-sdk-schema.md`
- `plans/2026-04-11-langchain-adapter.md`
- `plans/2026-04-11-docker-provider-cli.md`
- `plans/2026-04-12-persisted-resources.md`
- `plans/2026-04-12-long-term-memory.md`
- `plans/2026-04-12-real-tool-loading.md`
- `plans/2026-04-12-a2a-server.md`
- `plans/2026-04-12-mcp-integration.md`

---

## Principles

See [docs/principles.md](docs/principles.md) for the full philosophy. Key points:

1. **Agents are infrastructure** — defined, versioned, tested, deployed with rigor
2. **Define once, deploy everywhere** — one definition, any platform
3. **Build nothing, integrate everything** — thin adapters to best-in-class tools
4. **Code over config** — Python/TypeScript primary, YAML as on-ramp
5. **Progressive complexity** — 3 lines to start, full IaC when needed
6. **Stateless tool** — no state files, hash-based change detection
7. **Framework is a runtime target** — generate native code, no abstractions

---

## Business Model

```
Open Source (free)       CLI, all adapters, local execution
Team ($50/mo)            Remote state, dashboard, secrets, 5 users
Business ($200/mo)       Fleet management, replay testing, RBAC, audit
Enterprise (custom)      SSO, on-prem, SLA, dedicated support
```

Additional revenue: unified billing passthrough, skill marketplace, managed connectors, professional services.

---

## Getting Started

```bash
# Clone and setup
git clone <repo-url> && cd AgentsStack
uv sync && pnpm install

# Run tests
just test

# Create and deploy an agent
cd examples/hello-agent
cp .env.example .env  # add your API key
agentstack apply

# Talk to it
agentstack-chat --url http://localhost:8080
```
