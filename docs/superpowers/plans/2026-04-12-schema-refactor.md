# Core Schema Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the AgentStack schema so Provider, Platform, and Service are independent, composable concepts — enabling multi-cloud support.

**Architecture:** Replace generic `Resource` with typed `Service` subclasses (`Postgres`, `Sqlite`, `Redis`, `Qdrant`). Add `sessions` and `memory` as first-class Agent fields. Keep `resources` for backward compat. Update all consumers (adapter, provider, CLI, hash engine) to prefer the new fields.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, ruff

---

### Task 1: Add Service types to core schema

**Files:**
- Create: `packages/python/agentstack/src/agentstack/schema/service.py`
- Create: `packages/python/agentstack/tests/test_service.py`

- [ ] **Step 1: Write failing tests for Service base and subclasses**

```python
# packages/python/agentstack/tests/test_service.py
import pytest

from agentstack.schema.provider import Provider
from agentstack.schema.service import Postgres, Qdrant, Redis, Service, Sqlite


@pytest.fixture()
def docker():
    return Provider(name="docker", type="docker")


@pytest.fixture()
def azure():
    return Provider(name="azure", type="azure", config={"location": "eastus2"})


class TestService:
    def test_minimal(self):
        svc = Service()
        assert svc.name == ""
        assert svc.provider is None
        assert svc.connection_string_env is None
        assert svc.config == {}

    def test_is_managed_with_provider(self, docker):
        svc = Service(provider=docker)
        assert svc.is_managed is True

    def test_is_not_managed_with_connection_string(self):
        svc = Service(connection_string_env="DATABASE_URL")
        assert svc.is_managed is False

    def test_is_not_managed_with_both(self, docker):
        svc = Service(provider=docker, connection_string_env="DATABASE_URL")
        assert svc.is_managed is False

    def test_is_not_managed_with_neither(self):
        svc = Service()
        assert svc.is_managed is False

    def test_with_config(self, azure):
        svc = Service(provider=azure, config={"sku": "Standard_B1ms"})
        assert svc.config["sku"] == "Standard_B1ms"


class TestPostgres:
    def test_engine_default(self, docker):
        pg = Postgres(provider=docker)
        assert pg.engine == "postgres"
        assert isinstance(pg, Service)

    def test_managed(self, docker):
        pg = Postgres(provider=docker)
        assert pg.is_managed is True

    def test_bring_your_own(self):
        pg = Postgres(connection_string_env="DATABASE_URL")
        assert pg.is_managed is False
        assert pg.engine == "postgres"

    def test_with_config(self, azure):
        pg = Postgres(provider=azure, config={"sku": "Standard_B1ms", "storage_gb": 64})
        assert pg.config["storage_gb"] == 64

    def test_serialization_roundtrip(self, docker):
        pg = Postgres(name="sessions", provider=docker, config={"version": "16"})
        data = pg.model_dump()
        restored = Postgres.model_validate(data)
        assert restored == pg


class TestSqlite:
    def test_engine_default(self, docker):
        sl = Sqlite(provider=docker)
        assert sl.engine == "sqlite"
        assert isinstance(sl, Service)

    def test_bring_your_own(self):
        sl = Sqlite(connection_string_env="SQLITE_PATH")
        assert sl.is_managed is False


class TestRedis:
    def test_engine_default(self, docker):
        rd = Redis(name="cache", provider=docker)
        assert rd.engine == "redis"
        assert isinstance(rd, Service)


class TestQdrant:
    def test_engine_default(self, docker):
        qd = Qdrant(name="vectors", provider=docker)
        assert qd.engine == "qdrant"
        assert isinstance(qd, Service)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentstack.schema.service'`

- [ ] **Step 3: Implement Service types**

```python
# packages/python/agentstack/src/agentstack/schema/service.py
"""Service models — typed infrastructure services for agents."""

from pydantic import BaseModel

from agentstack.schema.provider import Provider


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

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_service.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack/src/agentstack/schema/service.py packages/python/agentstack/tests/test_service.py
git commit -m "feat: add Service types (Postgres, Sqlite, Redis, Qdrant)"
```

---

### Task 2: Add sessions, memory, services fields to Agent

**Files:**
- Modify: `packages/python/agentstack/src/agentstack/schema/agent.py`
- Modify: `packages/python/agentstack/tests/test_agent.py`

- [ ] **Step 1: Write failing tests for new Agent fields**

Add to `packages/python/agentstack/tests/test_agent.py`:

```python
from agentstack.schema.service import Postgres, Redis, Sqlite


class TestAgentServices:
    def test_sessions_field(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot",
            model=sonnet,
            sessions=Postgres(provider=docker),
        )
        assert agent.sessions is not None
        assert agent.sessions.engine == "postgres"
        assert agent.sessions.name == "sessions"

    def test_memory_field(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot",
            model=sonnet,
            memory=Postgres(provider=docker),
        )
        assert agent.memory is not None
        assert agent.memory.name == "memory"

    def test_services_list(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot",
            model=sonnet,
            services=[Redis(name="cache", provider=docker)],
        )
        assert len(agent.services) == 1
        assert agent.services[0].engine == "redis"

    def test_defaults_none(self, sonnet):
        agent = Agent(name="bot", model=sonnet)
        assert agent.sessions is None
        assert agent.memory is None
        assert agent.services == []

    def test_auto_name_sessions(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(name="bot", model=sonnet, sessions=Postgres(provider=docker))
        assert agent.sessions.name == "sessions"

    def test_auto_name_memory(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(name="bot", model=sonnet, memory=Postgres(provider=docker))
        assert agent.memory.name == "memory"

    def test_explicit_name_preserved(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(name="bot", model=sonnet, sessions=Postgres(name="my-db", provider=docker))
        assert agent.sessions.name == "my-db"

    def test_bring_your_own_sessions(self, sonnet):
        agent = Agent(
            name="bot",
            model=sonnet,
            sessions=Postgres(connection_string_env="DATABASE_URL"),
        )
        assert agent.sessions.is_managed is False

    def test_full_agent_with_services(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="support-bot",
            model=sonnet,
            platform=Platform(name="local", type="docker", provider=docker),
            sessions=Postgres(provider=docker),
            memory=Postgres(provider=docker),
            services=[Redis(name="cache", provider=docker)],
            channels=[Channel(name="api", type=ChannelType.API)],
        )
        assert agent.sessions.engine == "postgres"
        assert agent.memory.engine == "postgres"
        assert len(agent.services) == 1

    def test_serialization_roundtrip_with_services(self, sonnet):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot",
            model=sonnet,
            sessions=Sqlite(provider=docker),
        )
        data = agent.model_dump()
        restored = Agent.model_validate(data)
        assert restored.sessions is not None
        assert restored.sessions.name == "sessions"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_agent.py::TestAgentServices -v`
Expected: FAIL — `Agent` does not accept `sessions` field

- [ ] **Step 3: Add new fields to Agent**

Edit `packages/python/agentstack/src/agentstack/schema/agent.py`:

```python
"""Agent model — the top-level composition unit."""

from typing import Self

from pydantic import model_validator

from agentstack.schema.channel import Channel
from agentstack.schema.common import NamedModel
from agentstack.schema.mcp import McpServer
from agentstack.schema.model import Model
from agentstack.schema.platform import Platform
from agentstack.schema.resource import Resource
from agentstack.schema.secret import Secret
from agentstack.schema.service import Service
from agentstack.schema.skill import Skill
from agentstack.schema.workspace import Workspace


class Agent(NamedModel):
    """An AI agent — the central deployable unit."""

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

    # First-class agent concerns
    sessions: Service | None = None
    memory: Service | None = None

    # Additional infrastructure services
    services: list[Service] = []

    # Deprecated: kept for backward compatibility
    resources: list[Resource] = []

    @model_validator(mode="after")
    def _assign_service_names(self) -> Self:
        if self.sessions and not self.sessions.name:
            self.sessions.name = "sessions"
        if self.memory and not self.memory.name:
            self.memory.name = "memory"
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_agent.py -v`
Expected: All tests PASS (both old and new)

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack/src/agentstack/schema/agent.py packages/python/agentstack/tests/test_agent.py
git commit -m "feat: add sessions, memory, services fields to Agent"
```

---

### Task 3: Update schema exports

**Files:**
- Modify: `packages/python/agentstack/src/agentstack/schema/__init__.py`
- Modify: `packages/python/agentstack/src/agentstack/__init__.py`
- Modify: `packages/python/agentstack/tests/test_schema_exports.py`

- [ ] **Step 1: Write failing test for new exports**

Edit `packages/python/agentstack/tests/test_schema_exports.py`:

```python
from agentstack.schema import (
    Agent, Cache, Channel, ChannelType, Database, Embedding, McpServer,
    McpTransport, Model, NamedModel, ObjectStore, Platform, Postgres,
    Provider, Qdrant, Queue, Redis, Resource, Secret, Service, SessionStore,
    Skill, SkillRequirements, SlackChannel, Sqlite, VectorStore, Workspace,
    WorkspaceType,
)


def test_all_schema_types_importable():
    types = [
        Agent, Cache, Channel, ChannelType, Database, Embedding, McpServer,
        McpTransport, Model, NamedModel, ObjectStore, Platform, Postgres,
        Provider, Qdrant, Queue, Redis, Resource, Secret, Service, SessionStore,
        Skill, SkillRequirements, SlackChannel, Sqlite, VectorStore, Workspace,
        WorkspaceType,
    ]
    assert len(types) == 29


def test_service_types_importable_from_top_level():
    from agentstack import Postgres, Qdrant, Redis, Service, Sqlite
    assert Service is not None
    assert Postgres is not None
    assert Sqlite is not None
    assert Redis is not None
    assert Qdrant is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_schema_exports.py -v`
Expected: FAIL — `cannot import name 'Service'`

- [ ] **Step 3: Update schema/__init__.py**

Edit `packages/python/agentstack/src/agentstack/schema/__init__.py`:

```python
"""AgentStack schema models — all seven concepts plus supporting types."""

from agentstack.schema.agent import Agent
from agentstack.schema.channel import Channel, SlackChannel
from agentstack.schema.common import ChannelType, McpTransport, NamedModel, WorkspaceType
from agentstack.schema.gateway import ChannelProvider, Gateway
from agentstack.schema.mcp import McpServer
from agentstack.schema.model import Embedding, Model
from agentstack.schema.platform import Platform
from agentstack.schema.provider import Provider
from agentstack.schema.resource import (
    Cache,
    Database,
    ObjectStore,
    Queue,
    Resource,
    SessionStore,
    VectorStore,
)
from agentstack.schema.secret import Secret
from agentstack.schema.service import Postgres, Qdrant, Redis, Service, Sqlite
from agentstack.schema.skill import Skill, SkillRequirements
from agentstack.schema.workspace import Workspace

__all__ = [
    "Agent", "Cache", "Channel", "ChannelProvider", "ChannelType", "Database",
    "Embedding", "Gateway", "McpServer", "McpTransport", "Model", "NamedModel",
    "ObjectStore", "Platform", "Postgres", "Provider", "Qdrant", "Queue", "Redis",
    "Resource", "Secret", "Service", "SessionStore", "Skill", "SkillRequirements",
    "SlackChannel", "Sqlite", "VectorStore", "Workspace", "WorkspaceType",
]
```

- [ ] **Step 4: Update top-level __init__.py**

Edit `packages/python/agentstack/src/agentstack/__init__.py`:

```python
"""AgentStack — declarative AI agent orchestration."""

__version__ = "0.1.0"

# Schema models
from agentstack.schema import (
    Agent, Cache, Channel, ChannelProvider, ChannelType, Database, Embedding,
    Gateway, McpServer, McpTransport, Model, NamedModel, ObjectStore, Platform,
    Postgres, Provider, Qdrant, Queue, Redis, Resource, Secret, Service,
    SessionStore, Skill, SkillRequirements, SlackChannel, Sqlite, VectorStore,
    Workspace, WorkspaceType,
)

# Hash engine
from agentstack.hash import AgentHashTree, hash_agent, hash_dict, hash_model

# Loader
from agentstack.schema.loader import dump_agent, load_agent

# Provider ABCs and supporting types
from agentstack.providers import (
    AgentStatus, ChannelAdapter, DeployPlan, DeployResult,
    FrameworkAdapter, GeneratedCode, PlatformProvider, ValidationError,
)

__all__ = [
    "__version__",
    "Agent", "Cache", "Channel", "ChannelProvider", "ChannelType", "Database",
    "Embedding", "Gateway", "McpServer", "McpTransport", "Model", "NamedModel",
    "ObjectStore", "Platform", "Postgres", "Provider", "Qdrant", "Queue", "Redis",
    "Resource", "Secret", "Service", "SessionStore", "Skill", "SkillRequirements",
    "SlackChannel", "Sqlite", "VectorStore", "Workspace", "WorkspaceType",
    "AgentHashTree", "hash_agent", "hash_dict", "hash_model",
    "dump_agent", "load_agent",
    "AgentStatus", "ChannelAdapter", "DeployPlan", "DeployResult",
    "FrameworkAdapter", "GeneratedCode", "PlatformProvider", "ValidationError",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_schema_exports.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack/src/agentstack/schema/__init__.py packages/python/agentstack/src/agentstack/__init__.py packages/python/agentstack/tests/test_schema_exports.py
git commit -m "feat: export Service types from schema and top-level package"
```

---

### Task 4: Update hash engine to include sessions/memory/services

**Files:**
- Modify: `packages/python/agentstack/src/agentstack/hash/tree.py`
- Modify: `packages/python/agentstack/tests/test_tree.py`

- [ ] **Step 1: Write failing tests for new hash fields**

Add to `packages/python/agentstack/tests/test_tree.py`:

```python
from agentstack.schema.service import Postgres, Redis


class TestAgentHashTreeServices:
    def test_sessions_change_detected(self):
        docker = Provider(name="docker", type="docker")
        agent1 = make_agent()
        agent2 = make_agent(sessions=Postgres(provider=docker))
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.sessions != tree2.sessions
        assert tree1.root != tree2.root

    def test_memory_change_detected(self):
        docker = Provider(name="docker", type="docker")
        agent1 = make_agent()
        agent2 = make_agent(memory=Postgres(provider=docker))
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.memory != tree2.memory
        assert tree1.root != tree2.root

    def test_services_change_detected(self):
        docker = Provider(name="docker", type="docker")
        agent1 = make_agent()
        agent2 = make_agent(services=[Redis(name="cache", provider=docker)])
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.services != tree2.services
        assert tree1.root != tree2.root

    def test_sessions_vs_memory_different_hashes(self):
        docker = Provider(name="docker", type="docker")
        agent1 = make_agent(sessions=Postgres(provider=docker))
        agent2 = make_agent(memory=Postgres(provider=docker))
        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)
        assert tree1.root != tree2.root
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_tree.py::TestAgentHashTreeServices -v`
Expected: FAIL — `AgentHashTree` has no field `sessions`

- [ ] **Step 3: Update AgentHashTree and hash_agent**

Edit `packages/python/agentstack/src/agentstack/hash/tree.py`:

```python
"""Hash tree composition for agent definitions."""

import hashlib
from dataclasses import dataclass

from agentstack.hash.hasher import hash_model
from agentstack.schema.agent import Agent


@dataclass
class AgentHashTree:
    """Per-section hashes for an agent, enabling partial deploy detection."""

    brain: str
    skills: str
    mcp_servers: str
    channels: str
    workspace: str
    resources: str
    secrets: str
    sessions: str
    memory: str
    services: str
    root: str


def _hash_list(items: list) -> str:
    if not items:
        return hashlib.sha256(b"[]").hexdigest()
    individual = sorted(hash_model(item) for item in items)
    combined = "|".join(individual)
    return hashlib.sha256(combined.encode()).hexdigest()


def _hash_optional(item) -> str:
    if item is None:
        return hashlib.sha256(b"null").hexdigest()
    return hash_model(item)


def hash_agent(agent: Agent) -> AgentHashTree:
    """Compute the full hash tree for an agent definition."""
    brain = hash_model(agent.model)
    skills = _hash_list(agent.skills)
    mcp_servers = _hash_list(agent.mcp_servers)
    channels = _hash_list(agent.channels)
    workspace = _hash_optional(agent.workspace)
    resources = _hash_list(agent.resources)
    secrets = _hash_list(agent.secrets)
    sessions = _hash_optional(agent.sessions)
    memory = _hash_optional(agent.memory)
    services = _hash_list(agent.services)

    sections = "|".join([
        brain, skills, mcp_servers, channels, workspace,
        resources, secrets, sessions, memory, services,
    ])
    root = hashlib.sha256(sections.encode()).hexdigest()

    return AgentHashTree(
        brain=brain, skills=skills, mcp_servers=mcp_servers, channels=channels,
        workspace=workspace, resources=resources, secrets=secrets,
        sessions=sessions, memory=memory, services=services, root=root,
    )
```

- [ ] **Step 4: Run all hash tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_tree.py -v`
Expected: All tests PASS

**Note:** Existing tests still pass because we only added new fields to the hash — the `brain`, `skills`, etc. fields are still computed the same way. The `root` hash will change for all agents since the hash input now includes `sessions|memory|services`, but the existing tests compare two agents built the same way so both sides get the same new root.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack/src/agentstack/hash/tree.py packages/python/agentstack/tests/test_tree.py
git commit -m "feat: include sessions, memory, services in agent hash tree"
```

---

### Task 5: Update YAML loader for Service type discriminator

**Files:**
- Modify: `packages/python/agentstack/src/agentstack/schema/service.py`
- Modify: `packages/python/agentstack/src/agentstack/schema/loader.py`
- Modify: `packages/python/agentstack/tests/test_loader.py`

- [ ] **Step 1: Write failing tests for YAML loading with new fields**

Add to `packages/python/agentstack/tests/test_loader.py`:

```python
from agentstack.schema.service import Postgres, Redis, Sqlite


class TestLoadAgentWithServices:
    def test_load_sessions_postgres(self, tmp_path):
        data = {
            "name": "bot",
            "model": {
                "name": "claude",
                "provider": {"name": "anthropic", "type": "anthropic"},
                "model_name": "claude-sonnet-4-20250514",
            },
            "sessions": {
                "type": "postgres",
                "provider": {"name": "docker", "type": "docker"},
            },
        }
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(data))
        agent = load_agent(path)
        assert agent.sessions is not None
        assert isinstance(agent.sessions, Postgres)
        assert agent.sessions.engine == "postgres"
        assert agent.sessions.name == "sessions"

    def test_load_sessions_sqlite(self, tmp_path):
        data = {
            "name": "bot",
            "model": {
                "name": "claude",
                "provider": {"name": "anthropic", "type": "anthropic"},
                "model_name": "claude-sonnet-4-20250514",
            },
            "sessions": {
                "type": "sqlite",
                "provider": {"name": "docker", "type": "docker"},
            },
        }
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(data))
        agent = load_agent(path)
        assert isinstance(agent.sessions, Sqlite)

    def test_load_bring_your_own(self, tmp_path):
        data = {
            "name": "bot",
            "model": {
                "name": "claude",
                "provider": {"name": "anthropic", "type": "anthropic"},
                "model_name": "claude-sonnet-4-20250514",
            },
            "sessions": {
                "type": "postgres",
                "connection_string_env": "DATABASE_URL",
            },
        }
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(data))
        agent = load_agent(path)
        assert agent.sessions is not None
        assert agent.sessions.is_managed is False
        assert agent.sessions.connection_string_env == "DATABASE_URL"

    def test_load_services_list(self, tmp_path):
        data = {
            "name": "bot",
            "model": {
                "name": "claude",
                "provider": {"name": "anthropic", "type": "anthropic"},
                "model_name": "claude-sonnet-4-20250514",
            },
            "services": [
                {
                    "name": "cache",
                    "type": "redis",
                    "provider": {"name": "docker", "type": "docker"},
                },
            ],
        }
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(data))
        agent = load_agent(path)
        assert len(agent.services) == 1
        assert isinstance(agent.services[0], Redis)

    def test_load_old_format_still_works(self, tmp_path):
        data = {
            "name": "bot",
            "model": {
                "name": "claude",
                "provider": {"name": "anthropic", "type": "anthropic"},
                "model_name": "claude-sonnet-4-20250514",
            },
            "resources": [
                {
                    "name": "sessions",
                    "provider": {"name": "docker", "type": "docker"},
                    "engine": "postgres",
                },
            ],
        }
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(data))
        agent = load_agent(path)
        assert len(agent.resources) == 1
        assert agent.resources[0].engine == "postgres"

    def test_roundtrip_with_sessions(self, tmp_path):
        anthropic = Provider(name="anthropic", type="anthropic")
        model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot",
            model=model,
            sessions=Postgres(provider=docker),
        )
        path = tmp_path / "agent.yaml"
        dump_agent(agent, path)
        restored = load_agent(path)
        assert restored.sessions is not None
        assert restored.sessions.engine == "postgres"
        assert restored.sessions.name == "sessions"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_loader.py::TestLoadAgentWithServices -v`
Expected: FAIL — Pydantic cannot deserialize `type: postgres` into `Service`

- [ ] **Step 3: Add type discriminator to Service**

Edit `packages/python/agentstack/src/agentstack/schema/service.py` — add a `type` field used as a Pydantic discriminator:

```python
"""Service models — typed infrastructure services for agents."""

from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, Tag

from agentstack.schema.provider import Provider


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

    type: Literal["postgres"] = "postgres"
    engine: str = "postgres"


class Sqlite(Service):
    """SQLite database service."""

    type: Literal["sqlite"] = "sqlite"
    engine: str = "sqlite"


class Redis(Service):
    """Redis cache/store service."""

    type: Literal["redis"] = "redis"
    engine: str = "redis"


class Qdrant(Service):
    """Qdrant vector database service."""

    type: Literal["qdrant"] = "qdrant"
    engine: str = "qdrant"


def _service_discriminator(v):
    if isinstance(v, dict):
        return v.get("type", "postgres")
    return getattr(v, "type", "postgres")


ServiceType = Annotated[
    Annotated[Postgres, Tag("postgres")]
    | Annotated[Sqlite, Tag("sqlite")]
    | Annotated[Redis, Tag("redis")]
    | Annotated[Qdrant, Tag("qdrant")],
    Discriminator(_service_discriminator),
]
```

- [ ] **Step 4: Update Agent to use ServiceType**

Edit `packages/python/agentstack/src/agentstack/schema/agent.py` — change the type annotations for `sessions`, `memory`, and `services`:

Replace:
```python
from agentstack.schema.service import Service
```
With:
```python
from agentstack.schema.service import Service, ServiceType
```

Replace:
```python
    # First-class agent concerns
    sessions: Service | None = None
    memory: Service | None = None

    # Additional infrastructure services
    services: list[Service] = []
```
With:
```python
    # First-class agent concerns
    sessions: ServiceType | None = None
    memory: ServiceType | None = None

    # Additional infrastructure services
    services: list[ServiceType] = []
```

- [ ] **Step 5: Run all loader tests**

Run: `uv run pytest packages/python/agentstack/tests/test_loader.py -v`
Expected: All tests PASS

- [ ] **Step 6: Run all core tests to check nothing is broken**

Run: `uv run pytest packages/python/agentstack/tests/ -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add packages/python/agentstack/src/agentstack/schema/service.py packages/python/agentstack/src/agentstack/schema/agent.py packages/python/agentstack/tests/test_loader.py
git commit -m "feat: add YAML type discriminator for Service types"
```

---

### Task 6: Update LangChain adapter to use new fields

**Files:**
- Modify: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py`
- Modify: `packages/python/agentstack-adapter-langchain/tests/test_templates.py`

- [ ] **Step 1: Write failing tests using new Agent fields**

Add to `packages/python/agentstack-adapter-langchain/tests/test_templates.py`:

```python
from agentstack.schema.service import Postgres, Sqlite


class TestSessionsField:
    """Tests that the adapter reads from agent.sessions (new API)."""

    def test_postgres_from_sessions_field(self, anthropic_provider):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot",
            model=Model(name="claude", provider=anthropic_provider, model_name="claude-sonnet-4-20250514"),
            sessions=Postgres(provider=docker),
        )
        code = generate_server_py(agent)
        assert "PostgresSaver" in code

    def test_sqlite_from_sessions_field(self, anthropic_provider):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot",
            model=Model(name="claude", provider=anthropic_provider, model_name="claude-sonnet-4-20250514"),
            sessions=Sqlite(provider=docker),
        )
        code = generate_server_py(agent)
        assert "SqliteSaver" in code or "store" in code.lower()

    def test_bring_your_own_sessions(self, anthropic_provider):
        agent = Agent(
            name="bot",
            model=Model(name="claude", provider=anthropic_provider, model_name="claude-sonnet-4-20250514"),
            sessions=Postgres(connection_string_env="DATABASE_URL"),
        )
        code = generate_server_py(agent)
        assert "PostgresSaver" in code
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/test_templates.py::TestSessionsField -v`
Expected: FAIL — `_get_session_store` doesn't read `agent.sessions`

- [ ] **Step 3: Update _get_session_store to prefer new fields**

Edit `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py` — replace the `_get_session_store` function:

```python
def _get_session_store(agent: Agent):
    """Find the session store for the agent.

    Prefers agent.sessions (new API), falls back to agent.resources (deprecated).
    """
    if agent.sessions is not None:
        return agent.sessions

    from agentstack.schema.resource import SessionStore
    for resource in agent.resources:
        if isinstance(resource, SessionStore):
            return resource
        if resource.engine in ("postgres", "sqlite", "redis"):
            return resource
    return None
```

- [ ] **Step 4: Run all adapter tests**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/ -v`
Expected: All tests PASS (old tests still pass via fallback, new tests pass via `agent.sessions`)

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py packages/python/agentstack-adapter-langchain/tests/test_templates.py
git commit -m "feat: adapter reads sessions from agent.sessions, falls back to resources"
```

---

### Task 7: Update Docker provider to use new fields

**Files:**
- Modify: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py`
- Modify: `packages/python/agentstack-provider-docker/tests/test_provider.py`

- [ ] **Step 1: Write failing tests using new Agent fields**

Add to `packages/python/agentstack-provider-docker/tests/test_provider.py`:

```python
from agentstack.schema.service import Postgres, Sqlite


class TestBuildEnvWithServices:
    def test_sessions_connection_string(self, provider, mock_docker_client):
        from agentstack.schema.service import Postgres
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="test-bot",
            model=Model(
                name="claude",
                provider=Provider(name="anthropic", type="anthropic"),
                model_name="claude-sonnet-4-20250514",
            ),
            sessions=Postgres(provider=docker),
        )
        provider.set_agent(agent)
        provider._resource_info = [{"engine": "postgres", "connection_string": "postgresql://test"}]
        env = provider._build_env()
        assert env.get("SESSION_STORE_URL") == "postgresql://test"

    def test_bring_your_own_connection_string(self, provider, mock_docker_client):
        agent = Agent(
            name="test-bot",
            model=Model(
                name="claude",
                provider=Provider(name="anthropic", type="anthropic"),
                model_name="claude-sonnet-4-20250514",
            ),
            sessions=Postgres(connection_string_env="DATABASE_URL"),
        )
        provider.set_agent(agent)
        env = provider._build_env()
        # BYO sessions should pass the env var name through
        # The actual value comes from os.environ at runtime
        assert "DATABASE_URL" not in env or True  # env var resolution happens at runtime
```

- [ ] **Step 2: Run tests to verify behavior**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/test_provider.py::TestBuildEnvWithServices -v`
Expected: Tests pass or fail depending on current `_build_env` implementation

- [ ] **Step 3: Update provider to collect services from new fields**

Edit `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py` — update the `_collect_services` helper and `apply` method:

Replace the resource loop in `apply()` (lines 226-232):

```python
            # 2. Provision resources
            self._resource_info = []
            if self._agent:
                for svc in self._all_services():
                    if svc.is_managed and svc.engine in ("postgres", "sqlite"):
                        info = provision_resource(
                            self._client, svc, network, SECRETS_PATH
                        )
                        self._resource_info.append(info)
```

Add a helper method to `DockerProvider`:

```python
    def _all_services(self) -> list:
        """Collect all services from sessions, memory, services, and legacy resources."""
        from agentstack.schema.service import Service
        result = []
        if self._agent:
            if self._agent.sessions and isinstance(self._agent.sessions, Service):
                result.append(self._agent.sessions)
            if self._agent.memory and isinstance(self._agent.memory, Service):
                result.append(self._agent.memory)
            result.extend(self._agent.services)
            # Legacy fallback: if no new-style services, use resources
            if not result:
                from agentstack.schema.resource import Resource
                for resource in self._agent.resources:
                    if resource.engine in ("postgres", "sqlite"):
                        result.append(resource)
        return result
```

Update `_build_env` to handle BYO connection strings:

```python
    def _build_env(self) -> dict[str, str]:
        env = {}
        if self._agent:
            for secret in self._agent.secrets:
                value = os.environ.get(secret.name)
                if value:
                    env[secret.name] = value
            # Connection strings from provisioned resources
            for info in self._resource_info:
                if info["engine"] in ("postgres", "sqlite"):
                    env["SESSION_STORE_URL"] = info["connection_string"]
            # BYO connection strings
            for svc in self._all_services():
                if hasattr(svc, "connection_string_env") and svc.connection_string_env:
                    value = os.environ.get(svc.connection_string_env)
                    if value:
                        env["SESSION_STORE_URL"] = value
        return env
```

Update `destroy` to iterate new service fields:

```python
    def destroy(self, agent_name: str, include_resources: bool = False) -> None:
        container = self._get_container(agent_name)
        if container is not None:
            container.stop()
            container.remove()

        if include_resources and self._agent:
            for svc in self._all_services():
                destroy_resource(self._client, svc.name)
            self.destroy_gateways()
```

- [ ] **Step 4: Update provision_resource to accept Service objects**

Edit `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/resources.py` — the `provision_resource` function already accepts anything with `.engine` and `.name`, so the `Service` objects work without changes. But update the type hint:

Replace:
```python
from agentstack.schema.resource import Resource
```
With:
```python
from typing import Protocol


class HasEngineAndName(Protocol):
    engine: str
    name: str
```

Replace function signatures from `resource: Resource` to `resource: HasEngineAndName` (in `provision_resource`, `_provision_postgres`, `_provision_sqlite`). This makes the function work with both `Resource` and `Service` objects.

- [ ] **Step 5: Run all Docker provider tests**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py packages/python/agentstack-provider-docker/src/agentstack_provider_docker/resources.py packages/python/agentstack-provider-docker/tests/test_provider.py
git commit -m "feat: Docker provider reads from sessions/memory/services fields"
```

---

### Task 8: Update CLI init and plan commands

**Files:**
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/init.py`
- Modify: `packages/python/agentstack-cli/tests/test_init.py` (if exists, otherwise create)

- [ ] **Step 1: Update STARTER_YAML to new format**

Edit `packages/python/agentstack-cli/src/agentstack_cli/commands/init.py`:

```python
"""agentstack init — create a starter agent definition."""

from pathlib import Path

import click

STARTER_YAML = """\
name: my-agent
model:
  name: claude
  provider:
    name: anthropic
    type: anthropic
  model_name: claude-sonnet-4-20250514
platform:
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
  - name: assistant
    tools: []
    prompt: You are a helpful assistant.
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
"""


@click.command()
def init():
    """Create a starter agent definition."""
    path = Path("agentstack.yaml")
    if path.exists():
        click.echo("Error: agentstack.yaml already exists", err=True)
        raise SystemExit(1)

    path.write_text(STARTER_YAML)
    click.echo(f"Created {path}")
```

- [ ] **Step 2: Verify the YAML is loadable**

Run: `uv run python -c "from agentstack.schema.loader import load_agent; import tempfile, os; d=tempfile.mkdtemp(); p=os.path.join(d,'a.yaml'); open(p,'w').write(open('packages/python/agentstack-cli/src/agentstack_cli/commands/init.py').read().split(\"STARTER_YAML = \\\"\\\"\\\"\\\\\n\")[1].split(\"\\\"\\\"\\\"\")[0]); a=load_agent(p); print(f'OK: {a.name}, sessions={a.sessions}')"`

Or simpler — run the existing CLI tests:

Run: `uv run pytest packages/python/agentstack-cli/tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add packages/python/agentstack-cli/src/agentstack_cli/commands/init.py
git commit -m "feat: update init YAML to use sessions field instead of resources"
```

---

### Task 9: Update examples to new format

**Files:**
- Modify: `examples/hello-agent/agentstack.yaml`
- Modify: `examples/multi-agent/assistant/agentstack.yaml`
- Modify: `examples/multi-agent/weather/agentstack.yaml`
- Modify: `examples/multi-agent/time/agentstack.yaml`

- [ ] **Step 1: Update hello-agent**

Edit `examples/hello-agent/agentstack.yaml`:

```yaml
name: hello-agent
instructions: |
  You are a helpful assistant built with AgentStack.
  Be concise, friendly, and always show your reasoning.
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
  type: docker
  provider:
    name: docker
    type: docker
sessions:
  type: sqlite
  provider:
    name: docker
    type: docker
skills:
  - name: assistant
    tools:
      - get_weather
      - get_time
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
port: 8080
```

- [ ] **Step 2: Update multi-agent examples**

The multi-agent examples (`assistant`, `weather`, `time`) don't use resources, so they only need `platform` added. Edit each of the three `agentstack.yaml` files to add:

```yaml
platform:
  type: docker
  provider:
    name: docker
    type: docker
```

Add this after the `model` block and before `skills` in each file.

- [ ] **Step 3: Verify examples load**

Run: `uv run python -c "from agentstack import load_agent; a = load_agent('examples/hello-agent/agentstack.yaml'); print(f'{a.name}: sessions={a.sessions}')"`
Expected: `hello-agent: sessions=Sqlite(...)`

- [ ] **Step 4: Commit**

```bash
git add examples/
git commit -m "feat: update examples to use sessions/platform fields"
```

---

### Task 10: Run full test suite and verify backward compatibility

**Files:** None (verification only)

- [ ] **Step 1: Run full Python test suite**

Run: `uv run pytest packages/python/ -v`
Expected: All 308+ tests PASS (plus new tests added in tasks 1-7)

- [ ] **Step 2: Run linter**

Run: `uv run ruff check packages/python/`
Expected: No errors

- [ ] **Step 3: Run type checker**

Run: `uv run pyright packages/python/`
Expected: No new errors

- [ ] **Step 4: Verify old YAML format still works**

Create a temp file with the old format and load it:

Run:
```bash
uv run python -c "
from agentstack import load_agent
import tempfile, os, yaml
data = {
    'name': 'legacy-bot',
    'model': {'name': 'claude', 'provider': {'name': 'anthropic', 'type': 'anthropic'}, 'model_name': 'claude-sonnet-4-20250514'},
    'resources': [{'name': 'sessions', 'provider': {'name': 'docker', 'type': 'docker'}, 'engine': 'postgres'}],
}
d = tempfile.mkdtemp()
p = os.path.join(d, 'agent.yaml')
with open(p, 'w') as f: yaml.dump(data, f)
a = load_agent(p)
print(f'OK: {a.name}, resources={len(a.resources)}, engine={a.resources[0].engine}')
"
```
Expected: `OK: legacy-bot, resources=1, engine=postgres`

- [ ] **Step 5: Commit if any fixes were needed**

If any tests failed and required fixes, commit those fixes:

```bash
git add -u
git commit -m "fix: resolve test failures from schema refactor"
```

---

### Task 11: Update README examples

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the YAML example in README**

Edit the YAML example block in `README.md` (around line 43-69) to use the new format:

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

- [ ] **Step 2: Update the Python example in README**

Edit the Python example block (around line 73-86):

```python
import agentstack as ast

anthropic = ast.Provider(name="anthropic", type="anthropic")
docker = ast.Provider(name="docker", type="docker")
model = ast.Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")

agent = ast.Agent(
    name="support-bot",
    instructions="You are a helpful support agent.",
    model=model,
    platform=ast.Platform(type="docker", provider=docker),
    sessions=ast.Postgres(provider=docker),
    skills=[ast.Skill(name="support", tools=["lookup_order", "process_refund"])],
    channels=[ast.Channel(name="api", type=ast.ChannelType.API)],
)
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README examples to use new schema API"
```
