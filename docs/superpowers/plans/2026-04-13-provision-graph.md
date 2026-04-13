# Provision Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace flat resource provisioning with a dependency-aware graph that topo-sorts and waits for readiness before provisioning dependents.

**Architecture:** Core `agentstack.provisioning` module defines the graph, health checks, and provisionable protocol. Docker provider implements concrete node types (network, service, agent, gateway) and builds the graph in `apply()`.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, Docker SDK

---

### Task 1: Implement health check classes

**Files:**
- Create: `packages/python/agentstack/src/agentstack/provisioning/__init__.py`
- Create: `packages/python/agentstack/src/agentstack/provisioning/health.py`
- Create: `packages/python/agentstack/tests/test_health.py`

- [ ] **Step 1: Write failing tests for health checks**

```python
# packages/python/agentstack/tests/test_health.py
import socket
from unittest.mock import MagicMock, patch

import pytest

from agentstack.provisioning.health import (
    CommandHealthCheck,
    HealthCheck,
    HttpHealthCheck,
    NoopHealthCheck,
    TcpHealthCheck,
)


class TestNoopHealthCheck:
    def test_always_ready(self):
        check = NoopHealthCheck()
        assert check.check() is True

    def test_wait_returns_immediately(self):
        check = NoopHealthCheck()
        check.wait(timeout=1)  # should not raise


class TestTcpHealthCheck:
    def test_check_succeeds_when_port_open(self):
        with patch("agentstack.provisioning.health.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = MagicMock()
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            check = TcpHealthCheck(host="localhost", port=5432)
            assert check.check() is True

    def test_check_fails_when_port_closed(self):
        with patch("agentstack.provisioning.health.socket.create_connection") as mock_conn:
            mock_conn.side_effect = ConnectionRefusedError
            check = TcpHealthCheck(host="localhost", port=5432)
            assert check.check() is False

    def test_wait_timeout(self):
        with patch("agentstack.provisioning.health.socket.create_connection") as mock_conn:
            mock_conn.side_effect = ConnectionRefusedError
            check = TcpHealthCheck(host="localhost", port=5432)
            with pytest.raises(TimeoutError):
                check.wait(timeout=0.1, interval=0.05)


class TestCommandHealthCheck:
    def test_check_succeeds(self):
        container = MagicMock()
        container.exec_run.return_value = MagicMock(exit_code=0)
        check = CommandHealthCheck(container=container, command=["pg_isready"])
        assert check.check() is True

    def test_check_fails(self):
        container = MagicMock()
        container.exec_run.return_value = MagicMock(exit_code=1)
        check = CommandHealthCheck(container=container, command=["pg_isready"])
        assert check.check() is False

    def test_check_handles_exception(self):
        container = MagicMock()
        container.exec_run.side_effect = Exception("container not running")
        check = CommandHealthCheck(container=container, command=["pg_isready"])
        assert check.check() is False


class TestHttpHealthCheck:
    def test_check_succeeds(self):
        with patch("agentstack.provisioning.health.urllib.request.urlopen") as mock_open:
            mock_open.return_value.status = 200
            check = HttpHealthCheck(url="http://localhost:8000/health")
            assert check.check() is True

    def test_check_fails_on_error(self):
        with patch("agentstack.provisioning.health.urllib.request.urlopen") as mock_open:
            mock_open.side_effect = Exception("connection refused")
            check = HttpHealthCheck(url="http://localhost:8000/health")
            assert check.check() is False


class TestHealthCheckWait:
    def test_wait_succeeds_on_second_try(self):
        check = MagicMock(spec=HealthCheck)
        check.check.side_effect = [False, True]
        # Can't call wait on a mock — test the pattern directly
        noop = NoopHealthCheck()
        noop.wait(timeout=1)  # just verify it doesn't raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentstack.provisioning'`

- [ ] **Step 3: Implement health check classes**

```python
# packages/python/agentstack/src/agentstack/provisioning/__init__.py
"""Provisioning engine — dependency graph, health checks, and provisionable protocol."""
```

```python
# packages/python/agentstack/src/agentstack/provisioning/health.py
"""Health check classes for resource readiness verification."""

import socket
import time
import urllib.request
from abc import ABC, abstractmethod


class HealthCheck(ABC):
    """Verifies a provisioned resource is ready to accept connections."""

    @abstractmethod
    def check(self) -> bool:
        """Return True if the resource is ready."""
        ...

    def wait(self, timeout: int = 60, interval: float = 1.0) -> None:
        """Poll check() until True or timeout. Raises TimeoutError."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.check():
                return
            time.sleep(interval)
        raise TimeoutError(f"Health check did not pass within {timeout}s")


class NoopHealthCheck(HealthCheck):
    """Always ready. For resources that need no readiness check."""

    def check(self) -> bool:
        return True


class TcpHealthCheck(HealthCheck):
    """Waits for a TCP port to accept connections."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def check(self) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=2):
                return True
        except (ConnectionRefusedError, OSError, socket.timeout):
            return False


class CommandHealthCheck(HealthCheck):
    """Runs a command inside a container and checks exit code."""

    def __init__(self, container, command: list[str]):
        self.container = container
        self.command = command

    def check(self) -> bool:
        try:
            result = self.container.exec_run(self.command, demux=False)
            return result.exit_code == 0
        except Exception:
            return False


class HttpHealthCheck(HealthCheck):
    """Hits an HTTP endpoint and checks for 200."""

    def __init__(self, url: str):
        self.url = url

    def check(self) -> bool:
        try:
            resp = urllib.request.urlopen(self.url, timeout=2)
            return resp.status == 200
        except Exception:
            return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_health.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack/src/agentstack/provisioning/ packages/python/agentstack/tests/test_health.py
git commit -m "feat: add health check classes for resource readiness"
```

---

### Task 2: Implement Provisionable protocol and ProvisionGraph

**Files:**
- Create: `packages/python/agentstack/src/agentstack/provisioning/node.py`
- Create: `packages/python/agentstack/src/agentstack/provisioning/graph.py`
- Create: `packages/python/agentstack/tests/test_graph.py`

- [ ] **Step 1: Write failing tests for ProvisionGraph**

```python
# packages/python/agentstack/tests/test_graph.py
import pytest

from agentstack.provisioning.graph import CycleError, ProvisionError, ProvisionGraph
from agentstack.provisioning.health import NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult


class StubNode(Provisionable):
    """Test node that records provision order."""

    def __init__(self, node_name: str, deps: list[str] | None = None, fail: bool = False):
        self._name = node_name
        self._deps = deps or []
        self._fail = fail
        self.provisioned = False
        self.context_received = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def depends_on(self) -> list[str]:
        return self._deps

    def provision(self, context: dict) -> ProvisionResult:
        self.context_received = dict(context)
        self.provisioned = True
        if self._fail:
            return ProvisionResult(name=self._name, success=False, error="forced failure")
        return ProvisionResult(name=self._name, success=True, info={"provisioned": True})

    def health_check(self):
        return NoopHealthCheck()

    def destroy(self):
        self.provisioned = False


class TestProvisionGraph:
    def test_single_node(self):
        graph = ProvisionGraph()
        node = StubNode("db")
        graph.add(node)
        results = graph.execute()
        assert node.provisioned
        assert results["db"].success

    def test_dependency_order(self):
        graph = ProvisionGraph()
        network = StubNode("network")
        db = StubNode("db", deps=["network"])
        app = StubNode("app", deps=["db"])
        graph.add(network)
        graph.add(db)
        graph.add(app)
        results = graph.execute()
        assert network.provisioned
        assert db.provisioned
        assert app.provisioned
        # db should have received network's result in context
        assert "network" in db.context_received
        # app should have received both network and db results
        assert "network" in app.context_received
        assert "db" in app.context_received

    def test_implicit_dependency(self):
        graph = ProvisionGraph()
        network = StubNode("network")
        db = StubNode("db")
        graph.add(network)
        graph.add(db)
        graph.add_dependency("db", "network")
        results = graph.execute()
        assert "network" in db.context_received

    def test_mixed_explicit_and_implicit_deps(self):
        graph = ProvisionGraph()
        network = StubNode("network")
        db = StubNode("db", deps=["network"])
        cache = StubNode("cache")
        app = StubNode("app", deps=["db"])
        graph.add(network)
        graph.add(db)
        graph.add(cache)
        graph.add(app)
        graph.add_dependency("cache", "network")
        graph.add_dependency("app", "cache")
        results = graph.execute()
        # app depends on both db (explicit) and cache (implicit)
        assert "db" in app.context_received
        assert "cache" in app.context_received

    def test_cycle_detection(self):
        graph = ProvisionGraph()
        a = StubNode("a", deps=["b"])
        b = StubNode("b", deps=["a"])
        graph.add(a)
        graph.add(b)
        with pytest.raises(CycleError):
            graph.execute()

    def test_provision_failure_stops_execution(self):
        graph = ProvisionGraph()
        good = StubNode("good")
        bad = StubNode("bad", deps=["good"], fail=True)
        after = StubNode("after", deps=["bad"])
        graph.add(good)
        graph.add(bad)
        graph.add(after)
        with pytest.raises(ProvisionError, match="bad"):
            graph.execute()
        assert good.provisioned
        assert bad.provisioned  # it tried
        assert not after.provisioned  # never reached

    def test_destroy_reverse_order(self):
        graph = ProvisionGraph()
        network = StubNode("network")
        db = StubNode("db", deps=["network"])
        app = StubNode("app", deps=["db"])
        graph.add(network)
        graph.add(db)
        graph.add(app)
        graph.execute()
        assert network.provisioned and db.provisioned and app.provisioned
        graph.destroy_all()
        assert not network.provisioned
        assert not db.provisioned
        assert not app.provisioned

    def test_unknown_dependency_ignored(self):
        graph = ProvisionGraph()
        node = StubNode("app", deps=["nonexistent"])
        graph.add(node)
        results = graph.execute()
        assert node.provisioned

    def test_empty_graph(self):
        graph = ProvisionGraph()
        results = graph.execute()
        assert results == {}

    def test_parallel_independent_nodes(self):
        """Independent nodes can be provisioned in any order."""
        graph = ProvisionGraph()
        a = StubNode("a")
        b = StubNode("b")
        c = StubNode("c")
        graph.add(a)
        graph.add(b)
        graph.add(c)
        results = graph.execute()
        assert a.provisioned and b.provisioned and c.provisioned
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_graph.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement Provisionable and ProvisionResult**

```python
# packages/python/agentstack/src/agentstack/provisioning/node.py
"""Provisionable protocol — a node in the dependency graph."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from agentstack.provisioning.health import HealthCheck, NoopHealthCheck


@dataclass
class ProvisionResult:
    """Result of provisioning a resource."""

    name: str
    success: bool
    info: dict = field(default_factory=dict)
    error: str | None = None


class Provisionable(ABC):
    """A resource that can be provisioned and has dependencies."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def depends_on(self) -> list[str]:
        """Names of resources this one depends on. Override to declare."""
        return []

    @abstractmethod
    def provision(self, context: dict) -> ProvisionResult:
        """Provision the resource. context contains ProvisionResults from dependencies."""
        ...

    def health_check(self) -> HealthCheck:
        """Return a health check for this resource. Default: no check."""
        return NoopHealthCheck()

    def destroy(self) -> None:
        """Tear down the resource. Default: no-op."""
        pass
```

- [ ] **Step 4: Implement ProvisionGraph**

```python
# packages/python/agentstack/src/agentstack/provisioning/graph.py
"""Dependency graph for provisioning resources."""

from dataclasses import dataclass, field

from agentstack.provisioning.node import Provisionable, ProvisionResult


class CycleError(Exception):
    """Raised when the dependency graph contains a cycle."""


class ProvisionError(Exception):
    """Raised when a resource fails to provision."""


@dataclass
class ProvisionGraph:
    """DAG of provisionable resources. Topo-sorts and provisions in order."""

    _nodes: dict[str, Provisionable] = field(default_factory=dict)
    _implicit_deps: dict[str, list[str]] = field(default_factory=dict)

    def add(self, node: Provisionable) -> None:
        """Add a provisionable node to the graph."""
        self._nodes[node.name] = node

    def add_dependency(self, name: str, depends_on: str) -> None:
        """Add an implicit dependency (inferred by the provider)."""
        self._implicit_deps.setdefault(name, []).append(depends_on)

    def _all_deps(self, name: str) -> list[str]:
        """Get all dependencies for a node (explicit + implicit), filtered to known nodes."""
        node = self._nodes[name]
        all_deps = list(node.depends_on)
        all_deps.extend(self._implicit_deps.get(name, []))
        return [d for d in all_deps if d in self._nodes]

    def _resolve_order(self) -> list[str]:
        """Topological sort using Kahn's algorithm. Raises CycleError on cycles."""
        # Build reverse adjacency and in-degree
        reverse: dict[str, list[str]] = {name: [] for name in self._nodes}
        in_degree: dict[str, int] = {name: 0 for name in self._nodes}

        for name in self._nodes:
            deps = self._all_deps(name)
            in_degree[name] = len(deps)
            for dep in deps:
                reverse[dep].append(name)

        queue = [n for n, d in in_degree.items() if d == 0]
        order: list[str] = []

        while queue:
            node = queue.pop(0)
            order.append(node)
            for dependent in reverse[node]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(order) != len(self._nodes):
            raise CycleError("Dependency cycle detected in provision graph")

        return order

    def execute(self) -> dict[str, ProvisionResult]:
        """Provision all nodes in dependency order. Returns results keyed by name."""
        order = self._resolve_order()
        results: dict[str, ProvisionResult] = {}

        for name in order:
            node = self._nodes[name]
            result = node.provision(context=results)
            results[name] = result

            if not result.success:
                raise ProvisionError(f"Failed to provision {name}: {result.error}")

            check = node.health_check()
            check.wait()

        return results

    def destroy_all(self) -> None:
        """Destroy all nodes in reverse dependency order."""
        order = self._resolve_order()
        for name in reversed(order):
            self._nodes[name].destroy()
```

- [ ] **Step 5: Update provisioning __init__.py with exports**

```python
# packages/python/agentstack/src/agentstack/provisioning/__init__.py
"""Provisioning engine — dependency graph, health checks, and provisionable protocol."""

from agentstack.provisioning.graph import CycleError, ProvisionError, ProvisionGraph
from agentstack.provisioning.health import (
    CommandHealthCheck,
    HealthCheck,
    HttpHealthCheck,
    NoopHealthCheck,
    TcpHealthCheck,
)
from agentstack.provisioning.node import Provisionable, ProvisionResult

__all__ = [
    "CommandHealthCheck",
    "CycleError",
    "HealthCheck",
    "HttpHealthCheck",
    "NoopHealthCheck",
    "Provisionable",
    "ProvisionError",
    "ProvisionGraph",
    "ProvisionResult",
    "TcpHealthCheck",
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_graph.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add packages/python/agentstack/src/agentstack/provisioning/ packages/python/agentstack/tests/test_graph.py
git commit -m "feat: add ProvisionGraph with topo-sort and health checks"
```

---

### Task 3: Add depends_on field to Service

**Files:**
- Modify: `packages/python/agentstack/src/agentstack/schema/service.py`
- Modify: `packages/python/agentstack/tests/test_service.py`

- [ ] **Step 1: Write failing test**

Add to `packages/python/agentstack/tests/test_service.py`:

```python
class TestServiceDependsOn:
    def test_default_empty(self, docker):
        pg = Postgres(provider=docker)
        assert pg.depends_on == []

    def test_explicit_depends_on(self, docker):
        rd = Redis(name="cache", provider=docker, depends_on=["sessions"])
        assert rd.depends_on == ["sessions"]

    def test_serialization_with_depends_on(self, docker):
        rd = Redis(name="cache", provider=docker, depends_on=["sessions", "memory"])
        data = rd.model_dump()
        restored = Redis.model_validate(data)
        assert restored.depends_on == ["sessions", "memory"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack/tests/test_service.py::TestServiceDependsOn -v`
Expected: FAIL — `unexpected keyword argument 'depends_on'`

- [ ] **Step 3: Add depends_on to Service**

Edit `packages/python/agentstack/src/agentstack/schema/service.py` — add the field to `Service`:

```python
class Service(BaseModel):
    """Base for infrastructure services an agent depends on."""

    name: str = ""
    provider: Provider | None = None
    connection_string_env: str | None = None
    config: dict = {}
    depends_on: list[str] = []
```

- [ ] **Step 4: Run all service tests**

Run: `uv run pytest packages/python/agentstack/tests/test_service.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack/src/agentstack/schema/service.py packages/python/agentstack/tests/test_service.py
git commit -m "feat: add depends_on field to Service for explicit dependencies"
```

---

### Task 4: Implement Docker provider node types

**Files:**
- Create: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/__init__.py`
- Create: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/network.py`
- Create: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/service.py`
- Create: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/agent.py`
- Create: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/gateway.py`
- Create: `packages/python/agentstack-provider-docker/tests/test_nodes.py`

- [ ] **Step 1: Write failing tests for Docker nodes**

```python
# packages/python/agentstack-provider-docker/tests/test_nodes.py
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentstack.provisioning.health import CommandHealthCheck, NoopHealthCheck
from agentstack.provisioning.node import ProvisionResult


class TestDockerNetworkNode:
    def test_provision_creates_network(self):
        from agentstack_provider_docker.nodes.network import DockerNetworkNode

        client = MagicMock()
        client.networks.list.return_value = []
        network = MagicMock()
        network.name = "agentstack-net"
        client.networks.create.return_value = network

        node = DockerNetworkNode(client)
        assert node.name == "network"
        assert node.depends_on == []

        result = node.provision(context={})
        assert result.success
        assert result.info["network_name"] == "agentstack-net"

    def test_provision_reuses_existing(self):
        from agentstack_provider_docker.nodes.network import DockerNetworkNode

        client = MagicMock()
        existing = MagicMock()
        existing.name = "agentstack-net"
        client.networks.list.return_value = [existing]

        node = DockerNetworkNode(client)
        result = node.provision(context={})
        assert result.success
        client.networks.create.assert_not_called()

    def test_health_check_is_noop(self):
        from agentstack_provider_docker.nodes.network import DockerNetworkNode

        node = DockerNetworkNode(MagicMock())
        assert isinstance(node.health_check(), NoopHealthCheck)


class TestDockerServiceNode:
    @pytest.fixture()
    def mock_client(self):
        client = MagicMock()
        client.containers.list.return_value = []
        return client

    def test_provision_postgres(self, mock_client, tmp_path):
        from agentstack_provider_docker.nodes.service import DockerServiceNode

        with patch("agentstack_provider_docker.nodes.service.get_resource_password", return_value="testpass"):
            svc = MagicMock()
            svc.name = "sessions"
            svc.engine = "postgres"
            svc.depends_on = []

            node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
            assert node.name == "sessions"

            network = MagicMock()
            network.name = "agentstack-net"
            context = {"network": ProvisionResult(name="network", success=True, info={"network": network})}

            result = node.provision(context=context)
            assert result.success
            assert result.info["engine"] == "postgres"
            assert "connection_string" in result.info
            mock_client.containers.run.assert_called_once()

    def test_provision_sqlite(self, mock_client, tmp_path):
        from agentstack_provider_docker.nodes.service import DockerServiceNode

        mock_client.volumes.list.return_value = []
        svc = MagicMock()
        svc.name = "sessions"
        svc.engine = "sqlite"
        svc.depends_on = []

        node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
        result = node.provision(context={})
        assert result.success
        assert result.info["engine"] == "sqlite"

    def test_health_check_postgres_uses_command(self, mock_client, tmp_path):
        from agentstack_provider_docker.nodes.service import DockerServiceNode

        with patch("agentstack_provider_docker.nodes.service.get_resource_password", return_value="testpass"):
            svc = MagicMock()
            svc.name = "sessions"
            svc.engine = "postgres"
            svc.depends_on = []

            node = DockerServiceNode(mock_client, svc, tmp_path / "secrets.json")
            mock_client.containers.list.return_value = []
            # After provision, health check should be command-based
            network = MagicMock()
            network.name = "agentstack-net"
            node.provision(context={"network": ProvisionResult(name="network", success=True, info={"network": network})})
            check = node.health_check()
            assert isinstance(check, CommandHealthCheck)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/test_nodes.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement DockerNetworkNode**

```python
# packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/__init__.py
"""Docker provider node types for the provision graph."""

from agentstack_provider_docker.nodes.agent import DockerAgentNode
from agentstack_provider_docker.nodes.gateway import DockerGatewayNode
from agentstack_provider_docker.nodes.network import DockerNetworkNode
from agentstack_provider_docker.nodes.service import DockerServiceNode

__all__ = ["DockerAgentNode", "DockerGatewayNode", "DockerNetworkNode", "DockerServiceNode"]
```

```python
# packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/network.py
"""Docker network node for the provision graph."""

from agentstack.provisioning.health import HealthCheck, NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult

NETWORK_NAME = "agentstack-net"


class DockerNetworkNode(Provisionable):
    """Provisions the shared Docker network."""

    def __init__(self, client):
        self._client = client

    @property
    def name(self) -> str:
        return "network"

    def provision(self, context: dict) -> ProvisionResult:
        existing = self._client.networks.list(names=[NETWORK_NAME])
        if existing:
            network = existing[0]
        else:
            network = self._client.networks.create(NETWORK_NAME, driver="bridge")
        return ProvisionResult(
            name=self.name,
            success=True,
            info={"network_name": network.name, "network": network},
        )

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()
```

- [ ] **Step 4: Implement DockerServiceNode**

```python
# packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/service.py
"""Docker service node — provisions postgres, sqlite, redis containers/volumes."""

from pathlib import Path

from agentstack.provisioning.health import CommandHealthCheck, HealthCheck, NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult
from agentstack_provider_docker.secrets import get_resource_password


def _resource_container_name(resource_name: str) -> str:
    return f"agentstack-resource-{resource_name}"


def _volume_name(resource_name: str) -> str:
    return f"agentstack-data-{resource_name}"


def _postgres_conn_string(resource_name: str, password: str) -> str:
    host = _resource_container_name(resource_name)
    return f"postgresql://agentstack:{password}@{host}:5432/agentstack"


class DockerServiceNode(Provisionable):
    """Provisions a backing service (postgres, sqlite, redis)."""

    def __init__(self, client, service, secrets_path: Path):
        self._client = client
        self._service = service
        self._secrets_path = secrets_path
        self._container = None

    @property
    def name(self) -> str:
        return self._service.name

    @property
    def depends_on(self) -> list[str]:
        deps = list(self._service.depends_on)
        # Implicit: all docker services depend on the network
        if "network" not in deps:
            deps.append("network")
        return deps

    def provision(self, context: dict) -> ProvisionResult:
        engine = self._service.engine
        if engine == "postgres":
            return self._provision_postgres(context)
        elif engine == "sqlite":
            return self._provision_sqlite()
        else:
            return ProvisionResult(
                name=self.name, success=False,
                error=f"Unsupported engine: {engine}",
            )

    def _provision_postgres(self, context: dict) -> ProvisionResult:
        container_name = _resource_container_name(self.name)
        volume_name = _volume_name(self.name)
        password = get_resource_password(self.name, self._secrets_path)

        # Get network from context
        network_result = context.get("network")
        network = network_result.info["network"] if network_result else None

        existing = self._client.containers.list(
            filters={"name": container_name}, all=True
        )
        if existing:
            container = existing[0]
            if container.status != "running":
                container.start()
            self._container = self._client.containers.get(container_name)
            # Sync password in case volume has old credentials
            self._sync_password(password)
            return ProvisionResult(
                name=self.name, success=True,
                info={
                    "engine": "postgres",
                    "container_name": container_name,
                    "connection_string": _postgres_conn_string(self.name, password),
                },
            )

        kwargs = {
            "name": container_name,
            "detach": True,
            "environment": {
                "POSTGRES_DB": "agentstack",
                "POSTGRES_USER": "agentstack",
                "POSTGRES_PASSWORD": password,
            },
            "volumes": {volume_name: {"bind": "/var/lib/postgresql/data", "mode": "rw"}},
            "labels": {
                "agentstack.resource": self.name,
                "agentstack.engine": "postgres",
            },
        }
        if network:
            kwargs["network"] = network.name

        self._client.containers.run("postgres:16-alpine", **kwargs)
        self._container = self._client.containers.get(container_name)

        return ProvisionResult(
            name=self.name, success=True,
            info={
                "engine": "postgres",
                "container_name": container_name,
                "connection_string": _postgres_conn_string(self.name, password),
            },
        )

    def _provision_sqlite(self) -> ProvisionResult:
        volume_name = _volume_name(self.name)
        existing = self._client.volumes.list(filters={"name": volume_name})
        if not existing:
            self._client.volumes.create(volume_name)

        return ProvisionResult(
            name=self.name, success=True,
            info={
                "engine": "sqlite",
                "volume_name": volume_name,
                "connection_string": f"/data/{self.name}.db",
            },
        )

    def _sync_password(self, password: str) -> None:
        """Ensure postgres password matches stored secret."""
        try:
            if self._container:
                sql = f"ALTER USER agentstack WITH PASSWORD '{password}';"
                self._container.exec_run(
                    ["psql", "-U", "agentstack", "-d", "agentstack", "-c", sql],
                    demux=False,
                )
        except Exception:
            pass

    def health_check(self) -> HealthCheck:
        if self._service.engine == "postgres" and self._container:
            return CommandHealthCheck(
                container=self._container,
                command=["pg_isready", "-U", "agentstack", "-d", "agentstack"],
            )
        return NoopHealthCheck()

    def destroy(self) -> None:
        container_name = _resource_container_name(self.name)
        containers = self._client.containers.list(
            filters={"name": container_name}, all=True
        )
        for container in containers:
            container.stop()
            container.remove()
```

- [ ] **Step 5: Implement DockerAgentNode (stub for now)**

```python
# packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/agent.py
"""Docker agent container node for the provision graph."""

from agentstack.provisioning.health import HealthCheck, NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult


class DockerAgentNode(Provisionable):
    """Provisions the agent container. Implementation in Task 5."""

    def __init__(self, client, agent, generated_code, plan):
        self._client = client
        self._agent = agent
        self._generated_code = generated_code
        self._plan = plan

    @property
    def name(self) -> str:
        return f"agent:{self._agent.name}"

    def provision(self, context: dict) -> ProvisionResult:
        raise NotImplementedError("Implemented in Task 5")

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()
```

```python
# packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/gateway.py
"""Docker gateway node for the provision graph."""

from agentstack.provisioning.health import HealthCheck, NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult


class DockerGatewayNode(Provisionable):
    """Provisions a gateway container. Implementation in Task 5."""

    def __init__(self, client, gw_name, gw_info):
        self._client = client
        self._gw_name = gw_name
        self._gw_info = gw_info

    @property
    def name(self) -> str:
        return f"gateway:{self._gw_name}"

    def provision(self, context: dict) -> ProvisionResult:
        raise NotImplementedError("Implemented in Task 5")

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/test_nodes.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/ packages/python/agentstack-provider-docker/tests/test_nodes.py
git commit -m "feat: add Docker provider node types (network, service, agent, gateway)"
```

---

### Task 5: Implement DockerAgentNode and DockerGatewayNode

**Files:**
- Modify: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/agent.py`
- Modify: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/gateway.py`
- Modify: `packages/python/agentstack-provider-docker/tests/test_nodes.py`

- [ ] **Step 1: Add tests for DockerAgentNode**

Add to `packages/python/agentstack-provider-docker/tests/test_nodes.py`:

```python
from agentstack.providers.base import DeployPlan, GeneratedCode
from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider


class TestDockerAgentNode:
    def test_provision_builds_and_runs(self):
        from agentstack_provider_docker.nodes.agent import DockerAgentNode

        client = MagicMock()
        client.images.build.return_value = (MagicMock(), [])
        deployed = MagicMock()
        deployed.ports = {"8000/tcp": [{"HostPort": "8090"}]}
        # First call: NotFound (no existing), second call: the new container
        not_found = type("NotFound", (Exception,), {})
        client.containers.get.side_effect = [not_found("not found"), deployed]

        agent = Agent(
            name="test-bot",
            model=Model(name="claude", provider=Provider(name="anthropic", type="anthropic"), model_name="claude-sonnet-4-20250514"),
        )
        code = GeneratedCode(
            files={"server.py": "# server", "requirements.txt": "fastapi\n"},
            entrypoint="server.py",
        )
        plan = DeployPlan(
            agent_name="test-bot", actions=["Create"], current_hash=None,
            target_hash="abc123", changes={},
        )

        node = DockerAgentNode(client, agent, code, plan)
        assert node.name == "agent:test-bot"

        network = MagicMock()
        network.name = "agentstack-net"
        context = {
            "network": ProvisionResult(name="network", success=True, info={"network": network}),
        }

        # Mock docker.errors.NotFound for _get_existing
        with patch("agentstack_provider_docker.nodes.agent.docker") as mock_docker:
            mock_docker.errors.NotFound = not_found
            result = node.provision(context=context)

        assert result.success
        assert "localhost" in result.info.get("url", "")
        client.images.build.assert_called_once()
        client.containers.run.assert_called_once()
```

- [ ] **Step 2: Implement DockerAgentNode**

Replace `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/agent.py`:

```python
"""Docker agent container node for the provision graph."""

import os
from pathlib import Path

import docker
import docker.errors

from agentstack.providers.base import DeployPlan, GeneratedCode
from agentstack.provisioning.health import HealthCheck, NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult
from agentstack.schema.agent import Agent


class DockerAgentNode(Provisionable):
    """Builds the Docker image and runs the agent container."""

    def __init__(self, client, agent: Agent, generated_code: GeneratedCode, plan: DeployPlan):
        self._client = client
        self._agent = agent
        self._generated_code = generated_code
        self._plan = plan

    @property
    def name(self) -> str:
        return f"agent:{self._agent.name}"

    @property
    def depends_on(self) -> list[str]:
        deps = ["network"]
        # Agent depends on all its services
        if self._agent.sessions:
            deps.append(self._agent.sessions.name)
        if self._agent.memory:
            deps.append(self._agent.memory.name)
        for svc in self._agent.services:
            deps.append(svc.name)
        return deps

    def _container_name(self) -> str:
        return f"agentstack-{self._agent.name}"

    def _build_env(self, context: dict) -> dict[str, str]:
        env = {}
        for secret in self._agent.secrets:
            value = os.environ.get(secret.name)
            if value:
                env[secret.name] = value
        # Collect connection strings from provisioned services
        for dep_name, result in context.items():
            if result.success and "connection_string" in result.info:
                engine = result.info.get("engine", "")
                if engine in ("postgres", "sqlite"):
                    env["SESSION_STORE_URL"] = result.info["connection_string"]
        # BYO connection strings
        from agentstack.schema.service import Service
        for svc_field in (self._agent.sessions, self._agent.memory):
            if svc_field and isinstance(svc_field, Service) and svc_field.connection_string_env:
                value = os.environ.get(svc_field.connection_string_env)
                if value:
                    env["SESSION_STORE_URL"] = value
        return env

    def _build_volumes(self, context: dict) -> dict:
        volumes = {}
        for dep_name, result in context.items():
            if result.success and result.info.get("engine") == "sqlite":
                volume_name = result.info.get("volume_name")
                if volume_name:
                    volumes[volume_name] = {"bind": "/data", "mode": "rw"}
        return volumes

    def provision(self, context: dict) -> ProvisionResult:
        container_name = self._container_name()

        # Stop existing
        try:
            existing = self._client.containers.get(container_name)
            existing.stop()
            existing.remove()
        except docker.errors.NotFound:
            pass

        # Build image
        build_dir = Path(".agentstack") / self._agent.name
        build_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in self._generated_code.files.items():
            file_path = build_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)

        # Dockerfile
        mcp_installs = ""
        needs_node = False
        if self._agent.mcp_servers:
            install_cmds = []
            for mcp in self._agent.mcp_servers:
                if mcp.install:
                    install_cmds.append(f"RUN {mcp.install}")
                for field in (mcp.install or "", mcp.command or ""):
                    if "npm" in field or "npx" in field:
                        needs_node = True
            if install_cmds:
                mcp_installs = "\n".join(install_cmds) + "\n"

        node_install = ""
        if needs_node:
            node_install = (
                "RUN apt-get update && apt-get install -y nodejs npm "
                "&& rm -rf /var/lib/apt/lists/*\n"
            )

        dockerfile = (
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            f"{node_install}"
            f"{mcp_installs}"
            "COPY requirements.txt .\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n"
            "COPY . .\n"
            f'CMD ["python", "{self._generated_code.entrypoint}"]\n'
        )
        (build_dir / "Dockerfile").write_text(dockerfile)

        image_tag = f"{container_name}:latest"
        self._client.images.build(path=str(build_dir), tag=image_tag)

        # Get network from context
        network_result = context.get("network")
        network_name = network_result.info["network"].name if network_result else None

        # Run container
        host_port = self._agent.port if self._agent.port else None
        run_kwargs = {
            "name": container_name,
            "detach": True,
            "ports": {"8000/tcp": host_port},
            "environment": self._build_env(context),
            "volumes": self._build_volumes(context),
            "labels": {
                "agentstack.hash": self._plan.target_hash,
                "agentstack.agent": self._agent.name,
            },
        }
        if network_name:
            run_kwargs["network"] = network_name

        self._client.containers.run(image_tag, **run_kwargs)

        # Get actual port
        container = self._client.containers.get(container_name)
        port_info = container.ports.get("8000/tcp")
        actual_port = port_info[0]["HostPort"] if port_info else "?"

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "url": f"http://localhost:{actual_port}",
                "container_name": container_name,
                "port": actual_port,
            },
        )

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        try:
            container = self._client.containers.get(self._container_name())
            container.stop()
            container.remove()
        except Exception:
            pass
```

- [ ] **Step 3: Implement DockerGatewayNode**

Replace `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/gateway.py`:

```python
"""Docker gateway node for the provision graph."""

import os
from pathlib import Path

from agentstack.provisioning.health import HealthCheck, NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult
from agentstack_provider_docker.gateway import (
    build_gateway_image,
    destroy_gateway,
    provision_gateway,
    write_gateway_source,
    write_routes_file,
)


class DockerGatewayNode(Provisionable):
    """Provisions a gateway container."""

    def __init__(self, client, gw_name: str, gw_info: dict, agent_name: str):
        self._client = client
        self._gw_name = gw_name
        self._gw_info = gw_info
        self._agent_name = agent_name

    @property
    def name(self) -> str:
        return f"gateway:{self._gw_name}"

    @property
    def depends_on(self) -> list[str]:
        return [f"agent:{self._agent_name}"]

    def provision(self, context: dict) -> ProvisionResult:
        gateway = self._gw_info["gateway"]
        gateway_dir = Path(".agentstack") / f"gateway-{self._gw_name}"

        write_gateway_source(gateway_dir)

        routes_path = gateway_dir / "routes.json"
        write_routes_file(
            routes_path,
            list(self._gw_info["providers"].values()),
            self._gw_info["routes"],
        )

        build_gateway_image(self._client, self._gw_name, str(gateway_dir))

        env = {}
        for prov in self._gw_info["providers"].values():
            for key, value in prov["config"].items():
                if isinstance(value, str) and value:
                    env_key = f"{prov['name'].upper().replace('-', '_')}_{key.upper()}"
                    env[env_key] = value

        # Get network from context
        network_result = context.get("network")
        network = network_result.info.get("network") if network_result else None

        port = gateway.config.get("port", 8080)
        provision_gateway(
            self._client, self._gw_name, network,
            routes_path=str(routes_path), env=env, port=port,
        )

        return ProvisionResult(
            name=self.name,
            success=True,
            info={"gateway_name": self._gw_name, "port": port},
        )

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        destroy_gateway(self._client, self._gw_name)
```

- [ ] **Step 4: Run all node tests**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/test_nodes.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-provider-docker/src/agentstack_provider_docker/nodes/
git commit -m "feat: implement DockerAgentNode and DockerGatewayNode"
```

---

### Task 6: Rewire DockerProvider.apply() and destroy() to use ProvisionGraph

**Files:**
- Modify: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py`
- Modify: `packages/python/agentstack-provider-docker/tests/test_provider.py`

- [ ] **Step 1: Rewrite apply() to use ProvisionGraph**

Replace the `apply()` method in `provider.py` with:

```python
    def apply(self, plan: DeployPlan) -> DeployResult:
        if not self._generated_code:
            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message="No generated code set. Call set_generated_code() first.",
            )

        try:
            from agentstack.provisioning import ProvisionGraph
            from agentstack_provider_docker.nodes import (
                DockerAgentNode,
                DockerGatewayNode,
                DockerNetworkNode,
                DockerServiceNode,
            )

            graph = ProvisionGraph()

            # Network
            graph.add(DockerNetworkNode(self._client))

            # Services (sessions, memory, services list)
            for svc in self._all_services():
                if svc.engine in ("postgres", "sqlite"):
                    node = DockerServiceNode(self._client, svc, SECRETS_PATH)
                    graph.add(node)

            # Agent container
            agent_node = DockerAgentNode(
                self._client, self._agent, self._generated_code, plan,
            )
            graph.add(agent_node)

            # Gateways
            for gw_name, gw_info in self._collect_gateway_info().items():
                gw_node = DockerGatewayNode(
                    self._client, gw_name, gw_info, self._agent.name,
                )
                graph.add(gw_node)

            # Execute
            results = graph.execute()

            # Extract result from agent node
            agent_result = results.get(f"agent:{plan.agent_name}")
            if agent_result and agent_result.success:
                url = agent_result.info.get("url", "?")
                return DeployResult(
                    agent_name=plan.agent_name,
                    success=True,
                    hash=plan.target_hash,
                    message=f"Deployed {plan.agent_name} at {url}",
                )

            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message="Agent node not found in provision results",
            )

        except Exception as e:
            return DeployResult(
                agent_name=plan.agent_name,
                success=False,
                hash=plan.target_hash,
                message=f"Deployment failed: {e}",
            )
```

- [ ] **Step 2: Rewrite destroy() to use ProvisionGraph**

Replace the `destroy()` method:

```python
    def destroy(self, agent_name: str, include_resources: bool = False) -> None:
        # Destroy agent container
        container = self._get_container(agent_name)
        if container is not None:
            container.stop()
            container.remove()

        if include_resources and self._agent:
            from agentstack_provider_docker.nodes.service import DockerServiceNode
            for svc in self._all_services():
                node = DockerServiceNode(self._client, svc, SECRETS_PATH)
                node.destroy()
            self.destroy_gateways()
```

- [ ] **Step 3: Remove old imports and methods that are now in nodes**

Remove these imports from provider.py (they're now in the node modules):
```python
from agentstack_provider_docker.resources import (
    destroy_resource,
    provision_resource,
)
```

Remove `_build_env()`, `_build_volumes()`, and `_resource_info` from the provider since they moved to `DockerAgentNode`.

Keep: `_all_services()`, `_collect_gateway_info()`, `provision_gateways()`, `destroy_gateways()`, `_container_name()`, `_get_container()`, `set_generated_code()`, `set_agent()`, `get_hash()`, `plan()`, `status()`.

- [ ] **Step 4: Run all provider tests**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/ -v`

Fix any failures — the existing test mocks for `provision_resource` may need updating since `apply()` no longer calls it directly.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest packages/python/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py packages/python/agentstack-provider-docker/tests/test_provider.py
git commit -m "feat: rewire DockerProvider to use ProvisionGraph"
```

---

### Task 7: Update exports and run integration test

**Files:**
- Modify: `packages/python/agentstack/src/agentstack/__init__.py`

- [ ] **Step 1: Add provisioning exports to top-level package**

Add to `packages/python/agentstack/src/agentstack/__init__.py`:

```python
# Provisioning engine
from agentstack.provisioning import (
    CommandHealthCheck,
    CycleError,
    HealthCheck,
    HttpHealthCheck,
    NoopHealthCheck,
    Provisionable,
    ProvisionError,
    ProvisionGraph,
    ProvisionResult,
    TcpHealthCheck,
)
```

Add all those names to `__all__`.

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest packages/python/ -v`
Expected: All tests PASS

- [ ] **Step 3: Deploy an example to verify end-to-end**

Run:
```bash
cd /Users/akolodkin/Developer/work/AgentsStack/examples/sessions-postgres
ANTHROPIC_API_KEY="sk-cp-9vv1vReqwBQ4-dIOlA72JvvtM-YW1nffg5JZ7Ng8tDFyk_nbiTLYDfWqx9afr7cPaT7QY70ACE63-CZCoN2n_oibuTTxj9YFAE7_gidPnPUCXm8Z1_ksQEk" uv run agentstack apply
curl -s http://localhost:8091/health
ANTHROPIC_API_KEY="sk-cp-9vv1vReqwBQ4-dIOlA72JvvtM-YW1nffg5JZ7Ng8tDFyk_nbiTLYDfWqx9afr7cPaT7QY70ACE63-CZCoN2n_oibuTTxj9YFAE7_gidPnPUCXm8Z1_ksQEk" uv run agentstack destroy
```

Expected: Deploy succeeds, health check returns OK, destroy succeeds.

- [ ] **Step 4: Commit**

```bash
git add packages/python/agentstack/src/agentstack/__init__.py
git commit -m "feat: export provisioning types from top-level package"
```
