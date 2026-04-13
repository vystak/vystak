# `agentstack dev` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `agentstack dev` command that runs an agent locally with uvicorn for fast iteration, while provisioning resource containers (Postgres, Redis, Qdrant) in Docker.

**Architecture:** The dev command reuses the existing adapter for code generation and Docker provider for resource provisioning. It generates code to `.agentstack/dev/<name>/`, installs deps, starts uvicorn, watches files for changes, and auto-restarts. Agents auto-register with the gateway using the existing `POST /register-route` endpoint for multi-agent dev.

**Tech Stack:** Click (CLI), watchfiles (file watching), uvicorn (ASGI server), subprocess (process management), httpx (gateway registration)

---

## File Structure

```
packages/python/agentstack-cli/
├── src/agentstack_cli/
│   ├── cli.py                          # Modify: register dev command
│   ├── commands/
│   │   └── dev.py                      # Create: dev command + run_dev_server
│   ├── dev_resources.py                # Create: resource provisioning for dev
│   ├── dev_codegen.py                  # Create: code generation to .agentstack/dev/
│   ├── dev_process.py                  # Create: uvicorn process manager
│   ├── dev_watcher.py                  # Create: file watcher
│   ├── dev_gateway.py                  # Create: gateway registration client
│   └── dev_local_gateway.py            # Create: local gateway process
├── tests/
│   ├── test_dev.py                     # Create: dev command + integration tests
│   ├── test_dev_resources.py           # Create: resource provisioning tests
│   ├── test_dev_codegen.py             # Create: code generation tests
│   ├── test_dev_process.py             # Create: uvicorn process tests
│   ├── test_dev_watcher.py             # Create: file watcher tests
│   ├── test_dev_gateway.py             # Create: gateway registration tests
│   └── test_dev_local_gateway.py       # Create: local gateway tests
```

No gateway changes needed — the existing `POST /register-route` and `DELETE /routes/{agent_name}` endpoints are sufficient for dev mode registration.

---

### Task 1: Dev Command Skeleton

Create the `agentstack dev` CLI command with all flags, agent loading, and the main structure. This task wires up the command but stubs out the core functionality (resource provisioning, code gen, uvicorn, watcher) — those are filled in by subsequent tasks.

**Files:**
- Create: `packages/python/agentstack-cli/src/agentstack_cli/commands/dev.py`
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/cli.py`
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/__init__.py`
- Test: `packages/python/agentstack-cli/tests/test_dev.py`

- [ ] **Step 1: Write failing tests for dev command flag parsing and agent loading**

```python
# packages/python/agentstack-cli/tests/test_dev.py
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from agentstack_cli.cli import cli


class TestDevCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def test_dev_command_exists(self):
        result = self.runner.invoke(cli, ["dev", "--help"])
        assert result.exit_code == 0
        assert "Run agent locally" in result.output

    def test_dev_accepts_file_flag(self):
        result = self.runner.invoke(cli, ["dev", "--help"])
        assert "--file" in result.output

    def test_dev_accepts_clean_flag(self):
        result = self.runner.invoke(cli, ["dev", "--help"])
        assert "--clean" in result.output

    def test_dev_accepts_gateway_flag(self):
        result = self.runner.invoke(cli, ["dev", "--help"])
        assert "--gateway" in result.output

    def test_dev_accepts_port_flag(self):
        result = self.runner.invoke(cli, ["dev", "--help"])
        assert "--port" in result.output

    @patch("agentstack_cli.commands.dev.find_agent_file")
    def test_dev_fails_when_no_agent_file(self, mock_find):
        mock_find.side_effect = FileNotFoundError("No agent file found")
        result = self.runner.invoke(cli, ["dev"])
        assert result.exit_code != 0
        assert "No agent file found" in result.output

    @patch("agentstack_cli.commands.dev.run_dev_server")
    @patch("agentstack_cli.commands.dev.load_agent_from_file")
    @patch("agentstack_cli.commands.dev.find_agent_file")
    def test_dev_loads_agent_and_calls_run(self, mock_find, mock_load, mock_run):
        from pathlib import Path
        from agentstack.schema.agent import Agent
        from agentstack.schema.model import Model, ModelProvider

        mock_find.return_value = Path("agentstack.yaml")
        mock_agent = Agent(
            name="test-agent",
            model=Model(name="claude-sonnet-4-20250514", provider=ModelProvider(type="anthropic")),
        )
        mock_load.return_value = mock_agent
        mock_run.return_value = None

        result = self.runner.invoke(cli, ["dev"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs[1]["agent"].name == "test-agent"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev.py -v`
Expected: FAIL — no dev command registered

- [ ] **Step 3: Implement dev command skeleton**

```python
# packages/python/agentstack-cli/src/agentstack_cli/commands/dev.py
"""agentstack dev — run an agent locally for fast iteration."""

from pathlib import Path

import click

from agentstack_cli.loader import find_agent_file, load_agent_from_file


def run_dev_server(
    *,
    agent,
    agent_file: Path,
    port: int,
    clean: bool,
    gateway: bool,
):
    """Run the dev server. Filled in by subsequent tasks."""
    click.echo(f'Agent "{agent.name}" ready for dev server (not yet implemented)')


@click.command()
@click.option("--file", "file_path", default=None, help="Path to agent definition file")
@click.option("--port", default=None, type=int, help="Override port (default: agent.port or 8000)")
@click.option("--clean", is_flag=True, default=False, help="Tear down resources before starting")
@click.option("--gateway", is_flag=True, default=False, help="Also run a local gateway on :8080")
def dev(file_path, port, clean, gateway):
    """Run agent locally for fast iteration."""
    try:
        path = find_agent_file(file=file_path)
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)

    agent = load_agent_from_file(path)
    click.echo(f'Agent: {agent.name}')

    # Resolve port: CLI flag > schema > default
    effective_port = port or getattr(agent, "port", None) or 8000

    run_dev_server(
        agent=agent,
        agent_file=path,
        port=effective_port,
        clean=clean,
        gateway=gateway,
    )
```

Register in CLI:

```python
# Add to packages/python/agentstack-cli/src/agentstack_cli/cli.py
from agentstack_cli.commands.dev import dev
cli.add_command(dev)
```

```python
# Add to packages/python/agentstack-cli/src/agentstack_cli/commands/__init__.py
from agentstack_cli.commands.dev import dev
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-cli/src/agentstack_cli/commands/dev.py packages/python/agentstack-cli/src/agentstack_cli/cli.py packages/python/agentstack-cli/src/agentstack_cli/commands/__init__.py packages/python/agentstack-cli/tests/test_dev.py
git commit -m "feat: add agentstack dev command skeleton with CLI flags"
```

---

### Task 2: Resource Provisioning for Dev

Extract resource provisioning from the Docker provider so the dev command can start Postgres/Redis/Qdrant containers without building a Docker image for the agent itself. Reuse `DockerServiceNode` and `DockerNetworkNode` from the provision graph.

**Files:**
- Create: `packages/python/agentstack-cli/src/agentstack_cli/dev_resources.py`
- Test: `packages/python/agentstack-cli/tests/test_dev_resources.py`

- [ ] **Step 1: Write failing tests for dev resource provisioning**

```python
# packages/python/agentstack-cli/tests/test_dev_resources.py
from unittest.mock import patch, MagicMock
from agentstack.schema.agent import Agent
from agentstack.schema.model import Model, ModelProvider
from agentstack.schema.service import Postgres, Sqlite


class TestDevResources:
    def _make_agent(self, **kwargs):
        return Agent(
            name="test-agent",
            model=Model(name="claude-sonnet-4-20250514", provider=ModelProvider(type="anthropic")),
            **kwargs,
        )

    @patch("agentstack_cli.dev_resources.docker")
    def test_provision_resources_creates_network_and_postgres(self, mock_docker):
        from agentstack_cli.dev_resources import provision_dev_resources

        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_client.networks.list.return_value = []

        agent = self._make_agent(sessions=Postgres(name="sessions"))
        result = provision_dev_resources(agent, clean=False)

        assert "SESSION_STORE_URL" in result
        assert "postgresql://" in result["SESSION_STORE_URL"]

    @patch("agentstack_cli.dev_resources.docker")
    def test_provision_resources_sqlite_returns_path(self, mock_docker):
        from agentstack_cli.dev_resources import provision_dev_resources

        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client

        agent = self._make_agent(sessions=Sqlite(name="sessions"))
        result = provision_dev_resources(agent, clean=False)

        assert "SESSION_STORE_URL" in result
        assert "sessions.db" in result["SESSION_STORE_URL"]

    @patch("agentstack_cli.dev_resources.docker")
    def test_provision_resources_empty_when_no_resources(self, mock_docker):
        from agentstack_cli.dev_resources import provision_dev_resources

        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client

        agent = self._make_agent()
        result = provision_dev_resources(agent, clean=False)

        assert result == {}

    @patch("agentstack_cli.dev_resources.docker")
    def test_clean_destroys_resources_first(self, mock_docker):
        from agentstack_cli.dev_resources import provision_dev_resources

        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_client.containers.get.return_value = mock_container

        agent = self._make_agent(sessions=Postgres(name="sessions"))
        provision_dev_resources(agent, clean=True)

        mock_container.stop.assert_called()
        mock_container.remove.assert_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev_resources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentstack_cli.dev_resources'`

- [ ] **Step 3: Implement dev resource provisioning**

```python
# packages/python/agentstack-cli/src/agentstack_cli/dev_resources.py
"""Provision resource containers (Postgres, Redis, Qdrant) for dev mode."""

from pathlib import Path

import docker

from agentstack.schema.agent import Agent
from agentstack.schema.service import Postgres, Sqlite

SECRETS_PATH = Path(".agentstack/secrets.json")
NETWORK_NAME = "agentstack-net"


def provision_dev_resources(agent: Agent, clean: bool) -> dict[str, str]:
    """Provision Docker resources for the agent. Returns env vars dict.

    Uses the existing Docker provider resource logic for Postgres/Redis/Qdrant.
    SQLite resources return a local file path (no Docker needed).
    """
    env_vars: dict[str, str] = {}
    services = _collect_services(agent)

    if not services:
        return env_vars

    client = docker.from_env()

    if clean:
        _clean_resources(client, services)

    # Ensure network exists for Postgres/Redis/Qdrant
    needs_network = any(not isinstance(svc, Sqlite) for svc in services)
    if needs_network:
        _ensure_network(client)

    for role, svc in services:
        if isinstance(svc, Sqlite):
            db_path = Path(f".agentstack/dev/{agent.name}/{svc.name}.db")
            db_path.parent.mkdir(parents=True, exist_ok=True)
            env_vars[_env_key(role)] = f"sqlite:///{db_path.resolve()}"
        elif isinstance(svc, Postgres):
            from agentstack_provider_docker.resources import provision_resource, get_connection_string
            from agentstack.schema.resource import Resource

            resource = Resource(name=svc.name, engine="postgres")
            provision_resource(client, resource, NETWORK_NAME, SECRETS_PATH)
            conn = get_connection_string(svc.name, "postgres", SECRETS_PATH)
            # Rewrite connection string for localhost access
            conn = conn.replace(f"agentstack-resource-{svc.name}", "localhost")
            env_vars[_env_key(role)] = conn

    return env_vars


def _collect_services(agent: Agent) -> list[tuple[str, object]]:
    """Collect (role, service) pairs from agent schema."""
    services = []
    if agent.sessions is not None:
        services.append(("SESSION_STORE_URL", agent.sessions))
    if agent.memory is not None:
        services.append(("MEMORY_STORE_URL", agent.memory))
    if hasattr(agent, "services") and agent.services:
        for svc in agent.services:
            services.append((f"{svc.name.upper()}_URL", svc))
    return services


def _env_key(role: str) -> str:
    return role


def _ensure_network(client):
    networks = client.networks.list(names=[NETWORK_NAME])
    if not networks:
        client.networks.create(NETWORK_NAME, driver="bridge")


def _clean_resources(client, services: list[tuple[str, object]]):
    for _role, svc in services:
        if isinstance(svc, Sqlite):
            continue
        container_name = f"agentstack-resource-{svc.name}"
        try:
            container = client.containers.get(container_name)
            container.stop()
            container.remove()
        except docker.errors.NotFound:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev_resources.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-cli/src/agentstack_cli/dev_resources.py packages/python/agentstack-cli/tests/test_dev_resources.py
git commit -m "feat: add dev resource provisioning for Postgres/SQLite containers"
```

---

### Task 3: Code Generation and Dependency Installation

Generate agent code to `.agentstack/dev/<name>/` and install dependencies into the active Python environment.

**Files:**
- Create: `packages/python/agentstack-cli/src/agentstack_cli/dev_codegen.py`
- Test: `packages/python/agentstack-cli/tests/test_dev_codegen.py`

- [ ] **Step 1: Write failing tests**

```python
# packages/python/agentstack-cli/tests/test_dev_codegen.py
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

from agentstack.schema.agent import Agent
from agentstack.schema.model import Model, ModelProvider


class TestDevCodegen:
    def _make_agent(self):
        return Agent(
            name="test-agent",
            model=Model(name="claude-sonnet-4-20250514", provider=ModelProvider(type="anthropic")),
        )

    @patch("agentstack_cli.dev_codegen.LangChainAdapter")
    def test_generate_writes_files_to_dev_dir(self, mock_adapter_cls, tmp_path):
        from agentstack_cli.dev_codegen import generate_dev_code
        from agentstack.providers.base import GeneratedCode

        mock_adapter = MagicMock()
        mock_adapter_cls.return_value = mock_adapter
        mock_adapter.validate.return_value = []
        mock_adapter.generate.return_value = GeneratedCode(
            files={"server.py": "# server", "agent.py": "# agent", "requirements.txt": "fastapi"},
            entrypoint="server.py",
        )

        agent = self._make_agent()
        result = generate_dev_code(agent, agent_file=tmp_path / "agentstack.yaml", output_root=tmp_path)

        dev_dir = tmp_path / ".agentstack" / "dev" / "test-agent"
        assert dev_dir.exists()
        assert (dev_dir / "server.py").read_text() == "# server"
        assert (dev_dir / "agent.py").read_text() == "# agent"
        assert result.dev_dir == dev_dir
        assert result.entrypoint == "server.py"

    @patch("agentstack_cli.dev_codegen.LangChainAdapter")
    def test_generate_creates_tools_subdir(self, mock_adapter_cls, tmp_path):
        from agentstack_cli.dev_codegen import generate_dev_code
        from agentstack.providers.base import GeneratedCode

        mock_adapter = MagicMock()
        mock_adapter_cls.return_value = mock_adapter
        mock_adapter.validate.return_value = []
        mock_adapter.generate.return_value = GeneratedCode(
            files={
                "server.py": "# server",
                "agent.py": "# agent",
                "requirements.txt": "fastapi",
                "tools/__init__.py": "# tools",
                "tools/my_tool.py": "# tool impl",
            },
            entrypoint="server.py",
        )

        agent = self._make_agent()
        result = generate_dev_code(agent, agent_file=tmp_path / "agentstack.yaml", output_root=tmp_path)

        dev_dir = tmp_path / ".agentstack" / "dev" / "test-agent"
        assert (dev_dir / "tools" / "__init__.py").read_text() == "# tools"
        assert (dev_dir / "tools" / "my_tool.py").read_text() == "# tool impl"

    @patch("agentstack_cli.dev_codegen.LangChainAdapter")
    def test_validate_failure_raises(self, mock_adapter_cls, tmp_path):
        from agentstack_cli.dev_codegen import generate_dev_code, CodegenError
        from agentstack.providers.base import ValidationError

        mock_adapter = MagicMock()
        mock_adapter_cls.return_value = mock_adapter
        mock_adapter.validate.return_value = [
            ValidationError(field="model", message="unsupported provider")
        ]

        agent = self._make_agent()
        try:
            generate_dev_code(agent, agent_file=tmp_path / "agentstack.yaml", output_root=tmp_path)
            assert False, "Should have raised CodegenError"
        except CodegenError as e:
            assert "unsupported provider" in str(e)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev_codegen.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentstack_cli.dev_codegen'`

- [ ] **Step 3: Implement code generation for dev**

```python
# packages/python/agentstack-cli/src/agentstack_cli/dev_codegen.py
"""Generate agent code to .agentstack/dev/<name>/ for local development."""

from dataclasses import dataclass
from pathlib import Path

from agentstack.schema.agent import Agent
from agentstack_adapter_langchain import LangChainAdapter


class CodegenError(Exception):
    pass


@dataclass
class DevCodeResult:
    dev_dir: Path
    entrypoint: str
    requirements_path: Path


def generate_dev_code(
    agent: Agent,
    agent_file: Path,
    output_root: Path | None = None,
) -> DevCodeResult:
    """Generate agent code for dev mode.

    Args:
        agent: Agent schema.
        agent_file: Path to the agent definition file (used as base_dir for tool discovery).
        output_root: Root directory for .agentstack/dev/. Defaults to agent_file's parent.

    Returns:
        DevCodeResult with paths to generated code.

    Raises:
        CodegenError: If validation fails.
    """
    adapter = LangChainAdapter()

    errors = adapter.validate(agent)
    if errors:
        msgs = "; ".join(f"{e.field}: {e.message}" for e in errors)
        raise CodegenError(f"Validation failed: {msgs}")

    base_dir = agent_file.parent
    code = adapter.generate(agent, base_dir=base_dir)

    root = output_root or base_dir
    dev_dir = root / ".agentstack" / "dev" / agent.name
    dev_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in code.files.items():
        filepath = dev_dir / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content)

    return DevCodeResult(
        dev_dir=dev_dir,
        entrypoint=code.entrypoint,
        requirements_path=dev_dir / "requirements.txt",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev_codegen.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-cli/src/agentstack_cli/dev_codegen.py packages/python/agentstack-cli/tests/test_dev_codegen.py
git commit -m "feat: add dev code generation to .agentstack/dev/<name>/"
```

---

### Task 4: Uvicorn Process Manager

Manage a uvicorn subprocess — start, stop, restart. The process manager runs the generated `server.py` with the correct environment variables and port.

**Files:**
- Create: `packages/python/agentstack-cli/src/agentstack_cli/dev_process.py`
- Test: `packages/python/agentstack-cli/tests/test_dev_process.py`

- [ ] **Step 1: Write failing tests**

```python
# packages/python/agentstack-cli/tests/test_dev_process.py
import signal
from pathlib import Path
from unittest.mock import patch, MagicMock, call


class TestDevProcess:
    @patch("agentstack_cli.dev_process.subprocess.Popen")
    def test_start_launches_uvicorn(self, mock_popen):
        from agentstack_cli.dev_process import DevProcess

        proc = DevProcess(
            dev_dir=Path("/tmp/dev/test-agent"),
            entrypoint="server.py",
            port=8000,
            env={"ANTHROPIC_API_KEY": "test-key"},
        )
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        proc.start()

        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "uvicorn" in cmd[1] or "server:app" in " ".join(cmd)
        assert proc.is_running()

    @patch("agentstack_cli.dev_process.subprocess.Popen")
    def test_stop_terminates_process(self, mock_popen):
        from agentstack_cli.dev_process import DevProcess

        proc = DevProcess(
            dev_dir=Path("/tmp/dev/test-agent"),
            entrypoint="server.py",
            port=8000,
            env={},
        )
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        proc.start()
        proc.stop()

        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once()

    @patch("agentstack_cli.dev_process.subprocess.Popen")
    def test_restart_stops_then_starts(self, mock_popen):
        from agentstack_cli.dev_process import DevProcess

        proc = DevProcess(
            dev_dir=Path("/tmp/dev/test-agent"),
            entrypoint="server.py",
            port=8000,
            env={},
        )
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        proc.start()
        proc.restart()

        assert mock_popen.call_count == 2
        mock_process.terminate.assert_called_once()

    @patch("agentstack_cli.dev_process.subprocess.Popen")
    def test_env_vars_passed_to_subprocess(self, mock_popen):
        from agentstack_cli.dev_process import DevProcess

        proc = DevProcess(
            dev_dir=Path("/tmp/dev/test-agent"),
            entrypoint="server.py",
            port=8000,
            env={"MY_VAR": "my_value"},
        )
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        proc.start()

        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs["env"]["MY_VAR"] == "my_value"

    def test_is_running_false_before_start(self):
        from agentstack_cli.dev_process import DevProcess

        proc = DevProcess(
            dev_dir=Path("/tmp/dev/test-agent"),
            entrypoint="server.py",
            port=8000,
            env={},
        )
        assert not proc.is_running()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev_process.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentstack_cli.dev_process'`

- [ ] **Step 3: Implement DevProcess**

```python
# packages/python/agentstack-cli/src/agentstack_cli/dev_process.py
"""Manage a uvicorn subprocess for dev mode."""

import os
import subprocess
import sys
from pathlib import Path


class DevProcess:
    """Manages a uvicorn subprocess running the generated agent server."""

    def __init__(self, *, dev_dir: Path, entrypoint: str, port: int, env: dict[str, str]):
        self._dev_dir = dev_dir
        self._entrypoint = entrypoint
        self._port = port
        self._env = env
        self._process: subprocess.Popen | None = None

    def start(self) -> None:
        """Start the uvicorn process."""
        module_name = self._entrypoint.removesuffix(".py")
        cmd = [
            sys.executable, "-m", "uvicorn",
            f"{module_name}:app",
            "--host", "0.0.0.0",
            "--port", str(self._port),
        ]

        env = {**os.environ, **self._env}

        self._process = subprocess.Popen(
            cmd,
            cwd=str(self._dev_dir),
            env=env,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

    def stop(self) -> None:
        """Stop the uvicorn process."""
        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        self._process = None

    def restart(self) -> None:
        """Stop and re-start the uvicorn process."""
        self.stop()
        self.start()

    def is_running(self) -> bool:
        """Check if the process is alive."""
        if self._process is None:
            return False
        return self._process.poll() is None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev_process.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-cli/src/agentstack_cli/dev_process.py packages/python/agentstack-cli/tests/test_dev_process.py
git commit -m "feat: add DevProcess for managing uvicorn subprocess in dev mode"
```

---

### Task 5: File Watcher

Watch agent definition file and tools/ directory for changes. On change, call a callback (which will trigger code regeneration and process restart).

**Files:**
- Create: `packages/python/agentstack-cli/src/agentstack_cli/dev_watcher.py`
- Test: `packages/python/agentstack-cli/tests/test_dev_watcher.py`

- [ ] **Step 1: Write failing tests**

```python
# packages/python/agentstack-cli/tests/test_dev_watcher.py
import time
from pathlib import Path
from unittest.mock import MagicMock


class TestDevWatcher:
    def test_collect_watch_paths_includes_agent_file(self, tmp_path):
        from agentstack_cli.dev_watcher import collect_watch_paths

        agent_file = tmp_path / "agentstack.yaml"
        agent_file.write_text("name: test")

        paths = collect_watch_paths(agent_file)
        assert agent_file in paths

    def test_collect_watch_paths_includes_tools_dir(self, tmp_path):
        from agentstack_cli.dev_watcher import collect_watch_paths

        agent_file = tmp_path / "agentstack.yaml"
        agent_file.write_text("name: test")
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "my_tool.py").write_text("def my_tool(): pass")

        paths = collect_watch_paths(agent_file)
        assert tools_dir in paths

    def test_collect_watch_paths_skips_missing_tools_dir(self, tmp_path):
        from agentstack_cli.dev_watcher import collect_watch_paths

        agent_file = tmp_path / "agentstack.yaml"
        agent_file.write_text("name: test")

        paths = collect_watch_paths(agent_file)
        assert len(paths) == 1  # Just the agent file

    def test_collect_watch_paths_includes_instructions_file(self, tmp_path):
        from agentstack_cli.dev_watcher import collect_watch_paths

        agent_file = tmp_path / "agentstack.yaml"
        agent_file.write_text("name: test")
        instructions = tmp_path / "instructions.md"
        instructions.write_text("You are a helpful agent.")

        paths = collect_watch_paths(agent_file, instructions_file=instructions)
        assert instructions in paths
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev_watcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentstack_cli.dev_watcher'`

- [ ] **Step 3: Implement file watcher**

```python
# packages/python/agentstack-cli/src/agentstack_cli/dev_watcher.py
"""Watch agent files for changes and trigger reload."""

from pathlib import Path
from typing import Callable

from watchfiles import watch, Change


def collect_watch_paths(
    agent_file: Path,
    instructions_file: Path | None = None,
) -> list[Path]:
    """Collect paths that should be watched for changes."""
    paths = [agent_file]

    tools_dir = agent_file.parent / "tools"
    if tools_dir.is_dir():
        paths.append(tools_dir)

    if instructions_file is not None and instructions_file.is_file():
        paths.append(instructions_file)

    return paths


def run_watcher(
    watch_paths: list[Path],
    on_change: Callable[[], None],
    debounce: int = 500,
) -> None:
    """Block and watch paths for changes. Calls on_change when files change.

    Args:
        watch_paths: Files and directories to watch.
        on_change: Callback invoked on change.
        debounce: Debounce interval in milliseconds.
    """
    for _changes in watch(
        *watch_paths,
        debounce=debounce,
        step=100,
        rust_timeout=5000,
    ):
        on_change()
```

- [ ] **Step 4: Add watchfiles dependency to pyproject.toml**

Add `"watchfiles>=1.0"` to the dependencies list in `packages/python/agentstack-cli/pyproject.toml`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev_watcher.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack-cli/src/agentstack_cli/dev_watcher.py packages/python/agentstack-cli/tests/test_dev_watcher.py packages/python/agentstack-cli/pyproject.toml
git commit -m "feat: add file watcher for dev mode auto-reload"
```

---

### Task 6: Gateway Registration Client

Client-side logic for the dev server to register/deregister with a gateway using the existing `POST /register-route` and `DELETE /routes/{agent_name}` endpoints. No heartbeat needed — gateway routes persist until explicitly removed.

**Files:**
- Create: `packages/python/agentstack-cli/src/agentstack_cli/dev_gateway.py`
- Test: `packages/python/agentstack-cli/tests/test_dev_gateway.py`

- [ ] **Step 1: Write failing tests**

```python
# packages/python/agentstack-cli/tests/test_dev_gateway.py
from unittest.mock import patch, MagicMock

from agentstack.schema.agent import Agent
from agentstack.schema.model import Model, ModelProvider


class TestDevGateway:
    def _make_agent(self):
        return Agent(
            name="test-agent",
            model=Model(name="claude-sonnet-4-20250514", provider=ModelProvider(type="anthropic")),
        )

    @patch("agentstack_cli.dev_gateway.httpx.Client")
    def test_detect_gateway_found(self, mock_client_cls):
        from agentstack_cli.dev_gateway import detect_gateway

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = MagicMock(status_code=200)

        url = detect_gateway()
        assert url is not None

    @patch("agentstack_cli.dev_gateway.httpx.Client")
    def test_detect_gateway_not_found(self, mock_client_cls):
        from agentstack_cli.dev_gateway import detect_gateway

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = Exception("Connection refused")

        url = detect_gateway()
        assert url is None

    @patch("agentstack_cli.dev_gateway.httpx.Client")
    def test_register_with_gateway(self, mock_client_cls):
        from agentstack_cli.dev_gateway import register_with_gateway

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = MagicMock(status_code=200)

        agent = self._make_agent()
        result = register_with_gateway("http://localhost:8080", agent, 9000)
        assert result is True

        # Verify it calls /register-route with correct payload
        call_args = mock_client.post.call_args
        assert "/register-route" in call_args[0][0]
        payload = call_args[1]["json"]
        assert payload["agent_name"] == "test-agent"
        assert payload["agent_url"] == "http://localhost:9000"

    @patch("agentstack_cli.dev_gateway.httpx.Client")
    def test_deregister_from_gateway(self, mock_client_cls):
        from agentstack_cli.dev_gateway import deregister_from_gateway

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.delete.return_value = MagicMock(status_code=200)

        deregister_from_gateway("http://localhost:8080", "test-agent")

        # Verify it calls DELETE /routes/{agent_name}
        call_args = mock_client.delete.call_args
        assert "/routes/test-agent" in call_args[0][0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev_gateway.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentstack_cli.dev_gateway'`

- [ ] **Step 3: Implement gateway registration client**

```python
# packages/python/agentstack-cli/src/agentstack_cli/dev_gateway.py
"""Gateway registration client for dev mode.

Uses the existing gateway endpoints:
  POST /register-route — register agent as a route
  DELETE /routes/{agent_name} — remove agent route on shutdown
"""

import os

import httpx

from agentstack.schema.agent import Agent

DEFAULT_GATEWAY_URL = "http://localhost:8080"


def detect_gateway(gateway_url: str | None = None) -> str | None:
    """Check if a gateway is running. Returns URL or None."""
    url = gateway_url or os.environ.get("AGENTSTACK_GATEWAY_URL", DEFAULT_GATEWAY_URL)
    try:
        with httpx.Client(timeout=3) as client:
            resp = client.get(f"{url}/health")
            if resp.status_code == 200:
                return url
    except Exception:
        pass
    return None


def register_with_gateway(gateway_url: str, agent: Agent, port: int) -> bool:
    """Register the dev agent with the gateway via POST /register-route."""
    agent_url = f"http://localhost:{port}"
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.post(f"{gateway_url}/register-route", json={
                "provider_name": "",
                "agent_name": agent.name,
                "agent_url": agent_url,
                "channels": [],
                "listen": "messages",
                "threads": False,
                "dm": False,
            })
            return resp.status_code == 200
    except Exception:
        return False


def deregister_from_gateway(gateway_url: str, agent_name: str) -> None:
    """Deregister the agent from the gateway via DELETE /routes/{agent_name}."""
    try:
        with httpx.Client(timeout=3) as client:
            client.delete(f"{gateway_url}/routes/{agent_name}")
    except Exception:
        pass  # Best effort — gateway may already be down
```

- [ ] **Step 4: Add httpx dependency if not already present**

Check `packages/python/agentstack-cli/pyproject.toml`. If `httpx` is not listed, add `"httpx>=0.28"` to dependencies.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev_gateway.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack-cli/src/agentstack_cli/dev_gateway.py packages/python/agentstack-cli/tests/test_dev_gateway.py packages/python/agentstack-cli/pyproject.toml
git commit -m "feat: add gateway registration client for dev mode"
```

---

### Task 7: Wire Up run_dev_server

Connect all the pieces: resource provisioning, code generation, dependency installation, uvicorn process, file watcher, gateway registration, and signal handling into the `run_dev_server` function.

**Files:**
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/dev.py`
- Test: `packages/python/agentstack-cli/tests/test_dev.py` (add integration-style tests)

- [ ] **Step 1: Write failing tests for the wired-up run_dev_server**

Add to `packages/python/agentstack-cli/tests/test_dev.py`:

```python
class TestRunDevServer:
    @patch("agentstack_cli.commands.dev.run_watcher")
    @patch("agentstack_cli.commands.dev.DevProcess")
    @patch("agentstack_cli.commands.dev.generate_dev_code")
    @patch("agentstack_cli.commands.dev.provision_dev_resources")
    @patch("agentstack_cli.commands.dev.detect_gateway")
    def test_run_dev_server_full_flow(
        self, mock_detect, mock_provision, mock_codegen, mock_process_cls, mock_watcher
    ):
        from pathlib import Path
        from agentstack.schema.agent import Agent
        from agentstack.schema.model import Model, ModelProvider
        from agentstack_cli.commands.dev import run_dev_server
        from agentstack_cli.dev_codegen import DevCodeResult

        mock_detect.return_value = None  # No gateway
        mock_provision.return_value = {"SESSION_STORE_URL": "postgresql://..."}
        mock_codegen.return_value = DevCodeResult(
            dev_dir=Path("/tmp/dev/test"),
            entrypoint="server.py",
            requirements_path=Path("/tmp/dev/test/requirements.txt"),
        )

        mock_process = MagicMock()
        mock_process_cls.return_value = mock_process

        # Make watcher exit immediately
        mock_watcher.side_effect = KeyboardInterrupt()

        agent = Agent(
            name="test",
            model=Model(name="claude-sonnet-4-20250514", provider=ModelProvider(type="anthropic")),
        )

        run_dev_server(
            agent=agent,
            agent_file=Path("agentstack.yaml"),
            port=8000,
            clean=False,
            gateway=False,
        )

        mock_provision.assert_called_once()
        mock_codegen.assert_called_once()
        mock_process.start.assert_called_once()
        mock_process.stop.assert_called_once()

    @patch("agentstack_cli.commands.dev.run_watcher")
    @patch("agentstack_cli.commands.dev.DevProcess")
    @patch("agentstack_cli.commands.dev.generate_dev_code")
    @patch("agentstack_cli.commands.dev.provision_dev_resources")
    @patch("agentstack_cli.commands.dev.deregister_from_gateway")
    @patch("agentstack_cli.commands.dev.register_with_gateway")
    @patch("agentstack_cli.commands.dev.detect_gateway")
    def test_run_dev_server_registers_with_gateway(
        self, mock_detect, mock_register, mock_deregister,
        mock_provision, mock_codegen, mock_process_cls, mock_watcher
    ):
        from pathlib import Path
        from agentstack.schema.agent import Agent
        from agentstack.schema.model import Model, ModelProvider
        from agentstack_cli.commands.dev import run_dev_server
        from agentstack_cli.dev_codegen import DevCodeResult

        mock_detect.return_value = "http://localhost:8080"
        mock_register.return_value = True
        mock_provision.return_value = {}
        mock_codegen.return_value = DevCodeResult(
            dev_dir=Path("/tmp/dev/test"),
            entrypoint="server.py",
            requirements_path=Path("/tmp/dev/test/requirements.txt"),
        )
        mock_process_cls.return_value = MagicMock()
        mock_watcher.side_effect = KeyboardInterrupt()

        agent = Agent(
            name="test",
            model=Model(name="claude-sonnet-4-20250514", provider=ModelProvider(type="anthropic")),
        )

        run_dev_server(
            agent=agent,
            agent_file=Path("agentstack.yaml"),
            port=8000,
            clean=False,
            gateway=False,
        )

        mock_register.assert_called_once_with("http://localhost:8080", agent, 8000)
        mock_deregister.assert_called_once_with("http://localhost:8080", "test")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev.py::TestRunDevServer -v`
Expected: FAIL — `run_dev_server` doesn't use the new modules yet

- [ ] **Step 3: Implement the full run_dev_server**

Replace the stub `run_dev_server` in `packages/python/agentstack-cli/src/agentstack_cli/commands/dev.py`:

```python
"""agentstack dev — run an agent locally for fast iteration."""

import os
import subprocess
import sys
from pathlib import Path

import click

from agentstack_cli.loader import find_agent_file, load_agent_from_file
from agentstack_cli.dev_codegen import generate_dev_code, CodegenError
from agentstack_cli.dev_resources import provision_dev_resources
from agentstack_cli.dev_process import DevProcess
from agentstack_cli.dev_watcher import collect_watch_paths, run_watcher
from agentstack_cli.dev_gateway import (
    detect_gateway,
    register_with_gateway,
    deregister_from_gateway,
)


def run_dev_server(
    *,
    agent,
    agent_file: Path,
    port: int,
    clean: bool,
    gateway: bool,
):
    """Run the agent locally with hot reload."""

    # 1. Provision resources (Docker containers for Postgres/Redis/Qdrant)
    click.echo("Provisioning resources...")
    resource_env = provision_dev_resources(agent, clean=clean)

    # 2. Generate code
    click.echo("Generating agent code...")
    try:
        code_result = generate_dev_code(agent, agent_file=agent_file)
    except CodegenError as e:
        click.echo(f"Code generation failed: {e}", err=True)
        raise SystemExit(1)

    # 3. Install dependencies
    click.echo("Installing dependencies...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(code_result.requirements_path)],
        check=True,
    )

    # 4. Build environment variables
    env = {}
    # Secrets from .env file
    env_file = agent_file.parent / ".env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    # Resource connection strings
    env.update(resource_env)
    # Agent name
    env["AGENT_NAME"] = agent.name

    # 5. Detect and register with gateway
    gateway_url = None
    # --gateway flag handled in Task 8 (LocalGateway)

    gateway_url = detect_gateway()
    if gateway_url:
        if register_with_gateway(gateway_url, agent, port):
            click.echo(f"Gateway: registered at {gateway_url}")
        else:
            click.echo("Gateway: registration failed, running standalone")
            gateway_url = None
    else:
        click.echo("No gateway detected — running standalone. Use --gateway to start one.")

    # 6. Start uvicorn
    process = DevProcess(
        dev_dir=code_result.dev_dir,
        entrypoint=code_result.entrypoint,
        port=port,
        env=env,
    )
    process.start()

    # 7. Collect watch paths
    instructions_file = None
    if agent.instructions and Path(agent.instructions).is_file():
        instructions_file = agent_file.parent / agent.instructions
    watch_paths = collect_watch_paths(agent_file, instructions_file=instructions_file)

    # 8. Print startup summary
    click.echo("")
    click.echo(f'Agent "{agent.name}" running at http://localhost:{port}')
    resource_names = [k for k in resource_env.keys()]
    if resource_names:
        click.echo(f"Resources: {', '.join(resource_names)}")
    watched = [str(p.name) for p in watch_paths]
    click.echo(f"Watching: {', '.join(watched)}")
    click.echo("Press Ctrl+C to stop.\n")

    # 9. Watch for changes and auto-reload
    def on_change():
        click.echo("Change detected — reloading...")
        try:
            generate_dev_code(agent, agent_file=agent_file)
            process.restart()
            click.echo(f'Reloaded — agent "{agent.name}" restarted')
        except Exception as e:
            click.echo(f"Reload failed: {e}", err=True)

    try:
        run_watcher(watch_paths, on_change)
    except KeyboardInterrupt:
        pass
    finally:
        click.echo(f'\nStopping agent "{agent.name}"...')
        process.stop()
        if gateway_url:
            deregister_from_gateway(gateway_url, agent.name)
        click.echo(f'Agent "{agent.name}" stopped. Resources still running — use --clean to tear down.')


@click.command()
@click.option("--file", "file_path", default=None, help="Path to agent definition file")
@click.option("--port", default=None, type=int, help="Override port (default: agent.port or 8000)")
@click.option("--clean", is_flag=True, default=False, help="Tear down resources before starting")
@click.option("--gateway", is_flag=True, default=False, help="Also run a local gateway on :8080")
def dev(file_path, port, clean, gateway):
    """Run agent locally for fast iteration."""
    try:
        path = find_agent_file(file=file_path)
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)

    agent = load_agent_from_file(path)
    click.echo(f"Agent: {agent.name}")

    # Resolve port: CLI flag > schema > default
    effective_port = port or getattr(agent, "port", None) or 8000

    run_dev_server(
        agent=agent,
        agent_file=path,
        port=effective_port,
        clean=clean,
        gateway=gateway,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run full test suite**

Run: `cd packages/python && uv run pytest --tb=short -q`
Expected: All existing tests still PASS

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack-cli/src/agentstack_cli/commands/dev.py packages/python/agentstack-cli/tests/test_dev.py
git commit -m "feat: wire up run_dev_server with resources, codegen, uvicorn, watcher, and gateway"
```

---

### Task 8: Local Gateway Mode (`--gateway` flag)

When `--gateway` is passed, start the gateway as a local process alongside the agent. Other `agentstack dev` instances will auto-register with it.

**Files:**
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/dev.py`
- Create: `packages/python/agentstack-cli/src/agentstack_cli/dev_local_gateway.py`
- Test: `packages/python/agentstack-cli/tests/test_dev_local_gateway.py`

- [ ] **Step 1: Write failing tests**

```python
# packages/python/agentstack-cli/tests/test_dev_local_gateway.py
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestLocalGateway:
    @patch("agentstack_cli.dev_local_gateway.subprocess.Popen")
    def test_start_launches_gateway_process(self, mock_popen):
        from agentstack_cli.dev_local_gateway import LocalGateway

        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        gw = LocalGateway(port=8080)
        gw.start()

        mock_popen.assert_called_once()
        assert gw.is_running()

    @patch("agentstack_cli.dev_local_gateway.subprocess.Popen")
    def test_stop_terminates_gateway(self, mock_popen):
        from agentstack_cli.dev_local_gateway import LocalGateway

        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        gw = LocalGateway(port=8080)
        gw.start()
        gw.stop()

        mock_process.terminate.assert_called_once()

    def test_url_property(self):
        from agentstack_cli.dev_local_gateway import LocalGateway

        gw = LocalGateway(port=8080)
        assert gw.url == "http://localhost:8080"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev_local_gateway.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentstack_cli.dev_local_gateway'`

- [ ] **Step 3: Implement LocalGateway**

```python
# packages/python/agentstack-cli/src/agentstack_cli/dev_local_gateway.py
"""Run the gateway as a local process for dev mode."""

import os
import subprocess
import sys


class LocalGateway:
    """Manages a local gateway process."""

    def __init__(self, port: int = 8080):
        self._port = port
        self._process: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"http://localhost:{self._port}"

    def start(self) -> None:
        """Start the gateway as a uvicorn subprocess."""
        cmd = [
            sys.executable, "-m", "uvicorn",
            "agentstack_gateway.server:app",
            "--host", "0.0.0.0",
            "--port", str(self._port),
        ]
        env = {
            **os.environ,
            "PORT": str(self._port),
            "ROUTES_FILE": "",  # No static routes needed
        }

        self._process = subprocess.Popen(
            cmd,
            env=env,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

    def stop(self) -> None:
        """Stop the gateway process."""
        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        self._process = None

    def is_running(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None
```

- [ ] **Step 4: Integrate --gateway flag into run_dev_server**

In `packages/python/agentstack-cli/src/agentstack_cli/commands/dev.py`, add the import:

```python
from agentstack_cli.dev_local_gateway import LocalGateway
```

Replace the gateway detection section (step 5 in run_dev_server) with:

```python
    # 5. Gateway: start local or detect existing
    gateway_url = None
    local_gw = None

    if gateway:
        local_gw = LocalGateway(port=8080)
        local_gw.start()
        gateway_url = local_gw.url
        click.echo(f"Local gateway started at {gateway_url}")
        # Give the gateway a moment to start
        import time
        time.sleep(1)
    else:
        gateway_url = detect_gateway()

    if gateway_url:
        if register_with_gateway(gateway_url, agent, port):
            click.echo(f"Gateway: registered at {gateway_url}")
        else:
            click.echo("Gateway: registration failed, running standalone")
            gateway_url = None
    else:
        click.echo("No gateway detected — running standalone. Use --gateway to start one.")
```

Update the finally block to also stop the local gateway:

```python
    finally:
        click.echo(f'\nStopping agent "{agent.name}"...')
        process.stop()
        if gateway_url:
            deregister_from_gateway(gateway_url, agent.name)
        if local_gw:
            local_gw.stop()
            click.echo("Local gateway stopped.")
        click.echo(f'Agent "{agent.name}" stopped. Resources still running — use --clean to tear down.')
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd packages/python/agentstack-cli && uv run pytest tests/test_dev_local_gateway.py tests/test_dev.py -v`
Expected: All tests PASS

- [ ] **Step 6: Add agentstack-gateway as optional dependency**

In `packages/python/agentstack-cli/pyproject.toml`, add `agentstack-gateway` to dependencies (it's needed for `--gateway` mode to import `agentstack_gateway.server:app`).

- [ ] **Step 7: Run full test suite**

Run: `cd packages/python && uv run pytest --tb=short -q`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add packages/python/agentstack-cli/src/agentstack_cli/dev_local_gateway.py packages/python/agentstack-cli/tests/test_dev_local_gateway.py packages/python/agentstack-cli/src/agentstack_cli/commands/dev.py packages/python/agentstack-cli/pyproject.toml
git commit -m "feat: add --gateway flag for local gateway in dev mode"
```

---

### Task 9: Add .agentstack/dev/ to .gitignore

Ensure generated dev code is not committed to the repo.

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Check existing .gitignore**

Read `.gitignore` and check if `.agentstack/` or `.agentstack/dev/` is already listed.

- [ ] **Step 2: Add entry if missing**

Add to `.gitignore`:
```
# Dev server generated code
.agentstack/dev/
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore .agentstack/dev/ generated code"
```

---

### Task 10: End-to-End Smoke Test

Manually verify the full flow works with the `minimal` example.

**Files:** None (manual verification)

- [ ] **Step 1: Run agentstack dev with minimal example**

```bash
cd examples/minimal
cp .env.example .env  # add API key
agentstack dev
```

Expected:
- Agent code generated to `.agentstack/dev/minimal-agent/`
- Uvicorn starts on port 8000
- Agent responds at `http://localhost:8000/health`

- [ ] **Step 2: Test invoke endpoint**

```bash
curl -X POST http://localhost:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello"}'
```

Expected: JSON response with agent reply

- [ ] **Step 3: Test hot reload**

Edit the agent's instructions in `agentstack.yaml`, save. The dev server should detect the change, regenerate code, and restart within 2 seconds.

- [ ] **Step 4: Test with agentstack-chat**

```bash
agentstack-chat --url http://localhost:8000
```

Expected: Interactive chat session works

- [ ] **Step 5: Test --gateway flag**

```bash
# Terminal 1
cd examples/multi-agent/coordinator
agentstack dev --gateway

# Terminal 2
cd examples/multi-agent/researcher
agentstack dev
```

Expected: Both agents register with the local gateway, visible at `http://localhost:8080/agents`

- [ ] **Step 6: Test --clean flag**

```bash
agentstack dev --clean
```

Expected: Resource containers torn down and re-created
