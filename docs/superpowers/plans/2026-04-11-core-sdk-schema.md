# Core SDK Schema Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core schema layer with Pydantic models for all AgentStack concepts, a content-addressable hash engine, YAML/JSON serialization, and provider ABCs.

**Architecture:** Pydantic v2 BaseModel subclasses for all schema types, SHA-256 hash tree for change detection, ABC base classes for plugin contracts. Schema IS the IR for now.

**Tech Stack:** Python 3.11+, Pydantic v2, PyYAML, pytest

---

### Task 1: Dependencies and Foundation (common.py, secret.py, provider.py)

**Files:**
- Modify: `packages/python/agentstack/pyproject.toml`
- Create: `packages/python/agentstack/src/agentstack/schema/common.py`
- Create: `packages/python/agentstack/src/agentstack/schema/secret.py`
- Create: `packages/python/agentstack/src/agentstack/schema/provider.py`
- Create: `packages/python/agentstack/tests/test_common.py`
- Create: `packages/python/agentstack/tests/test_secret.py`
- Create: `packages/python/agentstack/tests/test_provider.py`

- [ ] **Step 1: Add dependencies to pyproject.toml**

Add `pydantic` and `pyyaml` to the project dependencies in `packages/python/agentstack/pyproject.toml`:

```toml
[project]
name = "agentstack"
version = "0.1.0"
description = "AgentStack core SDK — declarative AI agent orchestration"
requires-python = ">=3.11"
license = "Apache-2.0"
readme = "README.md"
dependencies = [
    "pydantic>=2.0",
    "pyyaml>=6.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentstack"]
```

- [ ] **Step 2: Run `uv sync` to install dependencies**

Run: `cd /Users/akolodkin/Developer/work/AgentsStack && uv sync`

Expected: dependencies install successfully.

- [ ] **Step 3: Write tests for common.py**

`packages/python/agentstack/tests/test_common.py`:
```python
import pytest
from pydantic import ValidationError

from agentstack.schema.common import (
    ChannelType,
    McpTransport,
    NamedModel,
    WorkspaceType,
)


class TestNamedModel:
    def test_create_with_name(self):
        model = NamedModel(name="test")
        assert model.name == "test"

    def test_name_required(self):
        with pytest.raises(ValidationError):
            NamedModel()

    def test_name_must_be_string(self):
        with pytest.raises(ValidationError):
            NamedModel(name=123)

    def test_empty_name_allowed(self):
        model = NamedModel(name="")
        assert model.name == ""


class TestWorkspaceType:
    def test_sandbox(self):
        assert WorkspaceType.SANDBOX == "sandbox"

    def test_persistent(self):
        assert WorkspaceType.PERSISTENT == "persistent"

    def test_mounted(self):
        assert WorkspaceType.MOUNTED == "mounted"


class TestChannelType:
    def test_all_types(self):
        expected = {"api", "slack", "webhook", "voice", "cron", "widget"}
        actual = {ct.value for ct in ChannelType}
        assert actual == expected


class TestMcpTransport:
    def test_all_transports(self):
        expected = {"stdio", "sse", "streamable_http"}
        actual = {mt.value for mt in McpTransport}
        assert actual == expected
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_common.py -v`

Expected: FAIL — `ModuleNotFoundError` because `common.py` only has a docstring.

- [ ] **Step 5: Implement common.py**

`packages/python/agentstack/src/agentstack/schema/common.py`:
```python
"""Shared base classes and enums for AgentStack schema models."""

from enum import StrEnum

from pydantic import BaseModel


class NamedModel(BaseModel):
    """Base model with a required name field. All concept models inherit from this."""

    name: str


class WorkspaceType(StrEnum):
    SANDBOX = "sandbox"
    PERSISTENT = "persistent"
    MOUNTED = "mounted"


class ChannelType(StrEnum):
    API = "api"
    SLACK = "slack"
    WEBHOOK = "webhook"
    VOICE = "voice"
    CRON = "cron"
    WIDGET = "widget"


class McpTransport(StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_common.py -v`

Expected: all tests PASS.

- [ ] **Step 7: Write tests for secret.py**

`packages/python/agentstack/tests/test_secret.py`:
```python
import pytest
from pydantic import ValidationError

from agentstack.schema.secret import Secret


class TestSecret:
    def test_simple_form(self):
        secret = Secret(name="ANTHROPIC_API_KEY")
        assert secret.name == "ANTHROPIC_API_KEY"
        assert secret.provider is None
        assert secret.path is None
        assert secret.key is None

    def test_full_form(self):
        from agentstack.schema.provider import Provider

        vault = Provider(name="vault", type="vault", config={"addr": "https://vault.example.com"})
        secret = Secret(name="api-key", provider=vault, path="secrets/anthropic", key="api_key")
        assert secret.provider.name == "vault"
        assert secret.path == "secrets/anthropic"
        assert secret.key == "api_key"

    def test_name_required(self):
        with pytest.raises(ValidationError):
            Secret()

    def test_serialization_roundtrip(self):
        secret = Secret(name="MY_SECRET", path="some/path")
        data = secret.model_dump()
        restored = Secret.model_validate(data)
        assert restored == secret
```

- [ ] **Step 8: Write tests for provider.py**

`packages/python/agentstack/tests/test_provider.py`:
```python
import pytest
from pydantic import ValidationError

from agentstack.schema.provider import Provider


class TestProvider:
    def test_create(self):
        provider = Provider(name="anthropic", type="anthropic")
        assert provider.name == "anthropic"
        assert provider.type == "anthropic"
        assert provider.config == {}

    def test_with_config(self):
        provider = Provider(
            name="aws",
            type="aws",
            config={"region": "us-east-1", "profile": "default"},
        )
        assert provider.config["region"] == "us-east-1"

    def test_name_required(self):
        with pytest.raises(ValidationError):
            Provider(type="aws")

    def test_type_required(self):
        with pytest.raises(ValidationError):
            Provider(name="aws")

    def test_serialization_roundtrip(self):
        provider = Provider(name="docker", type="docker", config={"socket": "/var/run/docker.sock"})
        data = provider.model_dump()
        restored = Provider.model_validate(data)
        assert restored == provider
```

- [ ] **Step 9: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_secret.py packages/python/agentstack/tests/test_provider.py -v`

Expected: FAIL — modules not found.

- [ ] **Step 10: Implement secret.py**

`packages/python/agentstack/src/agentstack/schema/secret.py`:
```python
"""Secret model — credential references with progressive complexity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentstack.schema.common import NamedModel

if TYPE_CHECKING:
    from agentstack.schema.provider import Provider


class Secret(NamedModel):
    """A reference to a secret value.

    Simple form: Secret(name="ENV_VAR") — resolves from environment.
    Full form: Secret(name="key", provider=vault, path="secrets/x") — resolves from store.
    """

    provider: Provider | None = None
    path: str | None = None
    key: str | None = None
```

Wait — we need to handle the forward reference. Since Secret references Provider and Provider might reference Secret in config, let's use Pydantic's model_rebuild. Actually, looking at the spec, Provider.config is `dict` so no circular ref. Secret references Provider directly. Let's use a direct import:

`packages/python/agentstack/src/agentstack/schema/secret.py`:
```python
"""Secret model — credential references with progressive complexity."""

from __future__ import annotations

from agentstack.schema.common import NamedModel


class Secret(NamedModel):
    """A reference to a secret value.

    Simple form: Secret(name="ENV_VAR") — resolves from environment.
    Full form: Secret(name="key", provider=vault, path="secrets/x") — resolves from store.
    """

    provider: Provider | None = None
    path: str | None = None
    key: str | None = None


# Deferred import to avoid circular dependency
from agentstack.schema.provider import Provider  # noqa: E402

Secret.model_rebuild()
```

Actually, this pattern is fragile. Better approach: since Provider is simple and doesn't reference Secret, just import it directly:

`packages/python/agentstack/src/agentstack/schema/secret.py`:
```python
"""Secret model — credential references with progressive complexity."""

from agentstack.schema.common import NamedModel
from agentstack.schema.provider import Provider


class Secret(NamedModel):
    """A reference to a secret value.

    Simple form: Secret(name="ENV_VAR") — resolves from environment.
    Full form: Secret(name="key", provider=vault, path="secrets/x") — resolves from store.
    """

    provider: Provider | None = None
    path: str | None = None
    key: str | None = None
```

- [ ] **Step 11: Implement provider.py**

`packages/python/agentstack/src/agentstack/schema/provider.py`:
```python
"""Provider model — who provisions infrastructure."""

from agentstack.schema.common import NamedModel


class Provider(NamedModel):
    """A provider that provisions infrastructure or services.

    Example: Provider(name="anthropic", type="anthropic", config={"api_key": Secret("KEY")})
    """

    type: str
    config: dict = {}
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_common.py packages/python/agentstack/tests/test_secret.py packages/python/agentstack/tests/test_provider.py -v`

Expected: all tests PASS.

- [ ] **Step 13: Commit**

```bash
git add packages/python/agentstack/
git commit -m "feat: add schema foundation — common, secret, provider"
```

---

### Task 2: Model, Embedding, Resource Subtypes

**Files:**
- Create: `packages/python/agentstack/src/agentstack/schema/model.py`
- Create: `packages/python/agentstack/src/agentstack/schema/resource.py`
- Create: `packages/python/agentstack/tests/test_model.py`
- Create: `packages/python/agentstack/tests/test_resource.py`

- [ ] **Step 1: Write tests for model.py**

`packages/python/agentstack/tests/test_model.py`:
```python
import pytest
from pydantic import ValidationError

from agentstack.schema.model import Embedding, Model
from agentstack.schema.provider import Provider


@pytest.fixture()
def anthropic():
    return Provider(name="anthropic", type="anthropic")


class TestModel:
    def test_create(self, anthropic):
        model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
        assert model.name == "claude"
        assert model.provider.name == "anthropic"
        assert model.model_name == "claude-sonnet-4-20250514"
        assert model.parameters == {}

    def test_with_parameters(self, anthropic):
        model = Model(
            name="claude",
            provider=anthropic,
            model_name="claude-sonnet-4-20250514",
            parameters={"temperature": 0.7, "max_tokens": 4096},
        )
        assert model.parameters["temperature"] == 0.7

    def test_provider_required(self):
        with pytest.raises(ValidationError):
            Model(name="claude", model_name="claude-sonnet-4-20250514")

    def test_model_name_required(self, anthropic):
        with pytest.raises(ValidationError):
            Model(name="claude", provider=anthropic)

    def test_serialization_roundtrip(self, anthropic):
        model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
        data = model.model_dump()
        restored = Model.model_validate(data)
        assert restored == model


class TestEmbedding:
    def test_create(self, anthropic):
        emb = Embedding(name="embed", provider=anthropic, model_name="text-embedding-3-small")
        assert emb.dimensions is None

    def test_with_dimensions(self, anthropic):
        emb = Embedding(
            name="embed",
            provider=anthropic,
            model_name="text-embedding-3-small",
            dimensions=1536,
        )
        assert emb.dimensions == 1536

    def test_serialization_roundtrip(self, anthropic):
        emb = Embedding(name="embed", provider=anthropic, model_name="text-embedding-3-small", dimensions=768)
        data = emb.model_dump()
        restored = Embedding.model_validate(data)
        assert restored == emb
```

- [ ] **Step 2: Write tests for resource.py**

`packages/python/agentstack/tests/test_resource.py`:
```python
import pytest

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


@pytest.fixture()
def aws():
    return Provider(name="aws", type="aws")


class TestResource:
    def test_create(self, aws):
        resource = Resource(name="db", provider=aws, engine="postgres")
        assert resource.name == "db"
        assert resource.engine == "postgres"
        assert resource.config == {}

    def test_with_config(self, aws):
        resource = Resource(
            name="db",
            provider=aws,
            engine="postgres",
            config={"host": "localhost", "port": 5432},
        )
        assert resource.config["port"] == 5432

    def test_serialization_roundtrip(self, aws):
        resource = Resource(name="db", provider=aws, engine="postgres", config={"host": "localhost"})
        data = resource.model_dump()
        restored = Resource.model_validate(data)
        assert restored == resource


class TestResourceSubtypes:
    def test_session_store(self, aws):
        store = SessionStore(name="sessions", provider=aws, engine="redis")
        assert isinstance(store, Resource)
        assert store.engine == "redis"

    def test_vector_store(self, aws):
        store = VectorStore(name="kb", provider=aws, engine="pinecone")
        assert isinstance(store, Resource)

    def test_database(self, aws):
        db = Database(name="main", provider=aws, engine="postgres")
        assert isinstance(db, Resource)

    def test_cache(self, aws):
        cache = Cache(name="cache", provider=aws, engine="redis")
        assert isinstance(cache, Resource)

    def test_object_store(self, aws):
        store = ObjectStore(name="files", provider=aws, engine="s3")
        assert isinstance(store, Resource)

    def test_queue(self, aws):
        queue = Queue(name="tasks", provider=aws, engine="sqs")
        assert isinstance(queue, Resource)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_model.py packages/python/agentstack/tests/test_resource.py -v`

Expected: FAIL — modules not found.

- [ ] **Step 4: Implement model.py**

`packages/python/agentstack/src/agentstack/schema/model.py`:
```python
"""Model and Embedding — AI model configuration."""

from agentstack.schema.common import NamedModel
from agentstack.schema.provider import Provider


class Model(NamedModel):
    """LLM connection configuration."""

    provider: Provider
    model_name: str
    parameters: dict = {}


class Embedding(NamedModel):
    """Embedding model configuration."""

    provider: Provider
    model_name: str
    dimensions: int | None = None
```

- [ ] **Step 5: Implement resource.py**

`packages/python/agentstack/src/agentstack/schema/resource.py`:
```python
"""Resource models — infrastructure backing for agents."""

from agentstack.schema.common import NamedModel
from agentstack.schema.provider import Provider


class Resource(NamedModel):
    """Base resource model. Every resource has a provider and engine."""

    provider: Provider
    engine: str
    config: dict = {}


class SessionStore(Resource):
    """Conversation state storage (redis, elasticache, dynamodb, managed)."""


class VectorStore(Resource):
    """Embeddings and RAG storage (pinecone, chroma, qdrant, pgvector)."""


class Database(Resource):
    """Structured data storage (postgres, dynamodb, mysql, sqlite)."""


class Cache(Resource):
    """Tool result caching (redis, memcached)."""


class ObjectStore(Resource):
    """File and artifact storage (s3, gcs, minio, local)."""


class Queue(Resource):
    """Async task processing (sqs, rabbitmq, redis, kafka)."""
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_model.py packages/python/agentstack/tests/test_resource.py -v`

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/python/agentstack/
git commit -m "feat: add model, embedding, and resource schema models"
```

---

### Task 3: Workspace, McpServer, Skill

**Files:**
- Create: `packages/python/agentstack/src/agentstack/schema/workspace.py`
- Create: `packages/python/agentstack/src/agentstack/schema/mcp.py`
- Create: `packages/python/agentstack/src/agentstack/schema/skill.py`
- Create: `packages/python/agentstack/tests/test_workspace.py`
- Create: `packages/python/agentstack/tests/test_mcp.py`
- Create: `packages/python/agentstack/tests/test_skill.py`

- [ ] **Step 1: Write tests for workspace.py**

`packages/python/agentstack/tests/test_workspace.py`:
```python
import pytest
from pydantic import ValidationError

from agentstack.schema.common import WorkspaceType
from agentstack.schema.provider import Provider
from agentstack.schema.workspace import Workspace


class TestWorkspace:
    def test_sandbox(self):
        ws = Workspace(name="dev", type=WorkspaceType.SANDBOX)
        assert ws.type == WorkspaceType.SANDBOX
        assert ws.filesystem is False
        assert ws.terminal is False
        assert ws.network is True
        assert ws.persist is False

    def test_sandbox_with_capabilities(self):
        ws = Workspace(
            name="dev",
            type=WorkspaceType.SANDBOX,
            filesystem=True,
            terminal=True,
            timeout="30m",
        )
        assert ws.filesystem is True
        assert ws.terminal is True
        assert ws.timeout == "30m"

    def test_persistent_with_path(self):
        ws = Workspace(
            name="research",
            type=WorkspaceType.PERSISTENT,
            persist=True,
            path="research/{agent}/",
            max_size="100mb",
        )
        assert ws.persist is True
        assert ws.path == "research/{agent}/"
        assert ws.max_size == "100mb"

    def test_mounted_with_provider(self):
        provider = Provider(name="gdrive", type="google-drive")
        ws = Workspace(
            name="docs",
            type=WorkspaceType.MOUNTED,
            provider=provider,
            path="/shared/invoices/",
        )
        assert ws.provider.name == "gdrive"

    def test_type_required(self):
        with pytest.raises(ValidationError):
            Workspace(name="dev")

    def test_serialization_roundtrip(self):
        ws = Workspace(name="dev", type=WorkspaceType.SANDBOX, filesystem=True, terminal=True)
        data = ws.model_dump()
        restored = Workspace.model_validate(data)
        assert restored == ws
```

- [ ] **Step 2: Write tests for mcp.py**

`packages/python/agentstack/tests/test_mcp.py`:
```python
import pytest
from pydantic import ValidationError

from agentstack.schema.common import McpTransport
from agentstack.schema.mcp import McpServer


class TestMcpServer:
    def test_stdio(self):
        mcp = McpServer(
            name="filesystem",
            transport=McpTransport.STDIO,
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        )
        assert mcp.transport == McpTransport.STDIO
        assert mcp.command == "npx"
        assert len(mcp.args) == 3

    def test_sse(self):
        mcp = McpServer(
            name="remote",
            transport=McpTransport.SSE,
            url="https://mcp.example.com/sse",
        )
        assert mcp.transport == McpTransport.SSE
        assert mcp.url == "https://mcp.example.com/sse"

    def test_streamable_http(self):
        mcp = McpServer(
            name="api",
            transport=McpTransport.STREAMABLE_HTTP,
            url="https://mcp.example.com/mcp",
            headers={"Authorization": "Bearer token"},
        )
        assert mcp.transport == McpTransport.STREAMABLE_HTTP
        assert mcp.headers["Authorization"] == "Bearer token"

    def test_with_env(self):
        mcp = McpServer(
            name="github",
            transport=McpTransport.STDIO,
            command="github-mcp",
            env={"GITHUB_TOKEN": "secret"},
        )
        assert mcp.env["GITHUB_TOKEN"] == "secret"

    def test_transport_required(self):
        with pytest.raises(ValidationError):
            McpServer(name="test")

    def test_serialization_roundtrip(self):
        mcp = McpServer(name="test", transport=McpTransport.STDIO, command="test-mcp")
        data = mcp.model_dump()
        restored = McpServer.model_validate(data)
        assert restored == mcp
```

- [ ] **Step 3: Write tests for skill.py**

`packages/python/agentstack/tests/test_skill.py`:
```python
import pytest

from agentstack.schema.skill import Skill, SkillRequirements


class TestSkillRequirements:
    def test_defaults(self):
        req = SkillRequirements()
        assert req.session_store is False
        assert req.workspace is None
        assert req.mcp_servers is None

    def test_with_values(self):
        req = SkillRequirements(
            session_store=True,
            workspace={"filesystem": True, "terminal": True},
            mcp_servers=["github", "filesystem"],
        )
        assert req.session_store is True
        assert req.workspace["filesystem"] is True
        assert len(req.mcp_servers) == 2


class TestSkill:
    def test_minimal(self):
        skill = Skill(name="greeting")
        assert skill.name == "greeting"
        assert skill.tools == []
        assert skill.prompt is None
        assert skill.version == "0.1.0"

    def test_full(self):
        skill = Skill(
            name="refund-handling",
            tools=["lookup_order", "check_policy", "process_refund"],
            prompt="When handling refunds, always verify the order exists first.",
            guardrails={"max_amount": 500, "require_reason": True},
            requires=SkillRequirements(session_store=True, mcp_servers=["stripe"]),
            version="1.0.0",
            dependencies=["order-tracking"],
        )
        assert len(skill.tools) == 3
        assert skill.requires.session_store is True
        assert skill.requires.mcp_servers == ["stripe"]
        assert skill.dependencies == ["order-tracking"]

    def test_serialization_roundtrip(self):
        skill = Skill(
            name="test",
            tools=["tool_a", "tool_b"],
            prompt="Do the thing.",
            requires=SkillRequirements(session_store=True),
        )
        data = skill.model_dump()
        restored = Skill.model_validate(data)
        assert restored == skill
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_workspace.py packages/python/agentstack/tests/test_mcp.py packages/python/agentstack/tests/test_skill.py -v`

Expected: FAIL — modules not found.

- [ ] **Step 5: Implement workspace.py**

`packages/python/agentstack/src/agentstack/schema/workspace.py`:
```python
"""Workspace model — agent execution environment."""

from agentstack.schema.common import NamedModel, WorkspaceType
from agentstack.schema.provider import Provider


class Workspace(NamedModel):
    """Execution environment an agent operates in."""

    type: WorkspaceType
    provider: Provider | None = None
    filesystem: bool = False
    terminal: bool = False
    browser: bool = False
    network: bool = True
    gpu: bool = False
    timeout: str | None = None
    persist: bool = False
    path: str | None = None
    max_size: str | None = None
```

- [ ] **Step 6: Implement mcp.py**

`packages/python/agentstack/src/agentstack/schema/mcp.py`:
```python
"""McpServer model — MCP tool provider connections."""

from agentstack.schema.common import McpTransport, NamedModel


class McpServer(NamedModel):
    """An MCP server that provides tools to an agent."""

    transport: McpTransport
    command: str | None = None
    url: str | None = None
    args: list[str] | None = None
    env: dict | None = None
    headers: dict | None = None
```

- [ ] **Step 7: Implement skill.py**

`packages/python/agentstack/src/agentstack/schema/skill.py`:
```python
"""Skill model — reusable capability bundles."""

from pydantic import BaseModel

from agentstack.schema.common import NamedModel


class SkillRequirements(BaseModel):
    """What a skill needs from the agent environment."""

    session_store: bool = False
    workspace: dict | None = None
    mcp_servers: list[str] | None = None


class Skill(NamedModel):
    """A reusable bundle of tools, prompts, guardrails, and requirements."""

    tools: list[str] = []
    prompt: str | None = None
    guardrails: dict | None = None
    requires: SkillRequirements | None = None
    version: str = "0.1.0"
    dependencies: list[str] | None = None
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_workspace.py packages/python/agentstack/tests/test_mcp.py packages/python/agentstack/tests/test_skill.py -v`

Expected: all tests PASS.

- [ ] **Step 9: Commit**

```bash
git add packages/python/agentstack/
git commit -m "feat: add workspace, mcp server, and skill schema models"
```

---

### Task 4: Channel, Platform, Agent

**Files:**
- Create: `packages/python/agentstack/src/agentstack/schema/channel.py`
- Create: `packages/python/agentstack/src/agentstack/schema/platform.py`
- Create: `packages/python/agentstack/src/agentstack/schema/agent.py`
- Create: `packages/python/agentstack/tests/test_channel.py`
- Create: `packages/python/agentstack/tests/test_platform.py`
- Create: `packages/python/agentstack/tests/test_agent.py`

- [ ] **Step 1: Write tests for channel.py**

`packages/python/agentstack/tests/test_channel.py`:
```python
import pytest
from pydantic import ValidationError

from agentstack.schema.channel import Channel
from agentstack.schema.common import ChannelType


class TestChannel:
    def test_api(self):
        ch = Channel(name="rest", type=ChannelType.API)
        assert ch.type == ChannelType.API
        assert ch.config == {}

    def test_slack_with_config(self):
        ch = Channel(
            name="support-slack",
            type=ChannelType.SLACK,
            config={"channel": "#support", "bot_token_secret": "SLACK_TOKEN"},
        )
        assert ch.type == ChannelType.SLACK
        assert ch.config["channel"] == "#support"

    def test_type_required(self):
        with pytest.raises(ValidationError):
            Channel(name="test")

    def test_serialization_roundtrip(self):
        ch = Channel(name="api", type=ChannelType.API, config={"cors": True})
        data = ch.model_dump()
        restored = Channel.model_validate(data)
        assert restored == ch
```

- [ ] **Step 2: Write tests for platform.py**

`packages/python/agentstack/tests/test_platform.py`:
```python
import pytest
from pydantic import ValidationError

from agentstack.schema.platform import Platform
from agentstack.schema.provider import Provider


class TestPlatform:
    def test_create(self):
        docker = Provider(name="docker", type="docker")
        platform = Platform(name="local", type="docker", provider=docker)
        assert platform.type == "docker"
        assert platform.provider.name == "docker"
        assert platform.config == {}

    def test_with_config(self):
        aws = Provider(name="aws", type="aws")
        platform = Platform(
            name="prod",
            type="agentcore",
            provider=aws,
            config={"region": "us-east-1"},
        )
        assert platform.config["region"] == "us-east-1"

    def test_provider_required(self):
        with pytest.raises(ValidationError):
            Platform(name="local", type="docker")

    def test_serialization_roundtrip(self):
        docker = Provider(name="docker", type="docker")
        platform = Platform(name="local", type="docker", provider=docker)
        data = platform.model_dump()
        restored = Platform.model_validate(data)
        assert restored == platform
```

- [ ] **Step 3: Write tests for agent.py**

`packages/python/agentstack/tests/test_agent.py`:
```python
import pytest
from pydantic import ValidationError

from agentstack.schema.agent import Agent
from agentstack.schema.channel import Channel
from agentstack.schema.common import ChannelType, McpTransport, WorkspaceType
from agentstack.schema.mcp import McpServer
from agentstack.schema.model import Model
from agentstack.schema.platform import Platform
from agentstack.schema.provider import Provider
from agentstack.schema.resource import SessionStore
from agentstack.schema.secret import Secret
from agentstack.schema.skill import Skill
from agentstack.schema.workspace import Workspace


@pytest.fixture()
def anthropic():
    return Provider(name="anthropic", type="anthropic")


@pytest.fixture()
def sonnet(anthropic):
    return Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514")


class TestAgent:
    def test_minimal(self, sonnet):
        agent = Agent(name="bot", model=sonnet)
        assert agent.name == "bot"
        assert agent.model.model_name == "claude-sonnet-4-20250514"
        assert agent.skills == []
        assert agent.channels == []
        assert agent.mcp_servers == []
        assert agent.workspace is None
        assert agent.resources == []
        assert agent.secrets == []
        assert agent.platform is None

    def test_full_agent(self, sonnet):
        docker_provider = Provider(name="docker", type="docker")
        aws_provider = Provider(name="aws", type="aws")

        agent = Agent(
            name="support-bot",
            model=sonnet,
            skills=[
                Skill(name="refund-handling", tools=["lookup_order", "process_refund"]),
                Skill(name="order-tracking", tools=["get_order_status"]),
            ],
            channels=[
                Channel(name="api", type=ChannelType.API),
                Channel(name="slack", type=ChannelType.SLACK, config={"channel": "#support"}),
            ],
            mcp_servers=[
                McpServer(name="github", transport=McpTransport.STDIO, command="github-mcp"),
            ],
            workspace=Workspace(name="sandbox", type=WorkspaceType.SANDBOX, filesystem=True),
            guardrails={"max_response_length": 2000},
            resources=[
                SessionStore(name="sessions", provider=aws_provider, engine="redis"),
            ],
            secrets=[
                Secret(name="ANTHROPIC_API_KEY"),
            ],
            platform=Platform(name="local", type="docker", provider=docker_provider),
        )
        assert len(agent.skills) == 2
        assert len(agent.channels) == 2
        assert len(agent.mcp_servers) == 1
        assert agent.workspace.filesystem is True
        assert len(agent.resources) == 1
        assert len(agent.secrets) == 1
        assert agent.platform.type == "docker"

    def test_model_required(self):
        with pytest.raises(ValidationError):
            Agent(name="bot")

    def test_serialization_roundtrip(self, sonnet):
        agent = Agent(
            name="bot",
            model=sonnet,
            skills=[Skill(name="greeting", tools=["say_hello"])],
            channels=[Channel(name="api", type=ChannelType.API)],
        )
        data = agent.model_dump()
        restored = Agent.model_validate(data)
        assert restored == agent
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_channel.py packages/python/agentstack/tests/test_platform.py packages/python/agentstack/tests/test_agent.py -v`

Expected: FAIL — modules not found.

- [ ] **Step 5: Implement channel.py**

`packages/python/agentstack/src/agentstack/schema/channel.py`:
```python
"""Channel model — I/O adapter for agent communication."""

from agentstack.schema.common import ChannelType, NamedModel


class Channel(NamedModel):
    """An I/O adapter that connects users to an agent."""

    type: ChannelType
    config: dict = {}
```

- [ ] **Step 6: Implement platform.py**

`packages/python/agentstack/src/agentstack/schema/platform.py`:
```python
"""Platform model — deployment target for agents."""

from agentstack.schema.common import NamedModel
from agentstack.schema.provider import Provider


class Platform(NamedModel):
    """A deployment target where agents run."""

    type: str
    provider: Provider
    config: dict = {}
```

- [ ] **Step 7: Implement agent.py**

`packages/python/agentstack/src/agentstack/schema/agent.py`:
```python
"""Agent model — the top-level composition unit."""

from agentstack.schema.channel import Channel
from agentstack.schema.common import NamedModel
from agentstack.schema.mcp import McpServer
from agentstack.schema.model import Model
from agentstack.schema.platform import Platform
from agentstack.schema.resource import Resource
from agentstack.schema.secret import Secret
from agentstack.schema.skill import Skill
from agentstack.schema.workspace import Workspace


class Agent(NamedModel):
    """An AI agent — the central deployable unit."""

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

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_channel.py packages/python/agentstack/tests/test_platform.py packages/python/agentstack/tests/test_agent.py -v`

Expected: all tests PASS.

- [ ] **Step 9: Commit**

```bash
git add packages/python/agentstack/
git commit -m "feat: add channel, platform, and agent schema models"
```

---

### Task 5: Schema __init__.py Re-exports

**Files:**
- Modify: `packages/python/agentstack/src/agentstack/schema/__init__.py`

- [ ] **Step 1: Write test for schema re-exports**

`packages/python/agentstack/tests/test_schema_exports.py`:
```python
from agentstack.schema import (
    Agent,
    Cache,
    Channel,
    ChannelType,
    Database,
    Embedding,
    McpServer,
    McpTransport,
    Model,
    NamedModel,
    ObjectStore,
    Platform,
    Provider,
    Queue,
    Resource,
    Secret,
    SessionStore,
    Skill,
    SkillRequirements,
    VectorStore,
    Workspace,
    WorkspaceType,
)


def test_all_schema_types_importable():
    """Verify all schema types are re-exported from agentstack.schema."""
    types = [
        Agent, Cache, Channel, ChannelType, Database, Embedding, McpServer,
        McpTransport, Model, NamedModel, ObjectStore, Platform, Provider,
        Queue, Resource, Secret, SessionStore, Skill, SkillRequirements,
        VectorStore, Workspace, WorkspaceType,
    ]
    assert len(types) == 22
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/agentstack/tests/test_schema_exports.py -v`

Expected: FAIL — `ImportError` because `__init__.py` doesn't re-export yet.

- [ ] **Step 3: Implement schema/__init__.py**

`packages/python/agentstack/src/agentstack/schema/__init__.py`:
```python
"""AgentStack schema models — all seven concepts plus supporting types."""

from agentstack.schema.agent import Agent
from agentstack.schema.channel import Channel
from agentstack.schema.common import ChannelType, McpTransport, NamedModel, WorkspaceType
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
from agentstack.schema.skill import Skill, SkillRequirements
from agentstack.schema.workspace import Workspace

__all__ = [
    "Agent",
    "Cache",
    "Channel",
    "ChannelType",
    "Database",
    "Embedding",
    "McpServer",
    "McpTransport",
    "Model",
    "NamedModel",
    "ObjectStore",
    "Platform",
    "Provider",
    "Queue",
    "Resource",
    "Secret",
    "SessionStore",
    "Skill",
    "SkillRequirements",
    "VectorStore",
    "Workspace",
    "WorkspaceType",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_schema_exports.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack/
git commit -m "feat: add schema re-exports from agentstack.schema"
```

---

### Task 6: YAML/JSON Loader

**Files:**
- Create: `packages/python/agentstack/src/agentstack/schema/loader.py`
- Create: `packages/python/agentstack/tests/test_loader.py`

- [ ] **Step 1: Write tests for loader.py**

`packages/python/agentstack/tests/test_loader.py`:
```python
import json
from pathlib import Path

import pytest

from agentstack.schema.agent import Agent
from agentstack.schema.common import ChannelType
from agentstack.schema.loader import dump_agent, load_agent


@pytest.fixture()
def sample_agent_dict():
    return {
        "name": "test-bot",
        "model": {
            "name": "claude",
            "provider": {"name": "anthropic", "type": "anthropic"},
            "model_name": "claude-sonnet-4-20250514",
        },
        "skills": [{"name": "greeting", "tools": ["say_hello"]}],
        "channels": [{"name": "api", "type": "api"}],
    }


class TestLoadAgent:
    def test_load_yaml(self, tmp_path, sample_agent_dict):
        import yaml

        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(sample_agent_dict))

        agent = load_agent(path)
        assert agent.name == "test-bot"
        assert agent.model.model_name == "claude-sonnet-4-20250514"
        assert len(agent.skills) == 1
        assert agent.channels[0].type == ChannelType.API

    def test_load_json(self, tmp_path, sample_agent_dict):
        path = tmp_path / "agent.json"
        path.write_text(json.dumps(sample_agent_dict))

        agent = load_agent(path)
        assert agent.name == "test-bot"

    def test_load_yml_extension(self, tmp_path, sample_agent_dict):
        import yaml

        path = tmp_path / "agent.yml"
        path.write_text(yaml.dump(sample_agent_dict))

        agent = load_agent(path)
        assert agent.name == "test-bot"

    def test_load_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            load_agent("/nonexistent/path.yaml")

    def test_load_unsupported_extension(self, tmp_path):
        path = tmp_path / "agent.toml"
        path.write_text("")
        with pytest.raises(ValueError, match="Unsupported file format"):
            load_agent(path)


class TestDumpAgent:
    def test_dump_yaml(self, tmp_path):
        import yaml

        from agentstack.schema.model import Model
        from agentstack.schema.provider import Provider

        anthropic = Provider(name="anthropic", type="anthropic")
        model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
        agent = Agent(name="test-bot", model=model)

        path = tmp_path / "agent.yaml"
        dump_agent(agent, path)

        loaded = yaml.safe_load(path.read_text())
        assert loaded["name"] == "test-bot"
        assert loaded["model"]["model_name"] == "claude-sonnet-4-20250514"

    def test_dump_json(self, tmp_path):
        from agentstack.schema.model import Model
        from agentstack.schema.provider import Provider

        anthropic = Provider(name="anthropic", type="anthropic")
        model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
        agent = Agent(name="test-bot", model=model)

        path = tmp_path / "agent.json"
        dump_agent(agent, path, format="json")

        loaded = json.loads(path.read_text())
        assert loaded["name"] == "test-bot"

    def test_roundtrip_yaml(self, tmp_path):
        from agentstack.schema.channel import Channel
        from agentstack.schema.model import Model
        from agentstack.schema.provider import Provider
        from agentstack.schema.skill import Skill

        anthropic = Provider(name="anthropic", type="anthropic")
        model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
        agent = Agent(
            name="test-bot",
            model=model,
            skills=[Skill(name="greeting", tools=["say_hello"])],
            channels=[Channel(name="api", type=ChannelType.API)],
        )

        path = tmp_path / "agent.yaml"
        dump_agent(agent, path)
        restored = load_agent(path)
        assert restored == agent
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_loader.py -v`

Expected: FAIL — module not found.

- [ ] **Step 3: Implement loader.py**

`packages/python/agentstack/src/agentstack/schema/loader.py`:
```python
"""YAML/JSON loading and dumping for agent definitions."""

import json
from pathlib import Path

import yaml

from agentstack.schema.agent import Agent


def load_agent(path: str | Path) -> Agent:
    """Load an agent definition from a YAML or JSON file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Agent definition not found: {path}")

    text = path.read_text()
    suffix = path.suffix.lower()

    if suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Use .yaml, .yml, or .json")

    return Agent.model_validate(data)


def dump_agent(agent: Agent, path: str | Path, format: str = "yaml") -> None:
    """Serialize an agent definition to a YAML or JSON file."""
    path = Path(path)
    data = agent.model_dump(mode="python")

    if format == "yaml":
        text = yaml.dump(data, default_flow_style=False, sort_keys=False)
    elif format == "json":
        text = json.dumps(data, indent=2, default=str)
    else:
        raise ValueError(f"Unsupported format: {format}. Use 'yaml' or 'json'")

    path.write_text(text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_loader.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack/
git commit -m "feat: add YAML/JSON loader for agent definitions"
```

---

### Task 7: Hash Engine

**Files:**
- Create: `packages/python/agentstack/src/agentstack/hash/hasher.py`
- Create: `packages/python/agentstack/src/agentstack/hash/tree.py`
- Modify: `packages/python/agentstack/src/agentstack/hash/__init__.py`
- Create: `packages/python/agentstack/tests/test_hasher.py`
- Create: `packages/python/agentstack/tests/test_tree.py`

- [ ] **Step 1: Write tests for hasher.py**

`packages/python/agentstack/tests/test_hasher.py`:
```python
from pydantic import BaseModel

from agentstack.hash.hasher import hash_dict, hash_model


class SimpleModel(BaseModel):
    name: str
    value: int


class TestHashModel:
    def test_deterministic(self):
        model = SimpleModel(name="test", value=42)
        hash1 = hash_model(model)
        hash2 = hash_model(model)
        assert hash1 == hash2

    def test_different_values_different_hash(self):
        model1 = SimpleModel(name="test", value=42)
        model2 = SimpleModel(name="test", value=43)
        assert hash_model(model1) != hash_model(model2)

    def test_field_order_irrelevant(self):
        """Canonical JSON sorts keys, so field order doesn't matter."""
        model1 = SimpleModel(name="test", value=42)
        model2 = SimpleModel(value=42, name="test")
        assert hash_model(model1) == hash_model(model2)

    def test_returns_hex_string(self):
        model = SimpleModel(name="test", value=42)
        h = hash_model(model)
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest


class TestHashDict:
    def test_deterministic(self):
        data = {"a": 1, "b": 2}
        assert hash_dict(data) == hash_dict(data)

    def test_key_order_irrelevant(self):
        data1 = {"a": 1, "b": 2}
        data2 = {"b": 2, "a": 1}
        assert hash_dict(data1) == hash_dict(data2)

    def test_different_values_different_hash(self):
        data1 = {"a": 1}
        data2 = {"a": 2}
        assert hash_dict(data1) != hash_dict(data2)

    def test_empty_dict(self):
        h = hash_dict({})
        assert isinstance(h, str)
        assert len(h) == 64
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_hasher.py -v`

Expected: FAIL — module not found.

- [ ] **Step 3: Implement hasher.py**

`packages/python/agentstack/src/agentstack/hash/hasher.py`:
```python
"""Leaf-level hashing for Pydantic models and dicts."""

import hashlib
import json

from pydantic import BaseModel


def hash_model(model: BaseModel) -> str:
    """SHA-256 of canonical JSON representation of a Pydantic model."""
    canonical = json.dumps(model.model_dump(mode="python"), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def hash_dict(data: dict) -> str:
    """SHA-256 of canonical JSON representation of a dict."""
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_hasher.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Write tests for tree.py**

`packages/python/agentstack/tests/test_tree.py`:
```python
from agentstack.hash.tree import AgentHashTree, hash_agent
from agentstack.schema.channel import Channel
from agentstack.schema.common import ChannelType, McpTransport, WorkspaceType
from agentstack.schema.mcp import McpServer
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider
from agentstack.schema.secret import Secret
from agentstack.schema.skill import Skill
from agentstack.schema.workspace import Workspace


def make_agent(**overrides):
    anthropic = Provider(name="anthropic", type="anthropic")
    model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
    from agentstack.schema.agent import Agent

    defaults = {"name": "bot", "model": model}
    defaults.update(overrides)
    return Agent(**defaults)


class TestAgentHashTree:
    def test_deterministic(self):
        agent = make_agent()
        tree1 = hash_agent(agent)
        tree2 = hash_agent(agent)
        assert tree1.root == tree2.root

    def test_all_fields_populated(self):
        agent = make_agent()
        tree = hash_agent(agent)
        assert tree.brain
        assert tree.skills
        assert tree.mcp_servers
        assert tree.channels
        assert tree.workspace
        assert tree.resources
        assert tree.secrets
        assert tree.root

    def test_model_change_changes_brain_and_root(self):
        agent1 = make_agent()
        anthropic = Provider(name="anthropic", type="anthropic")
        different_model = Model(name="opus", provider=anthropic, model_name="claude-opus-4-20250514")
        agent2 = make_agent(model=different_model)

        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)

        assert tree1.brain != tree2.brain
        assert tree1.root != tree2.root
        # Other sections unchanged
        assert tree1.skills == tree2.skills
        assert tree1.channels == tree2.channels

    def test_skill_change_changes_skills_and_root(self):
        agent1 = make_agent(skills=[Skill(name="a", tools=["tool1"])])
        agent2 = make_agent(skills=[Skill(name="b", tools=["tool2"])])

        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)

        assert tree1.skills != tree2.skills
        assert tree1.root != tree2.root
        assert tree1.brain == tree2.brain

    def test_channel_change_detected(self):
        agent1 = make_agent(channels=[Channel(name="api", type=ChannelType.API)])
        agent2 = make_agent(channels=[Channel(name="slack", type=ChannelType.SLACK)])

        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)

        assert tree1.channels != tree2.channels
        assert tree1.root != tree2.root

    def test_mcp_change_detected(self):
        agent1 = make_agent()
        agent2 = make_agent(
            mcp_servers=[McpServer(name="fs", transport=McpTransport.STDIO, command="fs-mcp")]
        )

        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)

        assert tree1.mcp_servers != tree2.mcp_servers
        assert tree1.root != tree2.root

    def test_workspace_change_detected(self):
        agent1 = make_agent()
        agent2 = make_agent(
            workspace=Workspace(name="sandbox", type=WorkspaceType.SANDBOX, filesystem=True)
        )

        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)

        assert tree1.workspace != tree2.workspace
        assert tree1.root != tree2.root

    def test_secret_change_detected(self):
        agent1 = make_agent(secrets=[Secret(name="KEY_A")])
        agent2 = make_agent(secrets=[Secret(name="KEY_B")])

        tree1 = hash_agent(agent1)
        tree2 = hash_agent(agent2)

        assert tree1.secrets != tree2.secrets
        assert tree1.root != tree2.root
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_tree.py -v`

Expected: FAIL — module not found.

- [ ] **Step 7: Implement tree.py**

`packages/python/agentstack/src/agentstack/hash/tree.py`:
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
    root: str


def _hash_list(items: list) -> str:
    """Hash a list of models by sorting their individual hashes and hashing the result."""
    if not items:
        return hashlib.sha256(b"[]").hexdigest()
    individual = sorted(hash_model(item) for item in items)
    combined = "|".join(individual)
    return hashlib.sha256(combined.encode()).hexdigest()


def _hash_optional(item) -> str:
    """Hash an optional model, using empty sentinel for None."""
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

    # Root = hash of all section hashes in fixed order
    sections = "|".join([brain, skills, mcp_servers, channels, workspace, resources, secrets])
    root = hashlib.sha256(sections.encode()).hexdigest()

    return AgentHashTree(
        brain=brain,
        skills=skills,
        mcp_servers=mcp_servers,
        channels=channels,
        workspace=workspace,
        resources=resources,
        secrets=secrets,
        root=root,
    )
```

- [ ] **Step 8: Update hash/__init__.py**

`packages/python/agentstack/src/agentstack/hash/__init__.py`:
```python
"""Content-addressable hash engine for stateless change detection."""

from agentstack.hash.hasher import hash_dict, hash_model
from agentstack.hash.tree import AgentHashTree, hash_agent

__all__ = ["AgentHashTree", "hash_agent", "hash_dict", "hash_model"]
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_hasher.py packages/python/agentstack/tests/test_tree.py -v`

Expected: all tests PASS.

- [ ] **Step 10: Commit**

```bash
git add packages/python/agentstack/
git commit -m "feat: add content-addressable hash engine"
```

---

### Task 8: Provider ABCs and Supporting Types

**Files:**
- Modify: `packages/python/agentstack/src/agentstack/providers/base.py` (create new content)
- Modify: `packages/python/agentstack/src/agentstack/providers/__init__.py`
- Create: `packages/python/agentstack/tests/test_base.py`

- [ ] **Step 1: Write tests for base.py**

`packages/python/agentstack/tests/test_base.py`:
```python
import pytest

from agentstack.providers.base import (
    AgentStatus,
    ChannelAdapter,
    DeployPlan,
    DeployResult,
    FrameworkAdapter,
    GeneratedCode,
    PlatformProvider,
    ValidationError,
)


class TestSupportingTypes:
    def test_generated_code(self):
        code = GeneratedCode(files={"main.py": "print('hello')"}, entrypoint="main.py")
        assert code.entrypoint == "main.py"
        assert "main.py" in code.files

    def test_deploy_plan(self):
        plan = DeployPlan(
            agent_name="bot",
            actions=["create container", "start container"],
            current_hash=None,
            target_hash="abc123",
            changes={"brain": (None, "abc123")},
        )
        assert plan.agent_name == "bot"
        assert len(plan.actions) == 2
        assert plan.current_hash is None

    def test_deploy_result(self):
        result = DeployResult(agent_name="bot", success=True, hash="abc123", message="deployed")
        assert result.success is True

    def test_agent_status(self):
        status = AgentStatus(agent_name="bot", running=True, hash="abc123")
        assert status.running is True
        assert status.info == {}

    def test_agent_status_with_info(self):
        status = AgentStatus(agent_name="bot", running=False, hash=None, info={"error": "crashed"})
        assert status.info["error"] == "crashed"

    def test_validation_error(self):
        err = ValidationError(field="model", message="model is required")
        assert err.field == "model"


class TestFrameworkAdapterABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            FrameworkAdapter()

    def test_subclass_must_implement(self):
        class BadAdapter(FrameworkAdapter):
            pass

        with pytest.raises(TypeError):
            BadAdapter()

    def test_valid_subclass(self):
        class GoodAdapter(FrameworkAdapter):
            def generate(self, agent):
                return GeneratedCode(files={}, entrypoint="main.py")

            def validate(self, agent):
                return []

        adapter = GoodAdapter()
        assert adapter is not None


class TestPlatformProviderABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            PlatformProvider()

    def test_valid_subclass(self):
        class GoodProvider(PlatformProvider):
            def plan(self, agent, current_hash):
                return DeployPlan(
                    agent_name=agent.name,
                    actions=[],
                    current_hash=current_hash,
                    target_hash="x",
                    changes={},
                )

            def apply(self, plan):
                return DeployResult(agent_name=plan.agent_name, success=True, hash="x", message="ok")

            def destroy(self, agent_name):
                pass

            def status(self, agent_name):
                return AgentStatus(agent_name=agent_name, running=False, hash=None)

            def get_hash(self, agent_name):
                return None

        provider = GoodProvider()
        assert provider is not None


class TestChannelAdapterABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            ChannelAdapter()

    def test_valid_subclass(self):
        class GoodChannel(ChannelAdapter):
            def setup(self, agent, channel):
                pass

            def teardown(self, channel):
                pass

        adapter = GoodChannel()
        assert adapter is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_base.py -v`

Expected: FAIL — imports fail.

- [ ] **Step 3: Implement base.py**

`packages/python/agentstack/src/agentstack/providers/base.py`:
```python
"""Abstract base classes for framework adapters, platform providers, and channel adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from agentstack.schema.agent import Agent
from agentstack.schema.channel import Channel


@dataclass
class GeneratedCode:
    """Code generated by a framework adapter."""

    files: dict[str, str]
    entrypoint: str


@dataclass
class DeployPlan:
    """Plan for deploying or updating an agent."""

    agent_name: str
    actions: list[str]
    current_hash: str | None
    target_hash: str
    changes: dict[str, tuple[str | None, str]]


@dataclass
class DeployResult:
    """Result of a deployment operation."""

    agent_name: str
    success: bool
    hash: str
    message: str


@dataclass
class AgentStatus:
    """Current status of a deployed agent."""

    agent_name: str
    running: bool
    hash: str | None
    info: dict = field(default_factory=dict)


@dataclass
class ValidationError:
    """A validation error found by a framework adapter."""

    field: str
    message: str


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

- [ ] **Step 4: Update providers/__init__.py**

`packages/python/agentstack/src/agentstack/providers/__init__.py`:
```python
"""Provider base classes for platform and resource provisioning."""

from agentstack.providers.base import (
    AgentStatus,
    ChannelAdapter,
    DeployPlan,
    DeployResult,
    FrameworkAdapter,
    GeneratedCode,
    PlatformProvider,
    ValidationError,
)

__all__ = [
    "AgentStatus",
    "ChannelAdapter",
    "DeployPlan",
    "DeployResult",
    "FrameworkAdapter",
    "GeneratedCode",
    "PlatformProvider",
    "ValidationError",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_base.py -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack/
git commit -m "feat: add provider ABCs and supporting types"
```

---

### Task 9: Top-Level API Re-exports and Integration Test

**Files:**
- Modify: `packages/python/agentstack/src/agentstack/__init__.py`
- Modify: `packages/python/agentstack/tests/test_version.py`
- Create: `packages/python/agentstack/tests/test_integration.py`

- [ ] **Step 1: Write integration test**

`packages/python/agentstack/tests/test_integration.py`:
```python
"""Integration test: define an agent using the top-level API, hash it, serialize it."""

import agentstack as ast


def test_namespace_api():
    """Test the ast.Agent(...) style API."""
    anthropic = ast.Provider(name="anthropic", type="anthropic")
    model = ast.Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514")
    agent = ast.Agent(name="bot", model=model)
    assert agent.name == "bot"


def test_direct_import_api():
    """Test the from agentstack import Agent style API."""
    from agentstack import Agent, Model, Provider

    anthropic = Provider(name="anthropic", type="anthropic")
    model = Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514")
    agent = Agent(name="bot", model=model)
    assert agent.name == "bot"


def test_full_agent_definition():
    """Define a full agent with all concepts and verify it works."""
    anthropic = ast.Provider(name="anthropic", type="anthropic")
    docker = ast.Provider(name="docker", type="docker")
    aws = ast.Provider(name="aws", type="aws")

    sonnet = ast.Model(
        name="sonnet",
        provider=anthropic,
        model_name="claude-sonnet-4-20250514",
        parameters={"temperature": 0.7},
    )

    agent = ast.Agent(
        name="support-bot",
        model=sonnet,
        skills=[
            ast.Skill(
                name="refund-handling",
                tools=["lookup_order", "process_refund"],
                prompt="Always verify the order before processing a refund.",
                guardrails={"max_amount": 500},
            ),
        ],
        channels=[
            ast.Channel(name="api", type=ast.ChannelType.API),
            ast.Channel(name="slack", type=ast.ChannelType.SLACK, config={"channel": "#support"}),
        ],
        mcp_servers=[
            ast.McpServer(name="github", transport=ast.McpTransport.STDIO, command="github-mcp"),
        ],
        workspace=ast.Workspace(
            name="sandbox",
            type=ast.WorkspaceType.SANDBOX,
            filesystem=True,
            terminal=True,
            timeout="30m",
        ),
        resources=[
            ast.SessionStore(name="sessions", provider=aws, engine="redis"),
        ],
        secrets=[
            ast.Secret(name="ANTHROPIC_API_KEY"),
        ],
        platform=ast.Platform(name="local", type="docker", provider=docker),
    )

    assert agent.name == "support-bot"
    assert len(agent.skills) == 1
    assert len(agent.channels) == 2
    assert len(agent.mcp_servers) == 1
    assert agent.workspace.filesystem is True
    assert len(agent.resources) == 1
    assert len(agent.secrets) == 1
    assert agent.platform.type == "docker"


def test_hash_agent():
    """Hash an agent and verify the tree structure."""
    anthropic = ast.Provider(name="anthropic", type="anthropic")
    model = ast.Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514")
    agent = ast.Agent(
        name="bot",
        model=model,
        skills=[ast.Skill(name="greeting", tools=["say_hello"])],
    )

    tree = ast.hash_agent(agent)
    assert tree.root
    assert tree.brain
    assert tree.skills
    assert len(tree.root) == 64  # SHA-256 hex digest


def test_yaml_roundtrip(tmp_path):
    """Serialize an agent to YAML and load it back."""
    anthropic = ast.Provider(name="anthropic", type="anthropic")
    model = ast.Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514")
    agent = ast.Agent(
        name="bot",
        model=model,
        skills=[ast.Skill(name="greeting", tools=["say_hello"])],
        channels=[ast.Channel(name="api", type=ast.ChannelType.API)],
    )

    path = tmp_path / "agent.yaml"
    ast.dump_agent(agent, path)
    restored = ast.load_agent(path)
    assert restored == agent


def test_hash_change_detection():
    """Verify that changing a section changes only that section's hash."""
    anthropic = ast.Provider(name="anthropic", type="anthropic")
    model = ast.Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514")

    agent1 = ast.Agent(name="bot", model=model, skills=[ast.Skill(name="a")])
    agent2 = ast.Agent(name="bot", model=model, skills=[ast.Skill(name="b")])

    tree1 = ast.hash_agent(agent1)
    tree2 = ast.hash_agent(agent2)

    assert tree1.skills != tree2.skills  # skills changed
    assert tree1.brain == tree2.brain    # model unchanged
    assert tree1.root != tree2.root      # root reflects the change
```

- [ ] **Step 2: Run integration test to verify it fails**

Run: `uv run pytest packages/python/agentstack/tests/test_integration.py -v`

Expected: FAIL — `import agentstack as ast` won't find the re-exported symbols.

- [ ] **Step 3: Update agentstack/__init__.py with all re-exports**

`packages/python/agentstack/src/agentstack/__init__.py`:
```python
"""AgentStack — declarative AI agent orchestration."""

__version__ = "0.1.0"

# Schema models
from agentstack.schema import (
    Agent,
    Cache,
    Channel,
    ChannelType,
    Database,
    Embedding,
    McpServer,
    McpTransport,
    Model,
    NamedModel,
    ObjectStore,
    Platform,
    Provider,
    Queue,
    Resource,
    Secret,
    SessionStore,
    Skill,
    SkillRequirements,
    VectorStore,
    Workspace,
    WorkspaceType,
)

# Hash engine
from agentstack.hash import AgentHashTree, hash_agent, hash_dict, hash_model

# Loader
from agentstack.schema.loader import dump_agent, load_agent

# Provider ABCs and supporting types
from agentstack.providers import (
    AgentStatus,
    ChannelAdapter,
    DeployPlan,
    DeployResult,
    FrameworkAdapter,
    GeneratedCode,
    PlatformProvider,
    ValidationError,
)

__all__ = [
    "__version__",
    # Schema
    "Agent",
    "Cache",
    "Channel",
    "ChannelType",
    "Database",
    "Embedding",
    "McpServer",
    "McpTransport",
    "Model",
    "NamedModel",
    "ObjectStore",
    "Platform",
    "Provider",
    "Queue",
    "Resource",
    "Secret",
    "SessionStore",
    "Skill",
    "SkillRequirements",
    "VectorStore",
    "Workspace",
    "WorkspaceType",
    # Hash
    "AgentHashTree",
    "hash_agent",
    "hash_dict",
    "hash_model",
    # Loader
    "dump_agent",
    "load_agent",
    # Provider ABCs
    "AgentStatus",
    "ChannelAdapter",
    "DeployPlan",
    "DeployResult",
    "FrameworkAdapter",
    "GeneratedCode",
    "PlatformProvider",
    "ValidationError",
]
```

- [ ] **Step 4: Run integration tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_integration.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest packages/python/agentstack/tests/ -v`

Expected: all tests PASS (test_version + test_common + test_secret + test_provider + test_model + test_resource + test_workspace + test_mcp + test_skill + test_channel + test_platform + test_agent + test_schema_exports + test_loader + test_hasher + test_tree + test_base + test_integration).

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack/
git commit -m "feat: add top-level API re-exports and integration tests"
```

---

### Task 10: Full Verification

- [ ] **Step 1: Run all Python tests across all packages**

Run: `just test-python`

Expected: all tests pass across all 5 Python packages.

- [ ] **Step 2: Run linting**

Run: `uv run ruff check packages/python/agentstack/`

Expected: no lint errors (or fix any that appear).

- [ ] **Step 3: Verify import works**

Run: `uv run python -c "import agentstack as ast; print(f'AgentStack v{ast.__version__}'); a = ast.Agent(name='test', model=ast.Model(name='m', provider=ast.Provider(name='p', type='t'), model_name='x')); print(f'Agent: {a.name}'); t = ast.hash_agent(a); print(f'Hash: {t.root[:16]}...')"`

Expected: prints version, agent name, and hash prefix.
