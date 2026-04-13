# Core Schema Refactor — Design Spec

## Overview

Restructure the AgentStack schema to cleanly separate Provider, Platform, and Service concerns. Today, `Resource` is a generic catch-all tied to a provider, and the Docker provider doubles as both compute platform and resource provisioner. This refactor establishes the patterns needed for multi-cloud support (Azure, AWS, etc.) by making each concept independent and composable.

**Goal:** An agent definition where Provider is a cloud account, Platform is where the agent runs, and services (sessions, memory, etc.) are independently typed and optionally provisioned.

## What Changes

### Before (current)

```python
docker = ast.Provider(name="docker", type="docker")

agent = ast.Agent(
    name="support-bot",
    model=model,
    resources=[
        ast.Resource(name="sessions", provider=docker, engine="postgres"),
    ],
    platform=ast.Platform(name="docker", type="docker", provider=docker),
)
```

Problems:
- `Resource` is generic — `engine="postgres"` is a string, no type safety
- Provider, platform, and resource provisioner are conflated into one `docker` provider
- No way to bring-your-own resource without a provider
- `sessions` and `memory` are buried in a list — not obvious from the agent shape
- Adding a new cloud means teaching one provider to do everything

### After (new)

```python
docker = ast.Provider(name="docker", type="docker")
anthropic = ast.Provider(name="anthropic", type="anthropic")
model = ast.Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")

agent = ast.Agent(
    name="support-bot",
    model=model,
    platform=ast.Platform(type="docker", provider=docker),
    sessions=ast.Postgres(provider=docker),
    memory=ast.Postgres(provider=docker),
    services=[
        ast.Redis(name="cache", provider=docker),
    ],
)

# Bring your own — no provider, skip provisioning
agent2 = ast.Agent(
    name="other-bot",
    model=model,
    platform=ast.Platform(type="docker", provider=docker),
    sessions=ast.Postgres(connection_string_env="DATABASE_URL"),
)

# Multi-cloud — Azure compute, existing Postgres
azure = ast.Provider(name="azure", type="azure", config={"location": "eastus2"})

agent3 = ast.Agent(
    name="cloud-bot",
    model=model,
    platform=ast.Platform(type="container-apps", provider=azure),
    sessions=ast.Postgres(provider=azure, config={"sku": "Standard_B1ms"}),
)
```

## Schema Changes

### 1. Provider — no changes

Provider stays as-is. It represents a cloud account or service: `docker`, `azure`, `anthropic`, etc.

```python
class Provider(NamedModel):
    type: str
    config: dict = {}
```

### 2. Platform — minor changes

Platform already has `type`, `provider`, and `config`. No structural changes needed. We just use `type` values more precisely:

| `type` value | Provider | What it means |
|---|---|---|
| `docker` | `docker` | Local Docker containers |
| `container-apps` | `azure` | Azure Container Apps |
| `ecs` | `aws` | (future) AWS ECS/Fargate |
| `cloud-run` | `gcp` | (future) Google Cloud Run |

Platform `config` holds compute-specific settings:

```python
ast.Platform(
    type="container-apps",
    provider=azure,
    config={
        "cpu": 1.0,
        "memory": "2Gi",
        "min_replicas": 1,
        "max_replicas": 5,
        "ingress": "external",
        "environment": "my-existing-env",  # use existing ACA Environment
        "registry": "myacr.azurecr.io",   # use existing ACR
    },
)
```

### 3. Service — replaces Resource

Replace the generic `Resource` model with a `Service` base class and typed subclasses. Each service type knows its engine and has typed config.

```python
class Service(BaseModel):
    """Base for infrastructure services an agent depends on."""
    name: str = ""
    provider: Provider | None = None
    connection_string_env: str | None = None
    config: dict = {}

    @property
    def is_managed(self) -> bool:
        """True if AgentStack should provision this service."""
        return self.provider is not None and self.connection_string_env is None


class Postgres(Service):
    """PostgreSQL database service."""
    engine: str = "postgres"


class Sqlite(Service):
    """SQLite database service."""
    engine: str = "sqlite"


class Redis(Service):
    """Redis cache/store service."""
    engine: str = "redis"


class Qdrant(Service):
    """Qdrant vector database service."""
    engine: str = "qdrant"
```

The `engine` field is kept for serialization and provider dispatch but is set automatically by the type. The `name` field defaults to empty and is auto-generated from context when not specified (e.g., `sessions` field generates name `"sessions"`).

**Bring-your-own pattern:** When `connection_string_env` is set, the service is treated as external. No provider is needed, no provisioning happens. The env var is passed through to the container.

**Provisioned pattern:** When `provider` is set and `connection_string_env` is not, the platform provider provisions the service. Provider-specific config (SKU, storage, version) goes in `config`.

### 4. Agent — new fields, deprecate `resources`

```python
class Agent(NamedModel):
    instructions: str | None = None
    model: Model
    skills: list[Skill] = []
    channels: list[Channel] = []
    mcp_servers: list[McpServer] = []
    workspace: Workspace | None = None
    guardrails: dict | None = None
    secrets: list[Secret] = []
    platform: Platform | None = None
    port: int | None = None

    # New: first-class agent concerns
    sessions: Service | None = None
    memory: Service | None = None

    # New: additional infrastructure services
    services: list[Service] = []

    # Deprecated: kept for backward compatibility during migration
    resources: list[Resource] = []
```

**`sessions`** — conversation persistence (checkpointer). Maps to what `_get_session_store()` does today.

**`memory`** — long-term memory store. Maps to what the memory system uses today.

**`services`** — additional infra the agent needs (cache, vector store, queue, etc.).

**`resources`** — deprecated. Kept temporarily. The loader, CLI, and providers will read from `sessions`/`memory`/`services` first, falling back to `resources` for existing YAML files. Removed in a future version.

### 5. YAML format — new shape

**New format:**

```yaml
name: support-bot
model:
  name: claude
  provider: { name: anthropic, type: anthropic }
  model_name: claude-sonnet-4-20250514
platform:
  type: docker
  provider: { name: docker, type: docker }
sessions:
  type: postgres
  provider: { name: docker, type: docker }
memory:
  type: postgres
  provider: { name: docker, type: docker }
services:
  - name: cache
    type: redis
    provider: { name: docker, type: docker }
skills:
  - name: assistant
    tools: [get_weather]
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
```

**Bring-your-own in YAML:**

```yaml
sessions:
  type: postgres
  connection_string_env: DATABASE_URL
```

**YAML type discriminator:** The `type` field in YAML (`type: postgres`) maps to the Service subclass (`Postgres`). The loader uses a discriminated union: `type: postgres` → `Postgres(...)`, `type: redis` → `Redis(...)`. In Python code, you use the class directly (`ast.Postgres(...)`) so the `type` field is only relevant for YAML/JSON deserialization.

**Backward compatibility:** The loader detects old-format `resources` list and maps it to the new fields with a deprecation warning. `resources[engine=postgres/sqlite]` with name `sessions` maps to `agent.sessions`. This is a temporary bridge.

### 6. Service name auto-generation

When `sessions` or `memory` fields don't specify a name, the agent auto-assigns one based on the field:

```python
@model_validator(mode="after")
def _assign_service_names(self) -> Self:
    if self.sessions and not self.sessions.name:
        self.sessions.name = "sessions"
    if self.memory and not self.memory.name:
        self.memory.name = "memory"
    return self
```

## Impact on Existing Packages

### agentstack (core)

- Add `Service`, `Postgres`, `Sqlite`, `Redis`, `Qdrant` to `schema/service.py` (new file)
- Add `sessions`, `memory`, `services` fields to `Agent`
- Keep `resources` field for backward compat, add deprecation
- Update `schema/__init__.py` and top-level `__init__.py` exports
- Update hash engine to include `sessions`, `memory`, `services` in agent hash
- Update loader to handle both old and new YAML formats
- Keep `Resource` and subclasses for backward compat (deprecated)

### agentstack-adapter-langchain

- Update `_get_session_store()` to read from `agent.sessions` first, fall back to `agent.resources`
- Update `generate_server_py()` for memory store from `agent.memory`
- No changes to generated code shape — the adapter still produces the same LangGraph + FastAPI output

### agentstack-provider-docker

- Update `apply()` to read from `agent.sessions`/`agent.memory`/`agent.services` instead of `agent.resources`
- Dispatch provisioning based on service type (`Postgres`, `Sqlite`, `Redis`)
- `_build_env()` reads connection strings from the new service fields
- `destroy()` destroys services by iterating `sessions` + `memory` + `services`

### agentstack-cli

- Update `init` command to generate YAML in new format
- Update `plan` output to show sessions/memory/services instead of resources
- No changes to `apply`/`destroy`/`status`/`logs` — they delegate to the provider

### agentstack-chat

- No changes. Chat client talks to the agent's HTTP API, not the schema.

### agentstack-gateway

- No changes. Gateway routes to agent URLs, doesn't interact with resources.

### Examples

- Update `hello-agent/agentstack.yaml` to new format
- Update multi-agent examples to new format
- Old format still works (backward compat) but examples should demonstrate the new way

### Tests

- Add tests for new `Service` types and their validation
- Add tests for `sessions`/`memory`/`services` fields on Agent
- Add tests for `is_managed` property
- Add tests for backward-compat `resources` → `sessions` migration in loader
- Update existing tests that construct Agent with `resources` to use new fields
- Keep some tests that verify old `resources` format still works

## Migration Path

1. **Phase 1a — Add new types** (non-breaking): Add `Service`, `Postgres`, `Sqlite`, etc. Add `sessions`, `memory`, `services` fields to Agent. All optional, existing code works unchanged.

2. **Phase 1b — Update consumers** (non-breaking): Update adapter, provider, CLI to prefer new fields. Fall back to `resources` when new fields are absent. Existing YAML and Python definitions still work.

3. **Phase 1c — Update examples and docs** (non-breaking): Rewrite examples and README to use new format. Old format still works but is not shown.

4. **Phase 1d — Deprecation** (non-breaking): Add deprecation warnings when `resources` is used. Suggest migration path in the warning message.

5. **(Future) Remove** — Remove `resources` field and `Resource` class in a future major version.

## What This Enables

With this refactor complete, adding a new cloud provider (e.g., `agentstack-provider-azure`) requires:

1. A `Provider(type="azure")` that handles authentication (az CLI / service principal)
2. A platform handler for `type="container-apps"` that provisions ACA
3. Service handlers for `Postgres` (Azure Database for PostgreSQL), `Redis` (Azure Cache for Redis), etc.

Each is independent. The agent definition stays the same — only the provider references change. This is the "define once, deploy everywhere" promise.

## Out of Scope

- Azure provider implementation (Phase 2)
- New service types beyond Postgres/Sqlite/Redis/Qdrant
- Provider registry / plugin discovery system
- Breaking removal of `resources` field
