# Core SDK Schema Layer — Design Spec

## Overview

Build the core schema layer for AgentStack: Pydantic models for all seven concepts (Agent, Skill, Channel, Resource, Workspace, Provider, Platform) plus McpServer, Secret, Model, and Embedding. Includes a hash engine for content-addressable change detection and provider ABCs for plugin contracts.

## Decisions

| Decision | Choice |
|----------|--------|
| Validation library | Pydantic v2 BaseModel |
| Serialization | Pydantic dict/JSON + PyYAML for YAML |
| Top-level API | Both namespace (`ast.Agent`) and direct imports |
| Hash approach | SHA-256 of canonical JSON, composed into tree structure |
| IR strategy | Schema IS the IR for now, separate IR deferred |
| Provider discovery | Explicit registration (ABC, no auto-discovery) |
| MCP support | Standalone McpServer model + skill `requires.mcp_servers` |
| Secrets | Progressive — simple env form + full secret store form |

## Dependencies

Added to `packages/python/agentstack/pyproject.toml`:
- `pydantic>=2.0`
- `pyyaml>=6.0`

## File Structure

```
packages/python/agentstack/src/agentstack/
├── __init__.py                    # re-exports all public API
├── schema/
│   ├── __init__.py                # re-exports all models
│   ├── common.py                  # NamedModel base, enums
│   ├── secret.py                  # Secret
│   ├── provider.py                # Provider
│   ├── model.py                   # Model, Embedding
│   ├── resource.py                # Resource, SessionStore, VectorStore, etc.
│   ├── workspace.py               # Workspace
│   ├── mcp.py                     # McpServer
│   ├── skill.py                   # Skill
│   ├── channel.py                 # Channel
│   ├── platform.py                # Platform
│   ├── agent.py                   # Agent (top-level, references everything)
│   └── loader.py                  # load_agent, dump_agent (YAML/JSON)
├── hash/
│   ├── __init__.py                # re-exports hash_agent, AgentHashTree
│   ├── hasher.py                  # hash_model, hash_dict
│   └── tree.py                    # hash_agent, AgentHashTree
├── providers/
│   ├── __init__.py                # re-exports base classes
│   └── base.py                    # FrameworkAdapter, PlatformProvider, ChannelAdapter ABCs
└── ir/                            # empty for now (schema IS the IR)
    └── __init__.py
```

## Schema Models

### common.py — shared types

`NamedModel` — Pydantic BaseModel subclass with a required `name: str` field. All concept models inherit from this.

Enums:
- `WorkspaceType`: sandbox, persistent, mounted
- `ChannelType`: api, slack, webhook, voice, cron, widget
- `McpTransport`: stdio, sse, streamable_http

### secret.py — Secret

```python
class Secret(NamedModel):
    name: str                          # secret identifier
    provider: Provider | None = None   # None = read from environment
    path: str | None = None            # path within secret store
    key: str | None = None             # specific key within a secret
```

Simple form: `Secret("ANTHROPIC_API_KEY")` — resolves from environment variable.
Full form: `Secret("api-key", provider=vault, path="secrets/anthropic")` — resolves from secret store.

### provider.py — Provider

```python
class Provider(NamedModel):
    name: str
    type: str                          # "aws", "anthropic", "docker", etc.
    config: dict = {}                  # provider-specific configuration
```

Config values may contain `Secret` references for sensitive fields (API keys, tokens).

### model.py — Model, Embedding

```python
class Model(NamedModel):
    name: str
    provider: Provider
    model_name: str                    # e.g., "claude-sonnet-4-20250514"
    parameters: dict = {}             # temperature, max_tokens, etc.

class Embedding(NamedModel):
    name: str
    provider: Provider
    model_name: str
    dimensions: int | None = None
```

### resource.py — Resource and subtypes

```python
class Resource(NamedModel):
    name: str
    provider: Provider
    engine: str                        # specific implementation
    config: dict = {}

class SessionStore(Resource): ...     # redis, elasticache, dynamodb, managed
class VectorStore(Resource): ...      # pinecone, chroma, qdrant, pgvector
class Database(Resource): ...         # postgres, dynamodb, mysql, sqlite
class Cache(Resource): ...            # redis, memcached
class ObjectStore(Resource): ...      # s3, gcs, minio, local
class Queue(Resource): ...            # sqs, rabbitmq, redis, kafka
```

Subtypes inherit from Resource. They exist for type safety and may gain subtype-specific fields later.

### workspace.py — Workspace

```python
class Workspace(NamedModel):
    name: str
    type: WorkspaceType                # sandbox, persistent, mounted
    provider: Provider | None = None
    filesystem: bool = False
    terminal: bool = False
    browser: bool = False
    network: bool = True
    gpu: bool = False
    timeout: str | None = None         # e.g., "30m"
    persist: bool = False
    path: str | None = None            # for mounted/persistent types
    max_size: str | None = None        # e.g., "100mb"
```

### mcp.py — McpServer

```python
class McpServer(NamedModel):
    name: str
    transport: McpTransport            # stdio, sse, streamable_http
    command: str | None = None         # for stdio transport
    url: str | None = None             # for sse/streamable_http
    args: list[str] | None = None
    env: dict | None = None            # may contain Secret references
    headers: dict | None = None        # may contain Secret references
```

### skill.py — Skill

```python
class SkillRequirements(BaseModel):
    session_store: bool = False
    workspace: dict | None = None      # capability requirements
    mcp_servers: list[str] | None = None  # names of required MCP servers

class Skill(NamedModel):
    name: str
    tools: list[str] = []
    prompt: str | None = None
    guardrails: dict | None = None
    requires: SkillRequirements | None = None
    version: str = "0.1.0"
    dependencies: list[str] | None = None  # other skills this depends on
```

### channel.py — Channel

```python
class Channel(NamedModel):
    name: str
    type: ChannelType                  # api, slack, webhook, voice, cron, widget
    config: dict = {}
```

### platform.py — Platform

```python
class Platform(NamedModel):
    name: str
    type: str                          # "docker", "agentcore", "gradient", etc.
    provider: Provider
    config: dict = {}
```

### agent.py — Agent

```python
class Agent(NamedModel):
    name: str
    model: Model
    skills: list[Skill] = []
    channels: list[Channel] = []
    mcp_servers: list[McpServer] = []
    workspace: Workspace | None = None
    guardrails: dict | None = None
    resources: list[Resource] = []
    secrets: list[Secret] = []
    platform: Platform | None = None
```

Agent is the top-level composition unit. It references all other models.

### loader.py — YAML/JSON loading

```python
def load_agent(path: str | Path) -> Agent:
    """Load an agent definition from a YAML or JSON file."""

def dump_agent(agent: Agent, path: str | Path, format: str = "yaml") -> None:
    """Serialize an agent definition to a YAML or JSON file."""
```

Uses Pydantic's `.model_validate()` and `.model_dump()` for conversion, PyYAML for YAML parsing/writing.

## Hash Engine

### hasher.py — leaf hashing

```python
def hash_model(model: BaseModel) -> str:
    """SHA-256 of canonical JSON (sorted keys, no whitespace)."""

def hash_dict(data: dict) -> str:
    """SHA-256 of canonical JSON for raw dicts."""
```

Canonical JSON ensures deterministic output regardless of field insertion order.

### tree.py — hash tree composition

```python
@dataclass
class AgentHashTree:
    brain: str           # hash of model config
    skills: str          # hash of sorted skill hashes
    mcp_servers: str     # hash of sorted MCP server hashes
    channels: str        # hash of sorted channel hashes
    workspace: str       # hash of workspace (or empty string hash)
    resources: str       # hash of sorted resource hashes
    secrets: str         # hash of sorted secret hashes
    root: str            # SHA-256 of all section hashes in fixed order

def hash_agent(agent: Agent) -> AgentHashTree:
    """Compute the full hash tree for an agent definition."""
```

Comparing two `AgentHashTree` objects reveals exactly which sections changed, enabling partial deploys.

## Provider ABCs

### base.py — plugin contracts

```python
class FrameworkAdapter(ABC):
    """Takes schema models, produces native framework code."""
    @abstractmethod
    def generate(self, agent: Agent) -> GeneratedCode: ...
    @abstractmethod
    def validate(self, agent: Agent) -> list[ValidationError]: ...

class PlatformProvider(ABC):
    """Deploys and manages agents on a specific platform."""
    @abstractmethod
    def plan(self, agent: Agent, current_hash: str | None) -> DeployPlan: ...
    @abstractmethod
    def apply(self, plan: DeployPlan) -> DeployResult: ...
    @abstractmethod
    def destroy(self, agent_name: str) -> None: ...
    @abstractmethod
    def status(self, agent_name: str) -> AgentStatus: ...
    @abstractmethod
    def get_hash(self, agent_name: str) -> str | None: ...

class ChannelAdapter(ABC):
    """I/O adapter between users and the agent."""
    @abstractmethod
    def setup(self, agent: Agent, channel: Channel) -> None: ...
    @abstractmethod
    def teardown(self, channel: Channel) -> None: ...
```

Supporting types:

```python
@dataclass
class GeneratedCode:
    files: dict[str, str]              # path -> content
    entrypoint: str                    # main file path

@dataclass
class DeployPlan:
    agent_name: str
    actions: list[str]                 # human-readable action descriptions
    current_hash: str | None
    target_hash: str
    changes: dict[str, tuple[str, str]]  # section -> (old_hash, new_hash)

@dataclass
class DeployResult:
    agent_name: str
    success: bool
    hash: str
    message: str

@dataclass
class AgentStatus:
    agent_name: str
    running: bool
    hash: str | None
    info: dict = field(default_factory=dict)

@dataclass
class ValidationError:
    field: str
    message: str
```

## Top-Level API

`agentstack/__init__.py` re-exports all public symbols:

**Schema models:** Agent, Skill, Channel, Resource, SessionStore, VectorStore, Database, Cache, ObjectStore, Queue, Workspace, Provider, Platform, Model, Embedding, McpServer, Secret

**Enums:** WorkspaceType, ChannelType, McpTransport

**Hash engine:** hash_agent, AgentHashTree

**Loader:** load_agent, dump_agent

**Provider ABCs:** FrameworkAdapter, PlatformProvider, ChannelAdapter

**Supporting types:** GeneratedCode, DeployPlan, DeployResult, AgentStatus, ValidationError

## Testing Strategy

One test file per module:
- `test_common.py` — NamedModel validation, enum values
- `test_secret.py` — simple form, full form, validation
- `test_provider.py` — creation, config with secrets
- `test_model.py` — Model and Embedding creation, parameter validation
- `test_resource.py` — Resource subtypes, engine/config validation
- `test_workspace.py` — workspace types, capability flags, validation
- `test_mcp.py` — transport types, stdio vs sse validation
- `test_skill.py` — tools, prompt, requirements, version
- `test_channel.py` — channel types, config
- `test_platform.py` — platform creation, provider reference
- `test_agent.py` — full agent composition, nested model validation
- `test_loader.py` — YAML/JSON round-trip, load from file, dump to file
- `test_hasher.py` — deterministic hashing, canonical JSON
- `test_tree.py` — hash tree composition, change detection, partial diff
- `test_base.py` — ABC contract enforcement, supporting types

Tests verify: validation (valid/invalid inputs), serialization round-trips, hash determinism, hash change detection, and ABC contract enforcement.

## What This Spec Does NOT Cover

- Implementation of any framework adapter, platform provider, or channel adapter
- CLI commands
- Harness architecture
- Skill loading from disk (the `skills/` directory structure)
- Agent runtime behavior
- TypeScript SDK (schema models are Python-only for MVP)
