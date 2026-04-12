# Persisted Resources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add resource provisioning so SessionStore resources are automatically provisioned as Postgres containers or SQLite volumes, with sessions persisting across agent restarts.

**Architecture:** Docker provider gains network management and resource provisioning modules. LangChain adapter generates the appropriate LangGraph checkpointer based on resource type. Credentials stored in `.agentstack/secrets.json`.

**Tech Stack:** Python 3.11+, docker SDK, pytest, unittest.mock

---

### Task 1: Network Management

**Files:**
- Create: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/network.py`
- Create: `packages/python/agentstack-provider-docker/tests/test_network.py`

- [ ] **Step 1: Write tests**

`packages/python/agentstack-provider-docker/tests/test_network.py`:
```python
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def mock_docker_client():
    with patch("agentstack_provider_docker.network.docker") as mock_docker:
        client = MagicMock()
        mock_docker.from_env.return_value = client
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        mock_docker.errors.APIError = type("APIError", (Exception,), {})
        yield client, mock_docker.errors


class TestEnsureNetwork:
    def test_creates_network(self, mock_docker_client):
        from agentstack_provider_docker.network import ensure_network

        client, errors = mock_docker_client
        client.networks.list.return_value = []

        network = ensure_network(client)
        client.networks.create.assert_called_once_with(
            "agentstack-net", driver="bridge"
        )

    def test_reuses_existing(self, mock_docker_client):
        from agentstack_provider_docker.network import ensure_network

        client, errors = mock_docker_client
        existing = MagicMock()
        existing.name = "agentstack-net"
        client.networks.list.return_value = [existing]

        network = ensure_network(client)
        client.networks.create.assert_not_called()
        assert network == existing
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/akolodkin/Developer/work/AgentsStack && uv run pytest packages/python/agentstack-provider-docker/tests/test_network.py -v`

Expected: FAIL — module not found.

- [ ] **Step 3: Implement network.py**

`packages/python/agentstack-provider-docker/src/agentstack_provider_docker/network.py`:
```python
"""Docker network management for AgentStack."""

NETWORK_NAME = "agentstack-net"


def ensure_network(client, name: str = NETWORK_NAME):
    """Create the AgentStack Docker network if it doesn't exist."""
    existing = client.networks.list(names=[name])
    if existing:
        return existing[0]
    return client.networks.create(name, driver="bridge")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/test_network.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-provider-docker/
git commit -m "feat: add Docker network management"
```

---

### Task 2: Secrets Storage

**Files:**
- Create: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/secrets.py`
- Create: `packages/python/agentstack-provider-docker/tests/test_secrets.py`

- [ ] **Step 1: Write tests**

`packages/python/agentstack-provider-docker/tests/test_secrets.py`:
```python
import json
from pathlib import Path

from agentstack_provider_docker.secrets import (
    generate_password,
    get_resource_password,
    load_secrets,
    save_secrets,
)


class TestGeneratePassword:
    def test_returns_string(self):
        pw = generate_password()
        assert isinstance(pw, str)

    def test_length(self):
        pw = generate_password()
        assert len(pw) >= 24

    def test_unique(self):
        pw1 = generate_password()
        pw2 = generate_password()
        assert pw1 != pw2


class TestSecretsFile:
    def test_save_and_load(self, tmp_path):
        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        data = {"resources": {"sessions": {"password": "test123"}}}
        save_secrets(secrets_path, data)
        loaded = load_secrets(secrets_path)
        assert loaded == data

    def test_load_missing_returns_empty(self, tmp_path):
        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        loaded = load_secrets(secrets_path)
        assert loaded == {"resources": {}}


class TestGetResourcePassword:
    def test_creates_new(self, tmp_path):
        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        pw = get_resource_password("sessions", secrets_path)
        assert isinstance(pw, str)
        assert len(pw) >= 24

    def test_reuses_existing(self, tmp_path):
        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        pw1 = get_resource_password("sessions", secrets_path)
        pw2 = get_resource_password("sessions", secrets_path)
        assert pw1 == pw2

    def test_different_resources_different_passwords(self, tmp_path):
        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        pw1 = get_resource_password("sessions", secrets_path)
        pw2 = get_resource_password("other", secrets_path)
        assert pw1 != pw2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/test_secrets.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement secrets.py**

`packages/python/agentstack-provider-docker/src/agentstack_provider_docker/secrets.py`:
```python
"""Local secrets storage for provisioned resource credentials."""

import json
import secrets
from pathlib import Path


def generate_password(length: int = 32) -> str:
    """Generate a secure random password."""
    return secrets.token_urlsafe(length)


def load_secrets(secrets_path: Path) -> dict:
    """Load secrets from .agentstack/secrets.json."""
    if not secrets_path.exists():
        return {"resources": {}}
    return json.loads(secrets_path.read_text())


def save_secrets(secrets_path: Path, data: dict) -> None:
    """Save secrets to .agentstack/secrets.json."""
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text(json.dumps(data, indent=2))


def get_resource_password(resource_name: str, secrets_path: Path) -> str:
    """Get or create a password for a resource."""
    data = load_secrets(secrets_path)
    resources = data.setdefault("resources", {})
    resource = resources.setdefault(resource_name, {})

    if "password" not in resource:
        resource["password"] = generate_password()
        save_secrets(secrets_path, data)

    return resource["password"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/test_secrets.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-provider-docker/
git commit -m "feat: add local secrets storage for resource credentials"
```

---

### Task 3: Resource Provisioning

**Files:**
- Create: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/resources.py`
- Create: `packages/python/agentstack-provider-docker/tests/test_resources.py`

- [ ] **Step 1: Write tests**

`packages/python/agentstack-provider-docker/tests/test_resources.py`:
```python
from unittest.mock import MagicMock, patch, call

import pytest

from agentstack.schema.provider import Provider
from agentstack.schema.resource import SessionStore


@pytest.fixture()
def mock_docker_client():
    with patch("agentstack_provider_docker.resources.docker") as mock_docker:
        client = MagicMock()
        mock_docker.from_env.return_value = client
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        yield client, mock_docker.errors


class TestProvisionPostgres:
    def test_creates_container(self, mock_docker_client, tmp_path):
        from agentstack_provider_docker.resources import provision_resource

        client, errors = mock_docker_client
        client.containers.list.return_value = []
        network = MagicMock()

        resource = SessionStore(
            name="sessions",
            provider=Provider(name="docker", type="docker"),
            engine="postgres",
        )

        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        result = provision_resource(client, resource, network, secrets_path)

        client.containers.run.assert_called_once()
        call_kwargs = client.containers.run.call_args
        assert call_kwargs[0][0] == "postgres:16-alpine"
        assert "agentstack-resource-sessions" in str(call_kwargs)
        assert result["engine"] == "postgres"
        assert "connection_string" in result

    def test_reuses_existing(self, mock_docker_client, tmp_path):
        from agentstack_provider_docker.resources import provision_resource

        client, errors = mock_docker_client
        existing = MagicMock()
        existing.name = "agentstack-resource-sessions"
        existing.labels = {"agentstack.resource": "sessions", "agentstack.engine": "postgres"}
        client.containers.list.return_value = [existing]
        network = MagicMock()

        resource = SessionStore(
            name="sessions",
            provider=Provider(name="docker", type="docker"),
            engine="postgres",
        )

        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        result = provision_resource(client, resource, network, secrets_path)

        client.containers.run.assert_not_called()
        assert result["engine"] == "postgres"


class TestProvisionSqlite:
    def test_creates_volume(self, mock_docker_client, tmp_path):
        from agentstack_provider_docker.resources import provision_resource

        client, errors = mock_docker_client
        client.volumes.list.return_value = []
        network = MagicMock()

        resource = SessionStore(
            name="sessions",
            provider=Provider(name="docker", type="docker"),
            engine="sqlite",
        )

        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        result = provision_resource(client, resource, network, secrets_path)

        client.volumes.create.assert_called_once_with("agentstack-data-sessions")
        assert result["engine"] == "sqlite"
        assert result["volume_name"] == "agentstack-data-sessions"

    def test_reuses_existing_volume(self, mock_docker_client, tmp_path):
        from agentstack_provider_docker.resources import provision_resource

        client, errors = mock_docker_client
        existing_vol = MagicMock()
        existing_vol.name = "agentstack-data-sessions"
        client.volumes.list.return_value = [existing_vol]
        network = MagicMock()

        resource = SessionStore(
            name="sessions",
            provider=Provider(name="docker", type="docker"),
            engine="sqlite",
        )

        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        result = provision_resource(client, resource, network, secrets_path)

        client.volumes.create.assert_not_called()


class TestDestroyResource:
    def test_removes_container_keeps_volume(self, mock_docker_client):
        from agentstack_provider_docker.resources import destroy_resource

        client, errors = mock_docker_client
        container = MagicMock()
        client.containers.list.return_value = [container]

        destroy_resource(client, "sessions")
        container.stop.assert_called_once()
        container.remove.assert_called_once()

    def test_no_container_no_error(self, mock_docker_client):
        from agentstack_provider_docker.resources import destroy_resource

        client, errors = mock_docker_client
        client.containers.list.return_value = []

        destroy_resource(client, "sessions")  # should not raise


class TestGetConnectionInfo:
    def test_postgres(self, tmp_path):
        from agentstack_provider_docker.resources import get_connection_string
        from agentstack_provider_docker.secrets import save_secrets

        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        save_secrets(secrets_path, {
            "resources": {"sessions": {"password": "testpass"}}
        })

        conn = get_connection_string("sessions", "postgres", secrets_path)
        assert conn == "postgresql://agentstack:testpass@agentstack-resource-sessions:5432/agentstack"

    def test_sqlite(self, tmp_path):
        from agentstack_provider_docker.resources import get_connection_string

        secrets_path = tmp_path / ".agentstack" / "secrets.json"
        conn = get_connection_string("sessions", "sqlite", secrets_path)
        assert conn == "/data/sessions.db"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/test_resources.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement resources.py**

`packages/python/agentstack-provider-docker/src/agentstack_provider_docker/resources.py`:
```python
"""Resource provisioning for Docker — Postgres containers and SQLite volumes."""

from pathlib import Path

import docker
import docker.errors

from agentstack.schema.resource import Resource
from agentstack_provider_docker.secrets import get_resource_password


def _resource_container_name(resource_name: str) -> str:
    return f"agentstack-resource-{resource_name}"


def _volume_name(resource_name: str) -> str:
    return f"agentstack-data-{resource_name}"


def provision_resource(
    client, resource: Resource, network, secrets_path: Path
) -> dict:
    """Provision backing infrastructure for a resource. Returns connection info."""
    if resource.engine == "postgres":
        return _provision_postgres(client, resource, network, secrets_path)
    elif resource.engine == "sqlite":
        return _provision_sqlite(client, resource, secrets_path)
    else:
        raise ValueError(f"Unsupported session store engine: {resource.engine}")


def _provision_postgres(client, resource: Resource, network, secrets_path: Path) -> dict:
    """Provision a Postgres container."""
    container_name = _resource_container_name(resource.name)
    volume_name = _volume_name(resource.name)

    # Check if already running
    existing = client.containers.list(
        filters={"name": container_name}, all=True
    )
    if existing:
        password = get_resource_password(resource.name, secrets_path)
        return {
            "engine": "postgres",
            "container_name": container_name,
            "connection_string": _postgres_conn_string(resource.name, password),
        }

    # Create and start
    password = get_resource_password(resource.name, secrets_path)

    client.containers.run(
        "postgres:16-alpine",
        name=container_name,
        detach=True,
        environment={
            "POSTGRES_DB": "agentstack",
            "POSTGRES_USER": "agentstack",
            "POSTGRES_PASSWORD": password,
        },
        volumes={volume_name: {"bind": "/var/lib/postgresql/data", "mode": "rw"}},
        network=network.name,
        labels={
            "agentstack.resource": resource.name,
            "agentstack.engine": "postgres",
        },
    )

    return {
        "engine": "postgres",
        "container_name": container_name,
        "connection_string": _postgres_conn_string(resource.name, password),
    }


def _provision_sqlite(client, resource: Resource, secrets_path: Path) -> dict:
    """Ensure a Docker volume exists for SQLite storage."""
    volume_name = _volume_name(resource.name)

    existing = client.volumes.list(filters={"name": volume_name})
    if not existing:
        client.volumes.create(volume_name)

    return {
        "engine": "sqlite",
        "volume_name": volume_name,
        "connection_string": f"/data/{resource.name}.db",
    }


def destroy_resource(client, resource_name: str) -> None:
    """Stop and remove a resource container. Keeps volumes."""
    container_name = _resource_container_name(resource_name)
    containers = client.containers.list(
        filters={"name": container_name}, all=True
    )
    for container in containers:
        container.stop()
        container.remove()


def get_connection_string(
    resource_name: str, engine: str, secrets_path: Path
) -> str:
    """Get the connection string for a provisioned resource."""
    if engine == "postgres":
        password = get_resource_password(resource_name, secrets_path)
        return _postgres_conn_string(resource_name, password)
    elif engine == "sqlite":
        return f"/data/{resource_name}.db"
    else:
        raise ValueError(f"Unsupported engine: {engine}")


def _postgres_conn_string(resource_name: str, password: str) -> str:
    host = _resource_container_name(resource_name)
    return f"postgresql://agentstack:{password}@{host}:5432/agentstack"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/test_resources.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-provider-docker/
git commit -m "feat: add resource provisioning for Postgres and SQLite"
```

---

### Task 4: Update Docker Provider to Use Resources and Network

**Files:**
- Modify: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py`
- Modify: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/__init__.py`

- [ ] **Step 1: Rewrite provider.py**

Replace `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py` with:

```python
"""Docker platform provider — builds and runs agents as Docker containers."""

import os
from pathlib import Path

import docker
import docker.errors

from agentstack.hash import hash_agent
from agentstack.providers.base import (
    AgentStatus,
    DeployPlan,
    DeployResult,
    GeneratedCode,
    PlatformProvider,
)
from agentstack.schema.agent import Agent
from agentstack.schema.resource import SessionStore
from agentstack_provider_docker.network import ensure_network
from agentstack_provider_docker.resources import (
    destroy_resource,
    provision_resource,
)


DOCKERFILE_TEMPLATE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "{entrypoint}"]
"""

SECRETS_PATH = Path(".agentstack") / "secrets.json"


class DockerProvider(PlatformProvider):
    """Deploys and manages agents as Docker containers."""

    def __init__(self):
        self._client = self._create_client()
        self._generated_code: GeneratedCode | None = None
        self._agent: Agent | None = None
        self._resource_info: list[dict] = []

    @staticmethod
    def _create_client():
        try:
            return docker.from_env()
        except docker.errors.DockerException:
            desktop_socket = Path.home() / ".docker" / "run" / "docker.sock"
            if desktop_socket.exists():
                return docker.DockerClient(base_url=f"unix://{desktop_socket}")
            raise

    def set_generated_code(self, code: GeneratedCode) -> None:
        self._generated_code = code

    def set_agent(self, agent: Agent) -> None:
        self._agent = agent

    def _container_name(self, agent_name: str) -> str:
        return f"agentstack-{agent_name}"

    def _get_container(self, agent_name: str):
        try:
            return self._client.containers.get(self._container_name(agent_name))
        except docker.errors.NotFound:
            return None

    def _build_env(self) -> dict[str, str]:
        env = {}
        if self._agent:
            for secret in self._agent.secrets:
                value = os.environ.get(secret.name)
                if value:
                    env[secret.name] = value
            # Add resource connection strings
            for info in self._resource_info:
                if info["engine"] in ("postgres", "sqlite"):
                    env["SESSION_STORE_URL"] = info["connection_string"]
        return env

    def _build_volumes(self) -> dict:
        volumes = {}
        for info in self._resource_info:
            if info["engine"] == "sqlite":
                volumes[info["volume_name"]] = {"bind": "/data", "mode": "rw"}
        return volumes

    def get_hash(self, agent_name: str) -> str | None:
        container = self._get_container(agent_name)
        if container is None:
            return None
        return container.labels.get("agentstack.hash")

    def plan(self, agent: Agent, current_hash: str | None) -> DeployPlan:
        tree = hash_agent(agent)
        target_hash = tree.root
        container = self._get_container(agent.name)

        if container is None:
            return DeployPlan(
                agent_name=agent.name,
                actions=["Create new deployment"],
                current_hash=None,
                target_hash=target_hash,
                changes={"all": (None, target_hash)},
            )

        deployed_hash = container.labels.get("agentstack.hash")
        if deployed_hash == target_hash:
            return DeployPlan(
                agent_name=agent.name,
                actions=[],
                current_hash=deployed_hash,
                target_hash=target_hash,
                changes={},
            )

        return DeployPlan(
            agent_name=agent.name,
            actions=["Update deployment"],
            current_hash=deployed_hash,
            target_hash=target_hash,
            changes={"root": (deployed_hash, target_hash)},
        )

    def apply(self, plan: DeployPlan) -> DeployResult:
        if not self._generated_code:
            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message="No generated code set. Call set_generated_code() first.",
            )

        try:
            # 1. Ensure network
            network = ensure_network(self._client)

            # 2. Provision resources
            self._resource_info = []
            if self._agent:
                for resource in self._agent.resources:
                    if isinstance(resource, SessionStore):
                        info = provision_resource(
                            self._client, resource, network, SECRETS_PATH
                        )
                        self._resource_info.append(info)

            # 3. Stop existing agent container
            existing = self._get_container(plan.agent_name)
            if existing is not None:
                existing.stop()
                existing.remove()

            # 4. Build image
            build_dir = Path(".agentstack") / plan.agent_name
            build_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in self._generated_code.files.items():
                (build_dir / filename).write_text(content)
            dockerfile_content = DOCKERFILE_TEMPLATE.format(
                entrypoint=self._generated_code.entrypoint
            )
            (build_dir / "Dockerfile").write_text(dockerfile_content)
            image_tag = f"{self._container_name(plan.agent_name)}:latest"
            self._client.images.build(path=str(build_dir), tag=image_tag)

            # 5. Run agent container on network
            container_name = self._container_name(plan.agent_name)
            self._client.containers.run(
                image_tag,
                name=container_name,
                detach=True,
                ports={"8000/tcp": None},
                environment=self._build_env(),
                volumes=self._build_volumes(),
                network=network.name,
                labels={
                    "agentstack.hash": plan.target_hash,
                    "agentstack.agent": plan.agent_name,
                },
            )

            return DeployResult(
                agent_name=plan.agent_name,
                success=True,
                hash=plan.target_hash,
                message=f"Deployed {plan.agent_name} as {container_name}",
            )
        except Exception as e:
            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message=f"Deployment failed: {e}",
            )

    def destroy(self, agent_name: str, include_resources: bool = False) -> None:
        container = self._get_container(agent_name)
        if container is not None:
            container.stop()
            container.remove()

        if include_resources and self._agent:
            for resource in self._agent.resources:
                destroy_resource(self._client, resource.name)

    def status(self, agent_name: str) -> AgentStatus:
        container = self._get_container(agent_name)
        if container is None:
            return AgentStatus(agent_name=agent_name, running=False, hash=None)
        return AgentStatus(
            agent_name=agent_name,
            running=container.status == "running",
            hash=container.labels.get("agentstack.hash"),
            info={
                "container": self._container_name(agent_name),
                "status": container.status,
                "ports": container.ports,
            },
        )
```

- [ ] **Step 2: Update __init__.py**

Replace `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/__init__.py` with:

```python
"""AgentStack Docker platform provider."""

__version__ = "0.1.0"

from agentstack_provider_docker.provider import DockerProvider

__all__ = ["DockerProvider", "__version__"]
```

- [ ] **Step 3: Run existing provider tests**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/ -v`

Expected: existing tests may need updates due to `ensure_network` calls. Fix any failures by adding network mocking to the existing test fixtures.

If tests fail, update `packages/python/agentstack-provider-docker/tests/test_provider.py` to mock the new imports:

Add to the `mock_docker_client` fixture:
```python
@pytest.fixture()
def mock_docker_client():
    with patch("agentstack_provider_docker.provider.docker") as mock_docker, \
         patch("agentstack_provider_docker.provider.ensure_network") as mock_network, \
         patch("agentstack_provider_docker.provider.provision_resource") as mock_provision:
        client = MagicMock()
        mock_docker.from_env.return_value = client
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        mock_docker.errors.DockerException = type("DockerException", (Exception,), {})
        mock_network.return_value = MagicMock(name="agentstack-net")
        yield client, mock_docker.errors
```

- [ ] **Step 4: Commit**

```bash
git add packages/python/agentstack-provider-docker/
git commit -m "feat: integrate resource provisioning and networking into DockerProvider"
```

---

### Task 5: Update LangChain Adapter for Resource-Aware Code Generation

**Files:**
- Modify: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py`
- Modify: `packages/python/agentstack-adapter-langchain/tests/test_templates.py`

- [ ] **Step 1: Add new tests to test_templates.py**

Append to `packages/python/agentstack-adapter-langchain/tests/test_templates.py`:

```python
from agentstack.schema.resource import SessionStore


@pytest.fixture()
def postgres_agent(anthropic_provider):
    docker_provider = Provider(name="docker", type="docker")
    return Agent(
        name="pg-bot",
        model=Model(
            name="claude",
            provider=anthropic_provider,
            model_name="claude-sonnet-4-20250514",
        ),
        resources=[
            SessionStore(name="sessions", provider=docker_provider, engine="postgres"),
        ],
    )


@pytest.fixture()
def sqlite_agent(anthropic_provider):
    docker_provider = Provider(name="docker", type="docker")
    return Agent(
        name="sqlite-bot",
        model=Model(
            name="claude",
            provider=anthropic_provider,
            model_name="claude-sonnet-4-20250514",
        ),
        resources=[
            SessionStore(name="sessions", provider=docker_provider, engine="sqlite"),
        ],
    )


class TestCheckpointerSelection:
    def test_no_resource_uses_memory(self, openai_agent):
        code = generate_agent_py(openai_agent)
        assert "MemorySaver" in code
        assert "PostgresSaver" not in code
        assert "SqliteSaver" not in code

    def test_postgres_checkpointer(self, postgres_agent):
        code = generate_agent_py(postgres_agent)
        assert "PostgresSaver" in code
        assert "SESSION_STORE_URL" in code
        assert "MemorySaver" not in code
        python_ast.parse(code)

    def test_sqlite_checkpointer(self, sqlite_agent):
        code = generate_agent_py(sqlite_agent)
        assert "SqliteSaver" in code
        assert "/data/" in code
        assert "MemorySaver" not in code
        python_ast.parse(code)

    def test_postgres_requirements(self, postgres_agent):
        reqs = generate_requirements_txt(postgres_agent)
        assert "langgraph-checkpoint-postgres" in reqs

    def test_sqlite_requirements(self, sqlite_agent):
        reqs = generate_requirements_txt(sqlite_agent)
        assert "langgraph-checkpoint-sqlite" in reqs

    def test_no_resource_no_extra_requirements(self, openai_agent):
        reqs = generate_requirements_txt(openai_agent)
        assert "langgraph-checkpoint-postgres" not in reqs
        assert "langgraph-checkpoint-sqlite" not in reqs
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/test_templates.py -v`

Expected: new `TestCheckpointerSelection` tests FAIL.

- [ ] **Step 3: Update templates.py — checkpointer selection in generate_agent_py**

In `generate_agent_py`, replace the checkpointer section (lines around `MemorySaver`) with logic that inspects resources:

```python
def _get_session_store(agent: Agent):
    """Find a SessionStore resource in the agent, if any."""
    from agentstack.schema.resource import SessionStore
    for resource in agent.resources:
        if isinstance(resource, SessionStore):
            return resource
    return None
```

Add this helper function before `generate_agent_py`.

Then update `generate_agent_py` to use it. Replace the block that generates the checkpointer import and setup:

```python
    # Checkpointer based on resources
    session_store = _get_session_store(agent)

    if session_store and session_store.engine == "postgres":
        lines.append("import os")
        lines.append("")
        lines.append("from langgraph.checkpoint.postgres import PostgresSaver")
    elif session_store and session_store.engine == "sqlite":
        lines.append("from langgraph.checkpoint.sqlite import SqliteSaver")
    else:
        lines.append("from langgraph.checkpoint.memory import MemorySaver")

    lines.append("from langgraph.prebuilt import create_react_agent")
    lines.append("")
    lines.append("")
    lines.append(f"# Model")
    lines.append(f"model = {model_class}({model_kwargs_str})")
    lines.append("")

    # Checkpointer setup
    if session_store and session_store.engine == "postgres":
        lines.append("# Session persistence (Postgres)")
        lines.append('memory = PostgresSaver.from_conn_string(os.environ["SESSION_STORE_URL"])')
    elif session_store and session_store.engine == "sqlite":
        lines.append("# Session persistence (SQLite)")
        lines.append(f'memory = SqliteSaver.from_conn_string("/data/{session_store.name}.db")')
    else:
        lines.append("# Session memory (in-memory, not persisted)")
        lines.append("memory = MemorySaver()")

    lines.append("")
```

- [ ] **Step 4: Update generate_requirements_txt**

Add checkpoint package based on resources:

```python
def generate_requirements_txt(agent: Agent) -> str:
    """Generate a requirements.txt based on the agent's model provider."""
    provider_type = agent.model.provider.type
    provider_pkg = PROVIDER_PACKAGES.get(provider_type, PROVIDER_PACKAGES["anthropic"])

    session_store = _get_session_store(agent)
    checkpoint_pkg = ""
    if session_store and session_store.engine == "postgres":
        checkpoint_pkg = "\nlanggraph-checkpoint-postgres>=2.0\npsycopg[binary]>=3.0"
    elif session_store and session_store.engine == "sqlite":
        checkpoint_pkg = "\nlanggraph-checkpoint-sqlite>=2.0"

    return dedent(f"""\
        langchain-core>=0.3
        langgraph>=0.2
        {provider_pkg}
        fastapi>=0.115
        uvicorn>=0.34
        sse-starlette>=2.0{checkpoint_pkg}
    """)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/test_templates.py -v`

Expected: all tests PASS (old + new).

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/
git commit -m "feat: generate resource-aware checkpointer code (Postgres/SQLite/Memory)"
```

---

### Task 6: Update CLI Destroy Command

**Files:**
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/destroy.py`

- [ ] **Step 1: Update destroy.py with --include-resources flag**

Replace `packages/python/agentstack-cli/src/agentstack_cli/commands/destroy.py` with:

```python
"""agentstack destroy — stop and remove an agent."""

import click

from agentstack_cli.loader import find_agent_file, load_agent_from_file
from agentstack_provider_docker import DockerProvider


@click.command()
@click.option("--file", "file_path", default=None, help="Path to agent definition file")
@click.option("--name", "agent_name", default=None, help="Agent name (alternative to --file)")
@click.option(
    "--include-resources",
    is_flag=True,
    default=False,
    help="Also remove resource containers (keeps volumes)",
)
def destroy(file_path, agent_name, include_resources):
    """Stop and remove a deployed agent."""
    agent = None
    if agent_name is None:
        path = find_agent_file(file=file_path)
        agent = load_agent_from_file(path)
        agent_name = agent.name

    click.echo(f"Destroying: {agent_name}")
    provider = DockerProvider()

    if include_resources and agent:
        provider.set_agent(agent)

    click.echo(f"Stopping container agentstack-{agent_name}... ", nl=False)
    try:
        provider.destroy(agent_name, include_resources=include_resources)
        click.echo("OK")
        if include_resources:
            click.echo("Resource containers removed (volumes preserved)")
        click.echo(f"Destroyed: {agent_name}")
    except Exception as e:
        click.echo("FAILED")
        click.echo(f"  Error: {e}", err=True)
        raise SystemExit(1)
```

- [ ] **Step 2: Run CLI tests**

Run: `uv run pytest packages/python/agentstack-cli/tests/ -v`

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add packages/python/agentstack-cli/
git commit -m "feat: add --include-resources flag to destroy command"
```

---

### Task 7: Update Example and Full Verification

**Files:**
- Modify: `examples/hello-agent/agentstack.yaml`

- [ ] **Step 1: Update example with SessionStore resource**

Replace `examples/hello-agent/agentstack.yaml` with:

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
skills:
  - name: assistant
    tools:
      - get_weather
      - get_time
channels:
  - name: api
    type: api
resources:
  - name: sessions
    provider:
      name: docker
      type: docker
    engine: postgres
secrets:
  - name: ANTHROPIC_API_KEY
```

- [ ] **Step 2: Run all Python tests**

Run: `just test-python`

Expected: all tests pass.

- [ ] **Step 3: Run linting**

Run: `uv run ruff check packages/python/agentstack-provider-docker/ packages/python/agentstack-adapter-langchain/ packages/python/agentstack-cli/`

Fix any lint errors.

- [ ] **Step 4: Verify preview shows Postgres checkpointer**

Run: `uv run python examples/hello-agent/preview.py`

Expected: generated `agent.py` uses `PostgresSaver` and `os.environ["SESSION_STORE_URL"]`.

- [ ] **Step 5: Commit**

```bash
git add examples/hello-agent/agentstack.yaml
git commit -m "feat: update hello-agent example with Postgres session store"
```
