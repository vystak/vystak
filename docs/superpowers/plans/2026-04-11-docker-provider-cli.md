# Docker Provider + CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Docker platform provider and CLI to complete the end-to-end pipeline: define agent → `agentstack plan` → `agentstack apply` → Docker container running.

**Architecture:** DockerProvider implements `PlatformProvider` ABC using the Docker Python SDK. CLI uses Click with subcommands. Agent definitions are discovered by convention (`agentstack.yaml`) or explicit `--file` flag.

**Tech Stack:** Python 3.11+, docker SDK, Click, pytest, unittest.mock

---

### Task 1: Docker Provider

**Files:**
- Modify: `packages/python/agentstack-provider-docker/pyproject.toml`
- Modify: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/__init__.py`
- Modify: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py`
- Create: `packages/python/agentstack-provider-docker/tests/test_provider.py`

- [ ] **Step 1: Update pyproject.toml with docker dependency**

Replace `packages/python/agentstack-provider-docker/pyproject.toml` with:

```toml
[project]
name = "agentstack-provider-docker"
version = "0.1.0"
description = "AgentStack Docker platform provider"
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
    "agentstack>=0.1.0",
    "docker>=7.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentstack_provider_docker"]

[tool.uv.sources]
agentstack = { workspace = true }
```

Run: `cd /Users/akolodkin/Developer/work/AgentsStack && uv sync`

- [ ] **Step 2: Write tests**

`packages/python/agentstack-provider-docker/tests/test_provider.py`:
```python
from unittest.mock import MagicMock, patch

import pytest

from agentstack.providers.base import DeployPlan, GeneratedCode
from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider

from agentstack_provider_docker.provider import DockerProvider


@pytest.fixture()
def mock_docker_client():
    with patch("agentstack_provider_docker.provider.docker") as mock_docker:
        client = MagicMock()
        mock_docker.from_env.return_value = client
        yield client


@pytest.fixture()
def provider(mock_docker_client):
    return DockerProvider()


@pytest.fixture()
def sample_agent():
    return Agent(
        name="test-bot",
        model=Model(
            name="claude",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-20250514",
        ),
    )


@pytest.fixture()
def sample_code():
    return GeneratedCode(
        files={
            "agent.py": "# agent code",
            "server.py": "# server code",
            "requirements.txt": "fastapi\nuvicorn\n",
        },
        entrypoint="server.py",
    )


class TestContainerNaming:
    def test_container_name(self, provider):
        assert provider._container_name("my-bot") == "agentstack-my-bot"


class TestGetHash:
    def test_returns_hash_from_label(self, provider, mock_docker_client):
        container = MagicMock()
        container.labels = {"agentstack.hash": "abc123", "agentstack.agent": "test-bot"}
        mock_docker_client.containers.get.return_value = container

        result = provider.get_hash("test-bot")
        assert result == "abc123"
        mock_docker_client.containers.get.assert_called_with("agentstack-test-bot")

    def test_returns_none_when_no_container(self, provider, mock_docker_client):
        import docker.errors

        mock_docker_client.containers.get.side_effect = docker.errors.NotFound("not found")

        result = provider.get_hash("test-bot")
        assert result is None


class TestPlan:
    def test_new_deployment(self, provider, sample_agent, mock_docker_client):
        import docker.errors

        mock_docker_client.containers.get.side_effect = docker.errors.NotFound("not found")

        plan = provider.plan(sample_agent, None)
        assert plan.agent_name == "test-bot"
        assert len(plan.actions) > 0
        assert any("create" in a.lower() or "new" in a.lower() for a in plan.actions)
        assert plan.current_hash is None

    def test_no_change(self, provider, sample_agent, mock_docker_client):
        from agentstack.hash import hash_agent

        tree = hash_agent(sample_agent)
        container = MagicMock()
        container.labels = {"agentstack.hash": tree.root}
        mock_docker_client.containers.get.return_value = container

        plan = provider.plan(sample_agent, tree.root)
        assert plan.actions == []

    def test_update(self, provider, sample_agent, mock_docker_client):
        container = MagicMock()
        container.labels = {"agentstack.hash": "old-hash"}
        mock_docker_client.containers.get.return_value = container

        plan = provider.plan(sample_agent, "old-hash")
        assert len(plan.actions) > 0
        assert any("update" in a.lower() for a in plan.actions)


class TestApply:
    def test_builds_and_runs(self, provider, mock_docker_client, sample_code):
        import docker.errors

        mock_docker_client.containers.get.side_effect = docker.errors.NotFound("not found")
        mock_docker_client.images.build.return_value = (MagicMock(), [])

        provider.set_generated_code(sample_code)
        plan = DeployPlan(
            agent_name="test-bot",
            actions=["Create new deployment"],
            current_hash=None,
            target_hash="abc123",
            changes={},
        )

        result = provider.apply(plan)
        assert result.success is True
        assert result.agent_name == "test-bot"
        mock_docker_client.images.build.assert_called_once()
        mock_docker_client.containers.run.assert_called_once()

    def test_replaces_existing(self, provider, mock_docker_client, sample_code):
        existing = MagicMock()
        mock_docker_client.containers.get.return_value = existing
        mock_docker_client.images.build.return_value = (MagicMock(), [])

        provider.set_generated_code(sample_code)
        plan = DeployPlan(
            agent_name="test-bot",
            actions=["Update deployment"],
            current_hash="old",
            target_hash="new",
            changes={},
        )

        result = provider.apply(plan)
        assert result.success is True
        existing.stop.assert_called_once()
        existing.remove.assert_called_once()


class TestDestroy:
    def test_removes_container(self, provider, mock_docker_client):
        container = MagicMock()
        mock_docker_client.containers.get.return_value = container

        provider.destroy("test-bot")
        container.stop.assert_called_once()
        container.remove.assert_called_once()

    def test_not_found(self, provider, mock_docker_client):
        import docker.errors

        mock_docker_client.containers.get.side_effect = docker.errors.NotFound("not found")
        # Should not raise
        provider.destroy("test-bot")


class TestStatus:
    def test_running(self, provider, mock_docker_client):
        container = MagicMock()
        container.status = "running"
        container.labels = {"agentstack.hash": "abc123", "agentstack.agent": "test-bot"}
        container.ports = {"8000/tcp": [{"HostPort": "32768"}]}
        mock_docker_client.containers.get.return_value = container

        status = provider.status("test-bot")
        assert status.agent_name == "test-bot"
        assert status.running is True
        assert status.hash == "abc123"

    def test_not_found(self, provider, mock_docker_client):
        import docker.errors

        mock_docker_client.containers.get.side_effect = docker.errors.NotFound("not found")

        status = provider.status("test-bot")
        assert status.running is False
        assert status.hash is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/test_provider.py -v`

Expected: FAIL — imports fail.

- [ ] **Step 4: Implement provider.py**

Replace `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py` with:

```python
"""Docker platform provider — builds and runs agents as Docker containers."""

import tempfile
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


DOCKERFILE_TEMPLATE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "{entrypoint}"]
"""


class DockerProvider(PlatformProvider):
    """Deploys and manages agents as Docker containers."""

    def __init__(self):
        self._client = docker.from_env()
        self._generated_code: GeneratedCode | None = None

    def set_generated_code(self, code: GeneratedCode) -> None:
        """Set the generated code to use during apply."""
        self._generated_code = code

    def _container_name(self, agent_name: str) -> str:
        return f"agentstack-{agent_name}"

    def _get_container(self, agent_name: str):
        """Get a container by agent name, or None if not found."""
        try:
            return self._client.containers.get(self._container_name(agent_name))
        except docker.errors.NotFound:
            return None

    def get_hash(self, agent_name: str) -> str | None:
        """Read the hash label from a running container."""
        container = self._get_container(agent_name)
        if container is None:
            return None
        return container.labels.get("agentstack.hash")

    def plan(self, agent: Agent, current_hash: str | None) -> DeployPlan:
        """Compute what would change if we deployed this agent."""
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
        """Build Docker image and start/replace container."""
        if not self._generated_code:
            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message="No generated code set. Call set_generated_code() first.",
            )

        try:
            # Stop existing container if present
            existing = self._get_container(plan.agent_name)
            if existing is not None:
                existing.stop()
                existing.remove()

            # Write files to temp directory and build
            with tempfile.TemporaryDirectory() as tmpdir:
                tmppath = Path(tmpdir)

                for filename, content in self._generated_code.files.items():
                    (tmppath / filename).write_text(content)

                dockerfile_content = DOCKERFILE_TEMPLATE.format(
                    entrypoint=self._generated_code.entrypoint
                )
                (tmppath / "Dockerfile").write_text(dockerfile_content)

                image_tag = f"{self._container_name(plan.agent_name)}:latest"
                self._client.images.build(path=str(tmppath), tag=image_tag)

            # Run container
            container_name = self._container_name(plan.agent_name)
            self._client.containers.run(
                image_tag,
                name=container_name,
                detach=True,
                ports={"8000/tcp": None},
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

    def destroy(self, agent_name: str) -> None:
        """Stop and remove the agent's container."""
        container = self._get_container(agent_name)
        if container is None:
            return
        container.stop()
        container.remove()

    def status(self, agent_name: str) -> AgentStatus:
        """Query the running state of an agent."""
        container = self._get_container(agent_name)
        if container is None:
            return AgentStatus(
                agent_name=agent_name,
                running=False,
                hash=None,
            )
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

- [ ] **Step 5: Update __init__.py**

Replace `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/__init__.py` with:

```python
"""AgentStack Docker platform provider."""

__version__ = "0.1.0"

from agentstack_provider_docker.provider import DockerProvider

__all__ = ["DockerProvider", "__version__"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/ -v`

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/python/agentstack-provider-docker/
git commit -m "feat: implement DockerProvider with plan, apply, destroy, status"
```

---

### Task 2: CLI Loader

**Files:**
- Modify: `packages/python/agentstack-cli/pyproject.toml`
- Create: `packages/python/agentstack-cli/src/agentstack_cli/loader.py`
- Create: `packages/python/agentstack-cli/tests/test_loader.py`

- [ ] **Step 1: Update CLI pyproject.toml**

Replace `packages/python/agentstack-cli/pyproject.toml` with:

```toml
[project]
name = "agentstack-cli"
version = "0.1.0"
description = "AgentStack CLI — manage and deploy AI agents"
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
    "agentstack>=0.1.0",
    "agentstack-adapter-langchain>=0.1.0",
    "agentstack-provider-docker>=0.1.0",
    "click>=8.0",
]

[project.scripts]
agentstack = "agentstack_cli.cli:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentstack_cli"]

[tool.uv.sources]
agentstack = { workspace = true }
agentstack-adapter-langchain = { workspace = true }
agentstack-provider-docker = { workspace = true }
```

Run: `cd /Users/akolodkin/Developer/work/AgentsStack && uv sync`

- [ ] **Step 2: Write tests for loader**

`packages/python/agentstack-cli/tests/test_loader.py`:
```python
import pytest
import yaml

from agentstack_cli.loader import find_agent_file, load_agent_from_file


@pytest.fixture()
def sample_agent_yaml():
    return {
        "name": "test-bot",
        "model": {
            "name": "claude",
            "provider": {"name": "anthropic", "type": "anthropic"},
            "model_name": "claude-sonnet-4-20250514",
        },
    }


class TestFindAgentFile:
    def test_find_yaml(self, tmp_path, sample_agent_yaml):
        path = tmp_path / "agentstack.yaml"
        path.write_text(yaml.dump(sample_agent_yaml))
        result = find_agent_file(search_dir=tmp_path)
        assert result == path

    def test_find_yml(self, tmp_path, sample_agent_yaml):
        path = tmp_path / "agentstack.yml"
        path.write_text(yaml.dump(sample_agent_yaml))
        result = find_agent_file(search_dir=tmp_path)
        assert result == path

    def test_find_py(self, tmp_path):
        path = tmp_path / "agentstack.py"
        path.write_text("agent = 'placeholder'")
        result = find_agent_file(search_dir=tmp_path)
        assert result == path

    def test_yaml_preferred_over_py(self, tmp_path, sample_agent_yaml):
        (tmp_path / "agentstack.yaml").write_text(yaml.dump(sample_agent_yaml))
        (tmp_path / "agentstack.py").write_text("agent = 'placeholder'")
        result = find_agent_file(search_dir=tmp_path)
        assert result.name == "agentstack.yaml"

    def test_file_override(self, tmp_path, sample_agent_yaml):
        custom = tmp_path / "custom.yaml"
        custom.write_text(yaml.dump(sample_agent_yaml))
        result = find_agent_file(file=str(custom))
        assert result == custom

    def test_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            find_agent_file(search_dir=tmp_path)

    def test_override_not_found(self):
        with pytest.raises(FileNotFoundError):
            find_agent_file(file="/nonexistent/file.yaml")


class TestLoadAgentFromFile:
    def test_load_yaml(self, tmp_path, sample_agent_yaml):
        path = tmp_path / "agent.yaml"
        path.write_text(yaml.dump(sample_agent_yaml))
        agent = load_agent_from_file(path)
        assert agent.name == "test-bot"
        assert agent.model.model_name == "claude-sonnet-4-20250514"

    def test_load_py(self, tmp_path):
        path = tmp_path / "agentstack.py"
        path.write_text("""\
from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider

anthropic = Provider(name="anthropic", type="anthropic")
model = Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514")
agent = Agent(name="py-bot", model=model)
""")
        agent = load_agent_from_file(path)
        assert agent.name == "py-bot"

    def test_load_py_missing_agent_var(self, tmp_path):
        path = tmp_path / "bad.py"
        path.write_text("x = 1")
        with pytest.raises(ValueError, match="agent"):
            load_agent_from_file(path)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack-cli/tests/test_loader.py -v`

Expected: FAIL — module not found.

- [ ] **Step 4: Implement loader.py**

`packages/python/agentstack-cli/src/agentstack_cli/loader.py`:
```python
"""Agent definition discovery and loading."""

import importlib.util
import sys
from pathlib import Path

from agentstack.schema.agent import Agent
from agentstack.schema.loader import load_agent

CONVENTION_FILES = ["agentstack.yaml", "agentstack.yml", "agentstack.py"]


def find_agent_file(file: str | None = None, search_dir: Path | None = None) -> Path:
    """Find the agent definition file.

    If file is specified, use it directly.
    Otherwise search for convention files in search_dir (default: cwd).
    """
    if file is not None:
        path = Path(file)
        if not path.exists():
            raise FileNotFoundError(f"Agent definition not found: {path}")
        return path

    search_dir = search_dir or Path.cwd()
    for name in CONVENTION_FILES:
        path = search_dir / name
        if path.exists():
            return path

    raise FileNotFoundError(
        f"No agent definition found. Create agentstack.yaml or specify --file. "
        f"Searched: {search_dir}"
    )


def load_agent_from_file(path: Path) -> Agent:
    """Load an Agent from a YAML/JSON or Python file."""
    path = Path(path)

    if path.suffix in (".yaml", ".yml", ".json"):
        return load_agent(path)

    if path.suffix == ".py":
        spec = importlib.util.spec_from_file_location("_agentstack_def", str(path))
        module = importlib.util.module_from_spec(spec)
        sys.modules["_agentstack_def"] = module
        spec.loader.exec_module(module)
        del sys.modules["_agentstack_def"]

        if not hasattr(module, "agent"):
            raise ValueError(
                f"Python file {path} must define an 'agent' variable of type Agent"
            )

        agent = module.agent
        if not isinstance(agent, Agent):
            raise ValueError(
                f"'agent' variable in {path} must be an Agent instance, got {type(agent)}"
            )
        return agent

    raise ValueError(f"Unsupported file type: {path.suffix}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-cli/tests/test_loader.py -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack-cli/
git commit -m "feat: add CLI agent definition loader"
```

---

### Task 3: CLI Init Command

**Files:**
- Create: `packages/python/agentstack-cli/src/agentstack_cli/commands/init.py`
- Create: `packages/python/agentstack-cli/tests/test_init.py`

- [ ] **Step 1: Write tests for init**

`packages/python/agentstack-cli/tests/test_init.py`:
```python
import yaml
from click.testing import CliRunner

from agentstack.schema.agent import Agent
from agentstack_cli.commands.init import init


class TestInit:
    def test_creates_yaml(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(init)
            assert result.exit_code == 0
            assert (tmp_path / "agentstack.yaml").exists()

    def test_yaml_content_valid(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(init)
            content = (tmp_path / "agentstack.yaml").read_text()
            data = yaml.safe_load(content)
            agent = Agent.model_validate(data)
            assert agent.name == "my-agent"
            assert agent.model.provider.type == "anthropic"

    def test_no_overwrite(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            (tmp_path / "agentstack.yaml").write_text("existing")
            result = runner.invoke(init)
            assert result.exit_code != 0 or "already exists" in result.output.lower()
            assert (tmp_path / "agentstack.yaml").read_text() == "existing"

    def test_output_message(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(init)
            assert "agentstack.yaml" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack-cli/tests/test_init.py -v`

Expected: FAIL — module not found.

- [ ] **Step 3: Implement init command**

`packages/python/agentstack-cli/src/agentstack_cli/commands/init.py`:
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
skills:
  - name: assistant
    tools: []
    prompt: You are a helpful assistant.
channels:
  - name: api
    type: api
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-cli/tests/test_init.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-cli/
git commit -m "feat: add agentstack init command"
```

---

### Task 4: CLI Plan, Apply, Destroy, Status Commands + Entry Point

**Files:**
- Create: `packages/python/agentstack-cli/src/agentstack_cli/commands/plan.py`
- Create: `packages/python/agentstack-cli/src/agentstack_cli/commands/apply.py`
- Create: `packages/python/agentstack-cli/src/agentstack_cli/commands/destroy.py`
- Create: `packages/python/agentstack-cli/src/agentstack_cli/commands/status.py`
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/__init__.py`
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/cli.py`
- Create: `packages/python/agentstack-cli/tests/test_cli.py`

- [ ] **Step 1: Implement plan command**

`packages/python/agentstack-cli/src/agentstack_cli/commands/plan.py`:
```python
"""agentstack plan — show what would change."""

import click

from agentstack.hash import hash_agent
from agentstack_adapter_langchain import LangChainAdapter
from agentstack_cli.loader import find_agent_file, load_agent_from_file
from agentstack_provider_docker import DockerProvider


@click.command()
@click.option("--file", "file_path", default=None, help="Path to agent definition file")
def plan(file_path):
    """Show what would change if you applied."""
    path = find_agent_file(file=file_path)
    agent = load_agent_from_file(path)

    adapter = LangChainAdapter()
    errors = adapter.validate(agent)
    if errors:
        for err in errors:
            click.echo(f"Validation error: {err.field} — {err.message}", err=True)
        raise SystemExit(1)

    tree = hash_agent(agent)

    click.echo(f"Agent: {agent.name}")
    click.echo(f"Provider: {agent.model.provider.type} ({agent.model.model_name})")
    click.echo(f"Framework: langchain")
    click.echo()

    try:
        provider = DockerProvider()
        current_hash = provider.get_hash(agent.name)
        deploy_plan = provider.plan(agent, current_hash)

        if not deploy_plan.actions:
            click.echo("No changes. Already up to date.")
        else:
            click.echo("Changes:")
            for action in deploy_plan.actions:
                click.echo(f"  + {action}")
            click.echo()
            click.echo("Run 'agentstack apply' to deploy.")
    except Exception as e:
        click.echo(f"Could not connect to Docker: {e}", err=True)
        click.echo(f"Target hash: {tree.root[:16]}...")
```

- [ ] **Step 2: Implement apply command**

`packages/python/agentstack-cli/src/agentstack_cli/commands/apply.py`:
```python
"""agentstack apply — deploy or update an agent."""

import click

from agentstack.hash import hash_agent
from agentstack_adapter_langchain import LangChainAdapter
from agentstack_cli.loader import find_agent_file, load_agent_from_file
from agentstack_provider_docker import DockerProvider


@click.command()
@click.option("--file", "file_path", default=None, help="Path to agent definition file")
def apply(file_path):
    """Deploy or update an agent."""
    path = find_agent_file(file=file_path)
    agent = load_agent_from_file(path)

    click.echo(f"Agent: {agent.name}")

    # Validate
    click.echo("Validating... ", nl=False)
    adapter = LangChainAdapter()
    errors = adapter.validate(agent)
    if errors:
        click.echo("FAILED")
        for err in errors:
            click.echo(f"  {err.field}: {err.message}", err=True)
        raise SystemExit(1)
    click.echo("OK")

    # Generate code
    click.echo("Generating code... ", nl=False)
    code = adapter.generate(agent)
    click.echo("OK")

    # Plan
    provider = DockerProvider()
    current_hash = provider.get_hash(agent.name)
    deploy_plan = provider.plan(agent, current_hash)

    if not deploy_plan.actions:
        click.echo("No changes. Already up to date.")
        return

    # Apply
    click.echo("Building Docker image... ", nl=False)
    provider.set_generated_code(code)
    result = provider.apply(deploy_plan)

    if result.success:
        click.echo("OK")
        click.echo()
        click.echo(f"Deployed: {agent.name}")
        click.echo(f"  Container: agentstack-{agent.name}")
    else:
        click.echo("FAILED")
        click.echo(f"  Error: {result.message}", err=True)
        raise SystemExit(1)
```

- [ ] **Step 3: Implement destroy command**

`packages/python/agentstack-cli/src/agentstack_cli/commands/destroy.py`:
```python
"""agentstack destroy — stop and remove an agent."""

import click

from agentstack_cli.loader import find_agent_file, load_agent_from_file
from agentstack_provider_docker import DockerProvider


@click.command()
@click.option("--file", "file_path", default=None, help="Path to agent definition file")
@click.option("--name", "agent_name", default=None, help="Agent name (alternative to --file)")
def destroy(file_path, agent_name):
    """Stop and remove a deployed agent."""
    if agent_name is None:
        path = find_agent_file(file=file_path)
        agent = load_agent_from_file(path)
        agent_name = agent.name

    click.echo(f"Destroying: {agent_name}")
    provider = DockerProvider()

    click.echo(f"Stopping container agentstack-{agent_name}... ", nl=False)
    try:
        provider.destroy(agent_name)
        click.echo("OK")
        click.echo(f"Destroyed: {agent_name}")
    except Exception as e:
        click.echo("FAILED")
        click.echo(f"  Error: {e}", err=True)
        raise SystemExit(1)
```

- [ ] **Step 4: Implement status command**

`packages/python/agentstack-cli/src/agentstack_cli/commands/status.py`:
```python
"""agentstack status — show agent status."""

import click

from agentstack_cli.loader import find_agent_file, load_agent_from_file
from agentstack_provider_docker import DockerProvider


@click.command()
@click.option("--file", "file_path", default=None, help="Path to agent definition file")
@click.option("--name", "agent_name", default=None, help="Agent name (alternative to --file)")
def status(file_path, agent_name):
    """Show the status of a deployed agent."""
    if agent_name is None:
        path = find_agent_file(file=file_path)
        agent = load_agent_from_file(path)
        agent_name = agent.name

    provider = DockerProvider()
    agent_status = provider.status(agent_name)

    click.echo(f"Agent: {agent_name}")
    if agent_status.running:
        click.echo(f"Status: running")
        click.echo(f"Container: agentstack-{agent_name}")
        if agent_status.hash:
            click.echo(f"Hash: {agent_status.hash[:16]}...")
        ports = agent_status.info.get("ports", {})
        if ports and "8000/tcp" in ports and ports["8000/tcp"]:
            host_port = ports["8000/tcp"][0].get("HostPort", "?")
            click.echo(f"URL: http://localhost:{host_port}")
    else:
        click.echo(f"Status: not deployed")
```

- [ ] **Step 5: Update commands/__init__.py**

`packages/python/agentstack-cli/src/agentstack_cli/commands/__init__.py`:
```python
"""CLI subcommands."""

from agentstack_cli.commands.apply import apply
from agentstack_cli.commands.destroy import destroy
from agentstack_cli.commands.init import init
from agentstack_cli.commands.plan import plan
from agentstack_cli.commands.status import status

__all__ = ["apply", "destroy", "init", "plan", "status"]
```

- [ ] **Step 6: Update cli.py — Click entry point**

Replace `packages/python/agentstack-cli/src/agentstack_cli/cli.py` with:

```python
"""AgentStack CLI entry point."""

import click

from agentstack_cli import __version__
from agentstack_cli.commands import apply, destroy, init, plan, status


@click.group()
@click.version_option(version=__version__)
def cli():
    """AgentStack — declarative AI agent orchestration."""


cli.add_command(init)
cli.add_command(plan)
cli.add_command(apply)
cli.add_command(destroy)
cli.add_command(status)
```

- [ ] **Step 7: Write CLI integration tests**

`packages/python/agentstack-cli/tests/test_cli.py`:
```python
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from agentstack_cli.cli import cli


SAMPLE_AGENT_YAML = {
    "name": "test-bot",
    "model": {
        "name": "claude",
        "provider": {"name": "anthropic", "type": "anthropic"},
        "model_name": "claude-sonnet-4-20250514",
    },
}


@patch("agentstack_cli.commands.plan.DockerProvider")
def test_plan_new(mock_provider_cls, tmp_path):
    from agentstack.providers.base import DeployPlan

    mock_provider = MagicMock()
    mock_provider.get_hash.return_value = None
    mock_provider.plan.return_value = DeployPlan(
        agent_name="test-bot",
        actions=["Create new deployment"],
        current_hash=None,
        target_hash="abc123",
        changes={},
    )
    mock_provider_cls.return_value = mock_provider

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        (tmp_path / "agentstack.yaml").write_text(yaml.dump(SAMPLE_AGENT_YAML))
        result = runner.invoke(cli, ["plan"])

    assert result.exit_code == 0
    assert "test-bot" in result.output
    assert "Create new deployment" in result.output


@patch("agentstack_cli.commands.plan.DockerProvider")
def test_plan_up_to_date(mock_provider_cls, tmp_path):
    from agentstack.providers.base import DeployPlan

    mock_provider = MagicMock()
    mock_provider.get_hash.return_value = "abc123"
    mock_provider.plan.return_value = DeployPlan(
        agent_name="test-bot",
        actions=[],
        current_hash="abc123",
        target_hash="abc123",
        changes={},
    )
    mock_provider_cls.return_value = mock_provider

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        (tmp_path / "agentstack.yaml").write_text(yaml.dump(SAMPLE_AGENT_YAML))
        result = runner.invoke(cli, ["plan"])

    assert result.exit_code == 0
    assert "up to date" in result.output.lower()


@patch("agentstack_cli.commands.apply.DockerProvider")
def test_apply_success(mock_provider_cls, tmp_path):
    from agentstack.providers.base import DeployPlan, DeployResult

    mock_provider = MagicMock()
    mock_provider.get_hash.return_value = None
    mock_provider.plan.return_value = DeployPlan(
        agent_name="test-bot",
        actions=["Create new deployment"],
        current_hash=None,
        target_hash="abc123",
        changes={},
    )
    mock_provider.apply.return_value = DeployResult(
        agent_name="test-bot",
        success=True,
        hash="abc123",
        message="Deployed",
    )
    mock_provider_cls.return_value = mock_provider

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        (tmp_path / "agentstack.yaml").write_text(yaml.dump(SAMPLE_AGENT_YAML))
        result = runner.invoke(cli, ["apply"])

    assert result.exit_code == 0
    assert "Deployed" in result.output


@patch("agentstack_cli.commands.destroy.DockerProvider")
def test_destroy_success(mock_provider_cls, tmp_path):
    mock_provider = MagicMock()
    mock_provider_cls.return_value = mock_provider

    runner = CliRunner()
    result = runner.invoke(cli, ["destroy", "--name", "test-bot"])

    assert result.exit_code == 0
    assert "Destroyed" in result.output
    mock_provider.destroy.assert_called_once_with("test-bot")


@patch("agentstack_cli.commands.status.DockerProvider")
def test_status_running(mock_provider_cls):
    from agentstack.providers.base import AgentStatus

    mock_provider = MagicMock()
    mock_provider.status.return_value = AgentStatus(
        agent_name="test-bot",
        running=True,
        hash="abc123def456",
        info={"container": "agentstack-test-bot", "ports": {"8000/tcp": [{"HostPort": "32768"}]}},
    )
    mock_provider_cls.return_value = mock_provider

    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--name", "test-bot"])

    assert result.exit_code == 0
    assert "running" in result.output
    assert "32768" in result.output


@patch("agentstack_cli.commands.status.DockerProvider")
def test_status_not_found(mock_provider_cls):
    from agentstack.providers.base import AgentStatus

    mock_provider = MagicMock()
    mock_provider.status.return_value = AgentStatus(
        agent_name="test-bot",
        running=False,
        hash=None,
    )
    mock_provider_cls.return_value = mock_provider

    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--name", "test-bot"])

    assert result.exit_code == 0
    assert "not deployed" in result.output
```

- [ ] **Step 8: Run all CLI tests**

Run: `uv run pytest packages/python/agentstack-cli/tests/ -v`

Expected: all tests PASS.

- [ ] **Step 9: Commit**

```bash
git add packages/python/agentstack-cli/
git commit -m "feat: add CLI commands — plan, apply, destroy, status"
```

---

### Task 5: Full Verification

- [ ] **Step 1: Run all Python tests**

Run: `just test-python`

Expected: all tests pass across all packages.

- [ ] **Step 2: Run linting**

Run: `uv run ruff check packages/python/agentstack-cli/ packages/python/agentstack-provider-docker/`

Fix any lint errors.

- [ ] **Step 3: Verify CLI help works**

Run: `uv run agentstack --help`

Expected: shows Click help with `init`, `plan`, `apply`, `destroy`, `status` subcommands.

- [ ] **Step 4: Verify init works**

Run:
```bash
cd /tmp && mkdir agentstack-test && cd agentstack-test
uv run --project /Users/akolodkin/Developer/work/AgentsStack agentstack init
cat agentstack.yaml
cd /Users/akolodkin/Developer/work/AgentsStack
rm -rf /tmp/agentstack-test
```

Expected: creates valid `agentstack.yaml` with starter content.
