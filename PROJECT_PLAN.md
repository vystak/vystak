# Vystak — Project Plan

## What Is Vystak

Vystak is a declarative, platform-agnostic orchestration layer for AI agents. It defines, provisions, deploys, updates, and manages agents across any framework, any platform, and any cloud — from a single codebase.

**Vystak builds nothing. It wires everything.**

Terraform/Pulumi didn't build AWS. They gave you one language to describe what you want and provisioned it. Vystak does the same for AI agents.

---

## Current State

**Status:** Multi-cloud deployment with OpenAI-compatible API — Docker + Azure Container Apps with multi-agent gateway. Long-running sessions stay bounded via three-layer compaction.

**Numbers:**
- 290+ commits
- 1270+ tests across 65+ test files
- 9 Python packages + 4 TypeScript stubs
- 10 examples (Docker + Azure)
- 5 design sessions (April 11–30, 2026)

## What We Built

### Phase 1: Foundation (Complete)

**Monorepo scaffold:**
- Polyglot monorepo (Python + TypeScript) with uv and pnpm workspaces
- Justfile for cross-language task running
- GitHub Actions CI (Python 3.11-3.13 × Node 20-22 matrix)
- GitHub Actions Release (PyPI + npm publishing via changesets)
- Pre-commit hooks (ruff, eslint, prettier, conventional commits)

**Core SDK (`vystak`):**
- Pydantic v2 schema models for all 7 concepts: Agent, Skill, Channel, Resource, Workspace, Provider, Platform
- Plus: McpServer, Secret, Model, Embedding, Gateway, ChannelProvider, SlackChannel
- Service types: Postgres, Sqlite, Redis, Qdrant — replace generic Resource
- First-class `sessions` and `memory` fields on Agent
- Content-addressable hash engine (SHA-256 hash tree for change detection)
- YAML/JSON loader (`load_agent`, `dump_agent`)
- Multi-agent YAML loader with named references (providers, platforms, models)
- Base + env config loading (`vystak.base.yaml` + `vystak.env.yaml`)
- AsyncSqliteStore for long-term memory persistence
- Provider ABCs: FrameworkAdapter, PlatformProvider, ChannelAdapter
- Provisioning engine:
  - ProvisionGraph — DAG with topological sort (Kahn's algorithm)
  - Provisionable protocol — name, depends_on, provision(), health_check()
  - HealthCheck ABCs: Noop, TCP, Command, HTTP
  - ProvisionListener — event callbacks for progress reporting (on_start/on_step/on_complete/on_error)
  - Platform fingerprint grouping for shared infrastructure dedup

### Phase 2: LangChain Adapter (Complete)

**Code generation (`vystak-adapter-langchain`):**
- Generates native LangGraph react agents from schema definitions
- Generated files: `agent.py`, `server.py`, `requirements.txt`, `tools/`, `store.py`
- FastAPI harness with OpenAI-compatible endpoints (see Phase 14)
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
  - Ephemeral memory recall via LangGraph `prompt` callable (never checkpointed)
  - Backed by AsyncPostgresStore or AsyncSqliteStore

### Phase 3: Docker Provider (Complete)

**Container management (`vystak-provider-docker`):**
- Build Docker images from generated code
- Deploy, update, and destroy agent containers
- Hash-based change detection (skip deploy if nothing changed)
- Docker network management (`vystak-net`)
- Resource provisioning:
  - Postgres containers with auto-generated passwords
  - SQLite volumes
  - Secrets stored in `.vystak/secrets.json`
- Port pinning (optional fixed host port)
- MCP install commands in Dockerfile
- Environment variable injection (secrets, session store URLs)
- Docker Desktop socket auto-detection (macOS)

### Phase 4: CLI (Complete)

**Commands (`vystak-cli`):**

| Command | Description |
|---------|-------------|
| `vystak init` | Create starter `vystak.yaml` |
| `vystak plan` | Show what would change |
| `vystak apply` | Deploy or update agent |
| `vystak destroy` | Stop and remove agent |
| `vystak status` | Show running agent status |
| `vystak logs` | Tail container logs |

- Agent definition discovery: convention (`vystak.yaml/yml/py`) + `--file` override
- Python file loading (`vystak.py` with `agent` variable)
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
- Multiple agents on shared Docker network (`vystak-net`)
- Agents call each other via A2A protocol tools (async httpx)
- Parallel agent calls (LangGraph runs async tools concurrently)
- Nested streaming — client sees full activity across agent chain:
  - `tool_call_start` → `agent_call started` → `agent_call completed` → `tool_result` → `token`
- Custom streaming events via LangGraph `get_stream_writer()`

### Phase 7: Gateway (Complete)

**Unified entry point (`vystak-gateway`):**
- Routes requests to agents on the Docker network
- Agent discovery via Agent Cards (`GET /agents`) and `/v1/models`
- OpenAI-compatible proxy: `/v1/chat/completions`, `/v1/responses`, `/v1/models`
- A2A proxy: `/a2a/{agent}`
- Response-to-agent mapping store for `GET /v1/responses/{id}` routing
- Slack channel provider with route-based dispatching
- `routes.json` for static configuration

### Phase 8: Chat Client (Complete)

**Interactive terminal client (`vystak-chat`):**
- Uses OpenAI Responses API with `previous_response_id` chaining for multi-turn
- Streaming responses with function call visibility (OpenAI SSE event format)
- Auto-detects gateway vs direct agent connection
- Slash commands: `/connect`, `/use`, `/agents`, `/gateway`, `/sessions`, `/new`, `/resume`, `/status`, `/help`
- Interactive agent picker (arrow keys)
- Tab completion for agent names and commands
- Persistent prompt history
- Token usage tracking with user_id-scoped memory
- Rich markdown rendering for agent responses
- One-shot mode (`-p "question"`) for scripting

### Phase 9: Schema Refactor (Complete — April 13, 2026)

**Provider/Platform/Service separation:**
- Provider = cloud account (azure, docker, anthropic)
- Platform = where agents run (container-apps, docker)
- Service = typed infrastructure (Postgres, Sqlite, Redis, Qdrant)
- `sessions` and `memory` as first-class Agent fields
- `depends_on` for explicit service dependencies
- Backward compatible — old `resources` field still works

### Phase 10: Provision Graph (Complete — April 13, 2026)

**Dependency-aware provisioning:**
- ProvisionGraph with Kahn's topological sort
- Provisionable protocol (name, depends_on, provision, health_check)
- HealthCheck hierarchy (Noop, TCP, Command, HTTP)
- ProvisionListener for progress events
- Docker provider rewired to use graph
- Implicit dependencies: network → services → agent → gateways

### Phase 11: Azure Provider — Phase 2a (Complete — April 13, 2026)

**Minimal Azure Container Apps deployment:**
- `vystak-provider-azure` package
- Auth: DefaultAzureCredential (az CLI → service principal)
- 5 Azure node types: ResourceGroup, LogAnalytics, ACR, ACA Environment, ContainerApp
- Cross-platform build (docker buildx linux/amd64 for ARM Macs)
- Hash-based change detection via ACA tags
- Tag-based destroy (`--include-resources`)
- CLI provider factory — auto-selects Docker vs Azure
- Tested: 3 agents deployed to ACA, A2A working

### Phase 12: Multi-Agent Deployment (Complete — April 14, 2026)

**Pulumi-style resource deduplication:**
- Python: same object `id()` → shared infrastructure
- YAML: named `providers`, `platforms`, `models` blocks — agents reference by name
- Base + env config: `vystak.base.yaml` + `vystak.env.yaml` + `VYSTAK_ENV`
- CLI accepts multiple files/directories: `vystak apply weather/ time/ assistant/`
- Platform fingerprint grouping — shared RG, ACR, ACA Environment
- All CLI commands updated: apply, destroy, status, plan, logs
- `--force` flag to redeploy without changes
- `--name` flag to target individual agents

### Phase 13: Gateway + Agent Registration (Complete — April 14, 2026)

**Auto-deployed gateway with CLI-driven registration:**
- Gateway auto-deploys after multi-agent apply (Docker + Azure)
- CLI registers agents via `POST /register` after deploy
- Persistent registration store (Postgres, SQLite, in-memory)
- Health tracking: marks agents offline after 3 consecutive proxy failures
- Gateway URL injection into Azure Container Apps
- Deployment summary with shared infra, agent URLs, connect command

### Phase 14: OpenAI-Compatible API (Complete — April 14-15, 2026)

**Stateless Chat Completions + Stateful Responses API:**

Every agent and the gateway expose OpenAI-compatible endpoints. Any OpenAI SDK client works as a drop-in:
```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8080/v1", api_key="unused")
client.chat.completions.create(model="vystak/my-agent", messages=[...])
```

- Agent endpoints:
  - `GET /v1/models` — agent listed as `vystak/{name}`
  - `POST /v1/chat/completions` — **stateless**, client sends full messages array, no checkpointer
  - `POST /v1/responses` — **stateful**, `previous_response_id` chaining backed by LangGraph checkpointer
  - `GET /v1/responses/{id}` — retrieve stored response (polling for background runs)
- Gateway endpoints: same `/v1/` routes, routes by `model` field to agents
- Responses API features:
  - `store: true/false` — persist to checkpointer or one-shot
  - `previous_response_id` — conversation chaining (response ID = LangGraph thread_id)
  - `background: true` — async execution, poll via GET
  - `stream: true` — OpenAI Responses SSE event types:
    - `response.created`, `response.output_text.delta`, `response.output_text.done`
    - `response.function_call_arguments.delta`, `response.function_call_arguments.done`
    - `response.output_item.added` (function_call, function_call_output)
    - `response.completed`, `[DONE]`
  - `input` accepts string or message array
  - `user_id`/`project_id` for memory scoping
- Memory recall via LangGraph `prompt` callable — ephemeral, never checkpointed
  - Follows LangMem canonical pattern: prompt function reconstructs system message fresh every turn
  - Eliminates duplicate system message errors on multi-turn conversations
- Removed: `/invoke`, `/stream`, `/proxy/*`, `/v1/threads/*`
- A2A protocol unchanged for agent-to-agent communication
- `openai_types.py` bundled into Docker builds for agent and gateway containers
- Chat REPL uses Responses API with `previous_response_id` chaining
- OpenAI error format on all `/v1/` endpoints

### Phase 15: Session Compaction (Complete — April 25–30, 2026)

**Three-layer defense against context overflow on long-running sessions.**

Compaction fires inside the agent's prompt callable, next to the
LangGraph checkpoint. None of the three layers requires changes to
how clients call the agent — they're transparent under
`/v1/responses` chaining.

- **Schema:** `Agent.compaction: Compaction | None`
  - `mode`: `off | conservative | aggressive` (preset shorthands)
  - Optional overrides: `trigger_pct`, `keep_recent_pct`,
    `prune_tool_output_bytes`, `target_tokens`, `context_window`,
    `summarizer` (Model with its own provider/api_key)
  - Hash contribution: changing compaction policy triggers redeploy

- **Layer 1 — pre-call prune** (always-on, pure):
  - Head-and-tail truncates oversized `ToolMessage` content older
    than the last 3 user→assistant turns
  - Defaults: 4 KB threshold (conservative), 1 KB (aggressive)
  - Never touches `HumanMessage` / `AIMessage` text

- **Layer 3 — threshold pre-call summarize:**
  - Token estimate via 3-tier strategy: cheap early-out from
    cached `last_input_tokens`, sync/async provider tokenizer
    (Anthropic exposes only sync in langchain 1.x), calibrated
    chars/3.5 with 10% safety margin as last resort
  - Summarizes `older` slice when prefill ≥
    `trigger_pct × context_window`
  - 60-second + 70%-coverage idempotency guard prevents
    summary-of-summary on adjacent turns
  - Stores summary in `vystak_compactions` table; the LangGraph
    checkpoint is never rewritten
  - Fail-open with `x_vystak: {compaction_fallback}` SSE chunk
    on summarizer error

- **Manual `POST /v1/sessions/{thread_id}/compact`:**
  - Optional `instructions` payload guides the summary
  - Fails loudly (HTTP 502) with `compaction_failed` code

- **Inspection endpoints:**
  - `GET /v1/sessions/{thread_id}/compactions` — list all generations
  - `GET /v1/sessions/{thread_id}/compactions/{generation}` — full row
  - Chat-channel proxy (`vystak-channel-chat`) forwards all three
  - `vystak-chat` slash commands `/compact [instructions]` and
    `/compactions` resolve `thread_id` from the most recent
    `previous_response_id`

- **Storage backends:**
  - `vystak_compactions` table with `(thread_id, generation)` PK
  - PostgresCompactionStore, SqliteCompactionStore,
    InMemoryCompactionStore — same contract across all three

- **Tool-output offloading** (opt-in via `Workspace`):
  - Large tool outputs written to disk, replaced in-prompt with
    `[tool] OK (N bytes) | preview: ... → /path`
  - Built-in `read_offloaded(path, offset, length)` tool with
    path-traversal hardening

- **Observability:** Prometheus-style counters
  (`vystak_compaction_total{layer, trigger, outcome}`,
  `_input_tokens_total`, `_messages_compacted`, `_estimate_error`,
  `_suppressions`) plus structured logs.

- **What's not Layer 2:** the originally planned autonomous-tool
  middleware is gone upstream. LangChain 1.1 renamed the API to
  `SummarizationMiddleware` (threshold-based) and removed the
  autonomous-tool variant. The remaining class is incompatible
  with vystak's `prompt=` callable architecture (`create_agent`
  doesn't accept callables, only static `system_prompt` strings).
  Layer 3 in our prompt callable provides the same threshold
  guarantee. Rationale preserved in `vystak.schema.compaction` for
  a future codegen migration to `create_agent` + middleware chain.

- **Verified end-to-end** on Postgres-backed agents in
  `examples/docker-compaction/`: threshold compactions fire after
  ~5 turns at the artificial 5K context window, manual `/compact`
  lands as a separate generation, summary text is clean prose with
  no thinking-block leak.

- **Concept doc:** `website/docs/concepts/compaction.md`.

---

## Planned: Phase 16 — Azure Provider Phase 2b/2c

### Phase 2b: Postgres + VNet + Key Vault

**Goal:** Full production Azure deployment with private networking and managed database.

- [ ] **Azure Database for PostgreSQL Flexible Server**
  - AzurePostgresNode in provision graph
  - SKU: Standard_B1ms (burstable), configurable via `config.sku`
  - Auto-create database `vystak`
  - Connection string injected into Container App env
  - Bring-your-own via `connection_string_env` (skip provisioning)

- [ ] **Virtual Network**
  - AzureVNetNode with two subnets: ACA (10.0.0.0/23) + Postgres (10.0.2.0/24)
  - ACA Environment integrated with VNet for private networking
  - Postgres private access via VNet subnet delegation
  - Agents reach Postgres via private IP (no public endpoint)

- [ ] **Key Vault**
  - AzureKeyVaultNode for secret management
  - Store ANTHROPIC_API_KEY, database passwords, ACR credentials
  - Container Apps reference secrets from Key Vault (managed identity)
  - Replaces plaintext secret injection in env vars

- [ ] **Managed Identity**
  - User-assigned managed identity for ACA → ACR pull (no admin user)
  - Key Vault access policy for Container Apps
  - Postgres Azure AD auth (optional, alongside password auth)

- [ ] **Session/memory examples on Azure**
  - `sessions-postgres` example deployed to Azure with managed Postgres
  - `memory-agent` example with both sessions + memory on Azure Postgres
  - Verify session persistence survives Container App restarts

### Phase 2c: Full Lifecycle

**Goal:** Complete Azure operational commands.

- [ ] **`vystak destroy` — full tag-based cleanup**
  - Delete resources in reverse dependency order
  - Respect shared resources (don't delete ACR if other agents use it)
  - Auto-delete RG only if Vystak created it (not user-specified)
  - Confirmation prompt before deleting infrastructure

- [ ] **`vystak status` — rich Azure status**
  - Show provisioning state, replica count, FQDN
  - Show resource group contents
  - Show cost estimate (based on SKU + replica hours)

- [ ] **`vystak logs` — Azure Monitor integration**
  - Query Log Analytics workspace for container logs
  - `--follow` for live tail via streaming query
  - `--tail N` for last N log lines
  - Filter by agent name

- [ ] **`vystak plan` — Azure diff**
  - Compare local hash with deployed hash (from ACA tags)
  - Show which resources would be created/updated/unchanged
  - Show infrastructure changes (new VNet, new Postgres, etc.)
  - Estimate cost impact

---

## Planned: Phase 17 — Parallel Provisioning

**Goal:** Provision independent graph nodes concurrently for faster deployments.

- [ ] **Parallel graph execution**
  - Identify independent nodes (same depth in topo-sort, no shared dependencies)
  - Execute independent nodes concurrently via `asyncio.gather()`
  - Sequential execution for dependent chains
  - Example: RG → (LogAnalytics + ACR + VNet in parallel) → ACA Environment → (3 Container Apps in parallel)

- [ ] **Async Provisionable protocol**
  - `async def provision(self, context)` — awaitable
  - `async def health_check().wait()` — async health polling
  - Backward compat: sync nodes wrapped in `asyncio.to_thread()`

- [ ] **Concurrency control**
  - `ProvisionGraph.execute(max_concurrency=N)` — limit parallel operations
  - Default: 5 concurrent provisions (Azure ARM has rate limits)
  - Per-provider throttling (Azure: 5, Docker: 10)

- [ ] **Progress reporting for parallel execution**
  - ProvisionListener events include concurrency info
  - `on_start` shows which nodes are running in parallel
  - `on_complete` shows remaining nodes
  - CLI output: `[3/7] Creating ACR + Log Analytics + VNet...`

- [ ] **Docker parallel provisioning**
  - Independent services (postgres for sessions + postgres for memory) in parallel
  - Multiple agent containers built + started in parallel
  - Network must be created first (dependency)

- [ ] **Estimated speed improvements**
  - Azure multi-agent: ~8 min sequential → ~4 min parallel (2 Container Apps at once)
  - Docker multi-agent: ~30s sequential → ~15s parallel

---

## Planned: Phase 18 — LangChain Adapter as a Prebuilt Package

**Status:** planned

Today `vystak-adapter-langchain` is a **codegen** package: it emits literal Python source strings (`templates.py`, `a2a.py`, `responses.py`) that get written into each agent's build context as `server.py`, `a2a.py`, etc. The generated container copies them + installs dependencies and runs the result. This shape has real costs:

- **Testing is shallow.** We can only assert against emitted source strings (e.g., "does the output contain `class ResponsesHandler:`?"). Runtime behavior — the actual dispatch paths, error handling, streaming semantics — is tested end-to-end via Docker or not at all.
- **Debugging is indirect.** A bug inside the emitted code requires tracing back to the `lines.append(...)` call that generated it.
- **Refactoring is high-friction.** Changing a behavior in the handler means editing string templates; linters and type-checkers don't help.
- **Generated source bloat.** `templates.py` is ~1400 lines emitting ~1500 lines of Python. The emitted code is verbose by nature because it has to inline every import, every helper.
- **Version drift.** Multiple agents deployed at different times hold frozen copies of the emitted logic. Fixing a bug requires redeploying every agent.

### Target shape

Refactor `vystak-adapter-langchain` into a **prebuilt, configurable Python package**:

- Ships as `vystak-adapter-langchain` on PyPI (eventually) or bundled as source (today's transport pattern).
- Exports classes and a factory: `build_langchain_agent_app(agent: Agent) -> FastAPI`.
- The factory constructs LangGraph + `A2AHandler` + `ResponsesHandler` + `ServerDispatcher` + FastAPI routes at runtime, reading the `Agent` Pydantic model for config.
- Generated container's `server.py` shrinks to ~10 lines:
  ```python
  # Emitted:
  import logging
  logging.basicConfig(level="INFO", format="...")

  from vystak_adapter_langchain.runtime import build_agent_app
  from agent_def import AGENT  # AGENT = Agent(...) — also emitted

  app = build_agent_app(AGENT)
  ```
- Docker build context bundles `vystak`, `vystak_transport_*`, `vystak_adapter_langchain` source trees (same mechanism used for transports today).

### What moves / stays

- `a2a.py` → `vystak_adapter_langchain.a2a` — real classes (`A2AHandler`, task manager, agent card builder).
- `templates.py` → `vystak_adapter_langchain.runtime` + submodules — real FastAPI app builders, model provider factories, MCP integration.
- `responses.py` → `vystak_adapter_langchain.responses` — real `ResponsesHandler`, event stream builders.
- Codegen stays only for the thin `server.py` bootstrap + `agent_def.py` (serialized Agent spec the container reads at startup).

### Unit tests

Full coverage becomes possible:
- `A2AHandler.dispatch()` with a fake LangGraph returning canned events.
- `ResponsesHandler.create_stream()` asserting each OpenAI event shape.
- `MCP` integration — mock MCP server, verify tool registration.
- Memory / session store integration tests in-process.
- FastAPI route behavior via `fastapi.testclient.TestClient`.

### Migration strategy

1. Extract current emitted logic into real module files one component at a time: `A2AHandler` first (lowest coupling), then `ResponsesHandler`, then `MemoryManager`, then the LangGraph builder, then the FastAPI app factory.
2. Each extracted component gets unit tests before the codegen template stops emitting its source.
3. Emitted `server.py` shrinks incrementally: every round of extraction removes ~100-200 lines from the emitted template.
4. Final state: `templates.py` shrinks to ~50 lines emitting just the bootstrap. `a2a.py` and `responses.py` codegen files are deleted.
5. The Docker provider's source-bundling loop already has the mechanism — just add `vystak_adapter_langchain` to the bundled list.

### Tasks (high-level)

- [ ] Extract `TaskManager` (current A2A state machine) into `vystak_adapter_langchain.tasks` with unit tests
- [ ] Extract `A2AHandler` into `vystak_adapter_langchain.a2a` with unit tests (replaces current codegen)
- [ ] Extract `ResponsesHandler` into `vystak_adapter_langchain.responses` with unit tests
- [ ] Extract `MemoryManager` + memory tool dispatch into `vystak_adapter_langchain.memory` with unit tests
- [ ] Extract LangGraph construction into `vystak_adapter_langchain.graph` with unit tests (mock models)
- [ ] Extract MCP wiring into `vystak_adapter_langchain.mcp` with unit tests
- [ ] Factory `build_agent_app(agent: Agent) -> FastAPI` in `vystak_adapter_langchain.runtime`
- [ ] Rewrite `templates.py` to emit a ~50-line bootstrap referencing the factory
- [ ] Docker provider bundles `vystak_adapter_langchain` source into agent build contexts
- [ ] End-to-end verification on `docker-multi-chat-nats` — behavior parity with the codegen era
- [ ] Delete `a2a.py` and `responses.py` codegen modules (their logic now lives in the real package)

Estimated size: 8-10 tasks, comparable to Plan A/B scope. Likely a multi-week effort.

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
          LangGraph   Azure ACA      Slack
          (future)   Kubernetes     (future)
                     AWS AgentCore

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
| `vystak` | Core SDK — schema, hash, loader, provisioning engine | Complete |
| `vystak-cli` | CLI — init, plan, apply, destroy, status, logs | Complete |
| `vystak-adapter-langchain` | LangChain/LangGraph code generator | Complete |
| `vystak-provider-docker` | Docker deployment provider (provision graph) | Complete |
| `vystak-provider-azure` | Azure Container Apps provider | Complete (Phase 2a) |
| `vystak-gateway` | Gateway — routing, registration, health tracking | Complete |
| `vystak-chat` | Interactive chat client | Complete |
| `vystak-adapter-mastra` | Mastra framework adapter | Stub |
| `vystak-channel-api` | REST API channel adapter | Stub |
| `@vystak/core` | TypeScript core SDK | Stub |
| `@vystak/cli` | TypeScript CLI | Stub |
| `@vystak/adapter-mastra` | TypeScript Mastra adapter | Stub |
| `@vystak/provider-docker` | TypeScript Docker provider | Stub |

---

## What's Planned

### Near Term (Next Sprint)

**Publishing:**
- [ ] Publish to PyPI (`pip install vystak vystak-cli`)
- [ ] Publish to npm (`npm install @vystak/core`)
- [ ] Proper versioning with changesets

**Developer Experience:**
- [ ] `vystak dev` — local dev server without Docker (fast iteration)
- [ ] `vystak compose` — deploy multiple agents from a single YAML file
- [ ] `vystak generate` — write generated code to disk without deploying
- [x] Agent registry — agents auto-register with gateway on deploy

**Documentation:**
- [x] Documentation site scaffold (Docusaurus 3 at `website/`, deployed to GitHub Pages)
- [ ] Documentation content (writing the actual guides, references, examples)
- [ ] API reference
- [ ] Tutorial: "Build your first agent in 5 minutes"
- [ ] Tutorial: "Multi-agent system with A2A"

### Near-Medium Term

**Authentication & Security:**
- [ ] Gateway authentication — API key or JWT for client → gateway (OpenAI `Authorization: Bearer` header)
- [ ] `vystak login` — CLI authentication command
- [ ] Agent endpoint protection — bearer token on `/v1/chat/completions`, `/v1/responses`, `/a2a`
- [ ] mTLS between agents on `vystak-net` (under discussion — adds complexity vs container network isolation)
- [ ] Secret rotation for auto-generated resource passwords
- [ ] Audit log for agent access (who called which agent, when)

**Token Optimization:**
- [x] Session compaction — summarize older messages to fit context window *(Phase 15)*
- [x] Configurable context window limits per agent *(`Compaction.context_window` override, Phase 15)*
- [x] Message pruning strategies (sliding window, summarize, truncate) *(Layer 1 prune + Layer 3 summarize + manual `/compact`, Phase 15)*
- [ ] Token budget per request (max_tokens enforcement)
- [ ] Token usage tracking per agent/user/project (already captured, needs storage)
- [ ] Cost estimation in `vystak plan` (model pricing × estimated tokens)

**LLM Cache Optimization:**
- [ ] Prompt caching — leverage Anthropic/OpenAI prompt caching for system prompts and tool definitions
- [ ] Response caching — cache identical requests (same message + context hash) with TTL
- [ ] Semantic caching — cache similar queries (embedding-based similarity) to avoid redundant LLM calls
- [ ] Tool result caching — cache deterministic tool outputs (e.g., weather for same city within 5 min)
- [ ] Shared cache across agents — common tool results available to all agents on the network
- [ ] Cache configuration in agent schema (`cache: {strategy: semantic, ttl: 300}`)

**Agentic Workflows (Claude Code-style):**

Agent modes beyond simple react (respond to message → call tools → respond):

*Plan-and-Execute:*
- [ ] Agent mode: `reactive` (current) vs `planner` (plan-execute loop)
- [ ] Task planning — agent decomposes complex requests into a step-by-step plan before executing
- [ ] Plan approval — agent presents plan to user, waits for approval via `interrupt()` / `input_required`
- [ ] Clarification questions — agent asks follow-up questions when ambiguous (maps to A2A `input_required`)
- [ ] Step-by-step execution — execute plan items sequentially, reporting progress via streaming
- [ ] Checkpoint gates — configurable pause points between steps for user review
- [ ] Plan revision — user can modify the plan mid-execution, agent adapts
- [ ] Parallel step execution — independent steps run concurrently
- [ ] Progress tracking — plan state persisted in checkpointer (survives restarts)
- [ ] Configurable autonomy levels:
  - `full` — plan and execute without pausing
  - `plan-approval` — pause after planning, execute autonomously
  - `step-approval` — pause before each step
  - `supervised` — pause after each step showing results
- [ ] Generated workflow graph — adapter generates LangGraph StateGraph with planner → executor → reviewer nodes
- [ ] Built-in tools: `create_plan`, `update_plan`, `mark_step_complete`
- [ ] Schema: `mode: planner` with `autonomy: plan-approval`

*Supervisor (using `langgraph-supervisor`):*
- [ ] Agent mode: `supervisor` — orchestrates multiple specialist agents
- [ ] `create_supervisor` integration — adapter generates supervisor graph from agent definition
- [ ] Sub-agents defined in YAML:
  ```yaml
  mode: supervisor
  agents:
    - name: researcher
      url: http://vystak-researcher:8000
    - name: math-expert  
      url: http://vystak-math:8000
  ```
- [ ] Handoff tools auto-generated — supervisor can delegate to any sub-agent
- [ ] Custom handoff descriptions — control how the LLM routes tasks
- [ ] Combined with A2A — supervisor calls sub-agents via A2A protocol on Docker network
- [ ] Hierarchical teams — supervisors can manage other supervisors

*Deep Research Agent:*
- [ ] Agent mode: `researcher` — multi-step research with iterative refinement
- [ ] Search → analyze → synthesize loop with configurable depth
- [ ] Source tracking and citation
- [ ] Intermediate findings streamed to client
- [ ] Can delegate sub-research to specialist agents

*Guardrails & Loop Protection:*
- [ ] Max tool calls per request — hard limit to prevent infinite loops (configurable, default 25)
- [ ] Max iterations per plan step — cap retries before escalating or failing
- [ ] Stuck detection — if agent calls the same tool with the same args N times, force a different approach or abort
- [ ] Timeout per request — wall-clock limit for entire agent invocation
- [ ] Timeout per tool call — individual tool execution timeout
- [ ] Cost circuit breaker — abort if estimated token cost exceeds budget for a single request
- [ ] Escalation on stuck — agent can escalate to user (via `input_required`) when it can't make progress
- [ ] Dead-end detection — if agent produces the same response N times, interrupt with "I'm unable to solve this"
- [ ] Configurable in schema:
  ```yaml
  guardrails:
    max_tool_calls: 25
    max_iterations: 10
    request_timeout: 120
    tool_timeout: 30
    max_cost_per_request: 0.50
    stuck_threshold: 3
  ```
- [ ] Generated code enforces limits — adapter generates loop counters and timeout wrappers
- [ ] Streaming visibility — client sees guardrail events (`{"type": "guardrail", "reason": "max_tool_calls_reached"}`)
- [ ] Metrics — track how often guardrails trigger per agent for tuning

*Streaming & Visibility:*
- [ ] Streaming plan updates — client sees plan creation, step progress, completion via SSE
- [ ] Multi-agent delegation visible in stream events
- [ ] Failure recovery — retry, skip, or revise plan on step failure

**Knowledge / RAG:**
- [ ] Knowledge resource type — declare vector stores as agent resources (`engine: pinecone/chroma/qdrant/pgvector`)
- [ ] Auto-provisioning — Docker provider spins up Chroma/Qdrant container or pgvector extension
- [ ] Document ingestion — `vystak ingest` CLI command to load docs into the knowledge base
- [ ] Generated retrieval tool — adapter generates a `search_knowledge` tool wired to the vector store
- [ ] Embedding model configuration — specify embedding provider/model in the knowledge resource
- [ ] Chunking strategies — configurable chunk size, overlap, splitter (recursive, semantic)
- [ ] Source tracking — retrieved chunks include source metadata (file, page, URL)
- [ ] Multi-knowledge support — agent can have multiple knowledge bases (e.g., docs + codebase)
- [ ] Knowledge sync — `vystak sync` re-indexes changed documents
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
- [ ] Queue monitoring — message depth, processing rate, error rate in `vystak status`
- [ ] Durable workflows — multi-step agent pipelines with guaranteed delivery (retry, exactly-once)

**Workspaces:**
- [ ] Sandbox workspace — isolated execution environment (e2b, Daytona, Docker) for code execution agents
- [ ] Persistent workspace — survives across sessions, agent accumulates work (S3, GCS, local volume)
- [ ] Mounted workspace — connect to existing storage (Google Drive, SharePoint, S3)
- [ ] Workspace capabilities: filesystem, terminal, browser, network, GPU
- [ ] Skill validation against workspace — skills declare what they need, `vystak plan` validates
- [ ] Workspace lifecycle management (per-session, per-request, persistent, shared)
- [ ] Workspace providers: e2b, Daytona, Docker volumes, cloud storage

**Testing & Evaluation:**
- [ ] `vystak test` — run test fixtures against a deployed or local agent
- [ ] Test fixture format — YAML files with input/expected output pairs
- [ ] Replay testing — replay production conversations against a new config, compare results
- [ ] Regression detection — catch when a prompt/model/tool change makes the agent worse
- [ ] Evaluation metrics — response quality scoring (LLM-as-judge, keyword matching, semantic similarity)
- [ ] Benchmark suite — standard test cases per agent, tracked over time
- [ ] CI integration — `vystak test` in GitHub Actions before deploy

**Reliability & Resilience:**
- [ ] Model fallback — if primary model provider is down, fall back to secondary (`fallback_model` in schema)
- [ ] Retry strategies — configurable retry with exponential backoff for model and tool failures
- [ ] Graceful degradation — if a tool fails, agent continues without it (optional per tool)
- [ ] Health check retries — agent marked healthy only after N consecutive successes
- [ ] Circuit breaker — disable a tool/model after repeated failures, auto-recover

**Environment Management:**
- [ ] Dev / staging / prod environments — `vystak apply --env production`
- [ ] Environment-specific config — different models, secrets, resources per environment
- [ ] Promotion flow — `vystak promote staging production` (verified deploy)
- [ ] Environment variables in YAML — `${ENV_VAR}` substitution in agent definitions
- [ ] Lock files — pin exact versions of models, tools, deps for reproducible deploys

**Scheduling & Triggers:**
- [ ] Cron-triggered agents — agents that run on a schedule (`schedule: "0 9 * * *"` in schema)
- [ ] Webhook-triggered agents — wake up on external events (GitHub push, Stripe payment, etc.)
- [ ] Event-driven patterns — agent subscribes to a topic, processes events as they arrive
- [ ] One-shot mode — agent runs once and exits (for batch jobs, reports)

**Compliance & Safety:**
- [ ] PII detection — flag/mask personal data before it reaches the model
- [ ] Content filtering — block harmful/inappropriate outputs before returning to user
- [ ] Output validation — enforce structured output schemas, response format constraints
- [ ] Conversation audit trail — immutable, append-only log of all interactions
- [ ] Data retention policies — auto-delete conversations/memories after configurable TTL
- [ ] Model output logging — optionally log all LLM inputs/outputs for compliance review

**Developer Tooling:**
- [ ] Agent debugging — step-through execution, inspect state at each graph node
- [ ] Time-travel debugging — rewind to any checkpoint and re-run from that point
- [ ] Hot reload in dev mode — change tools/prompts, agent restarts automatically
- [ ] `vystak diff` — show what changed between two agent versions (prompt, tools, model)
- [ ] `vystak inspect` — show generated code without deploying
- [ ] Agent REPL — interactive mode where you can test tools individually

### Medium Term

**Observability:**
- [ ] OpenTelemetry integration (trace_id → real OTel spans)
- [ ] Cost tracking per agent (model usage)
- [ ] `vystak dashboard` — web UI for monitoring agents

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

**Agent Versioning & Deployment Strategies:**
- [ ] Immutable agent versions — each deploy creates a version tag (content hash as version)
- [ ] `vystak rollback <version>` — instant rollback to any previous version
- [ ] A/B testing — route percentage of traffic to a new version (`traffic_split: {v1: 80, v2: 20}`)
- [ ] Canary deployments — gradual rollout with automatic rollback on error spike
- [ ] Blue-green deployments — swap between two identical environments
- [ ] Deploy history — `vystak history` shows all deploys with hashes and timestamps

**SDK & Client Libraries:**
- [ ] Python client — `from vystak import AgentClient; client.invoke("hello")`
- [ ] TypeScript/JS client — for web apps and Node.js backends
- [ ] OpenAPI spec auto-generated from agent endpoints — any language can codegen a client
- [ ] A2A client SDK — typed wrapper for calling agents via A2A protocol
- [ ] Webhook client — receive agent responses asynchronously via callback URL

**Composability:**
- [ ] `vystak compose` — single YAML defining multiple agents, gateway, routing, and resources
- [ ] Agent templates — `vystak init --template customer-support` (pre-built archetypes)
- [ ] Shared skill library — reusable skill packages across agents (`vystak-skill-*`)
- [ ] Agent inheritance — base agent with shared config, specialized agents extend it
- [ ] Import agents — reference other agent definitions (`agents: [./weather-agent, ./time-agent]`)

**Internationalization:**
- [ ] Multi-language system prompts — agents respond in the user's detected language
- [ ] Built-in translation tool — auto-translate between agent and user when needed
- [ ] Locale-aware formatting — dates, numbers, currencies adapted to user's locale

**Agent Analytics:**
- [ ] Conversation analytics — success rate, drop-off points, common failure patterns
- [ ] User satisfaction — thumbs up/down feedback, integrated into chat CLI and API response
- [ ] Tool usage analytics — which tools are called most, which fail most, avg latency
- [ ] Cost analytics — token usage and estimated cost per agent/user/project over time
- [ ] Dashboard views — `vystak dashboard` or web UI for visual analytics

### Long Term

**Fleet Management:**
- [ ] `vystak fleet status` — what's running, versions, costs
- [ ] `vystak fleet upgrade` — bulk update models or frameworks
- [ ] `vystak fleet rollback` — roll back to previous hash
- [ ] `vystak fleet promote` — staging → production promotion
- [ ] Replay testing (replay production traces against new config)

**Skill Marketplace:**
- [ ] Skill packaging and distribution (`pip install vystak-skill-*`)
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
- `specs/2026-04-12-schema-refactor-design.md`
- `specs/2026-04-13-test-examples-design.md`
- `specs/2026-04-13-provision-graph-design.md`
- `specs/2026-04-13-azure-provider-design.md`
- `specs/2026-04-13-multi-agent-deploy-design.md`
- `specs/2026-04-25-session-compaction-design.md`

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
- `plans/2026-04-12-schema-refactor.md`
- `plans/2026-04-13-test-examples.md`
- `plans/2026-04-13-provision-graph.md`
- `plans/2026-04-13-azure-provider-phase2a.md`
- `plans/2026-04-14-multi-agent-loader.md`
- `plans/2026-04-26-session-compaction.md`

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
git clone <repo-url> && cd Vystak
uv sync && pnpm install

# Run tests
just test

# Create and deploy an agent
cd examples/hello-agent
cp .env.example .env  # add your API key
vystak apply

# Talk to it
vystak-chat --url http://localhost:8080
```
