# Resource Provisioning with Dependency Graph — Design Spec

## Overview

Refactor resource provisioning from a flat sequential loop into a dependency-aware graph. Each provisionable resource declares its dependencies (implicit and explicit), defines a health check, and the system topo-sorts the graph to determine provisioning order. Resources only start after their dependencies are ready.

This abstraction lives in the core `agentstack` package so all platform providers (Docker, Azure, future) can reuse it.

## Problem

Today, `DockerProvider.apply()` provisions resources in a hardcoded order with ad-hoc readiness checks:

```python
# 1. network (hardcoded first)
# 2. for svc in services: provision_resource() with _wait_for_postgres() buried inside
# 3. gateways (hardcoded after resources)
# 4. agent container (hardcoded last)
```

Problems:
- Ordering is implicit in code, not declared
- Readiness checks are hardcoded per-resource inside `_provision_postgres`
- No way to express "service A depends on service B"
- Adding new resource types means editing the `apply()` ordering logic
- Can't parallelize independent resources
- Other providers (Azure) would have to reimplement the same ordering logic

## Design

### Core Package: `agentstack.provisioning`

New module in the core `agentstack` package with three concepts:

#### 1. HealthCheck

Pluggable readiness verification. Each resource type provides an appropriate health check.

```python
# agentstack/provisioning/health.py

class HealthCheck(ABC):
    """Verifies a provisioned resource is ready to accept connections."""

    @abstractmethod
    def check(self) -> bool:
        """Return True if the resource is ready."""
        ...

    def wait(self, timeout: int = 60, interval: float = 1.0) -> None:
        """Poll check() until True or timeout. Raises TimeoutError."""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.check():
                return
            time.sleep(interval)
        raise TimeoutError(f"Health check did not pass within {timeout}s")


class NoopHealthCheck(HealthCheck):
    """Always ready. For resources that don't need readiness checks (volumes, networks)."""

    def check(self) -> bool:
        return True


class TcpHealthCheck(HealthCheck):
    """Waits for a TCP port to accept connections."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def check(self) -> bool:
        import socket
        try:
            with socket.create_connection((self.host, self.port), timeout=2):
                return True
        except (ConnectionRefusedError, OSError, socket.timeout):
            return False


class CommandHealthCheck(HealthCheck):
    """Runs a command inside a Docker container and checks exit code."""

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
        import urllib.request
        try:
            resp = urllib.request.urlopen(self.url, timeout=2)
            return resp.status == 200
        except Exception:
            return False
```

#### 2. Provisionable

A node in the dependency graph. Anything that can be provisioned implements this protocol.

```python
# agentstack/provisioning/node.py

@dataclass
class ProvisionResult:
    """Result of provisioning a resource."""
    name: str
    success: bool
    info: dict = field(default_factory=dict)  # connection strings, ports, etc.
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
        """Provision the resource. context contains results from dependencies."""
        ...

    def health_check(self) -> HealthCheck:
        """Return a health check for this resource. Default: no check."""
        return NoopHealthCheck()

    def destroy(self) -> None:
        """Tear down the resource. Default: no-op."""
        pass
```

The `context` dict passed to `provision()` contains `ProvisionResult` objects from already-provisioned dependencies, keyed by name. This is how a downstream resource gets connection strings from upstream ones.

#### 3. ProvisionGraph

The DAG that collects nodes, resolves dependencies, topo-sorts, and executes in order.

```python
# agentstack/provisioning/graph.py

@dataclass
class ProvisionGraph:
    """Dependency graph for provisioning resources."""

    _nodes: dict[str, Provisionable] = field(default_factory=dict)
    _implicit_deps: dict[str, list[str]] = field(default_factory=dict)

    def add(self, node: Provisionable) -> None:
        """Add a provisionable node to the graph."""
        self._nodes[node.name] = node

    def add_dependency(self, name: str, depends_on: str) -> None:
        """Add an implicit dependency (inferred by the provider)."""
        self._implicit_deps.setdefault(name, []).append(depends_on)

    def _resolve_order(self) -> list[str]:
        """Topological sort. Raises CycleError if graph has cycles."""
        # Build adjacency: node -> list of dependencies
        deps = {}
        for name, node in self._nodes.items():
            all_deps = list(node.depends_on)
            all_deps.extend(self._implicit_deps.get(name, []))
            # Filter to only deps that exist in the graph
            deps[name] = [d for d in all_deps if d in self._nodes]

        # Kahn's algorithm
        in_degree = {name: 0 for name in self._nodes}
        for name, dep_list in deps.items():
            for dep in dep_list:
                in_degree[name] = in_degree.get(name, 0)  # ensure exists

        # Count incoming edges
        in_degree = {name: 0 for name in self._nodes}
        for name, dep_list in deps.items():
            for dep in dep_list:
                pass  # dep -> name means name has in_degree += 1
        # Proper Kahn's:
        reverse = {name: [] for name in self._nodes}  # name -> list of dependents
        in_degree = {name: 0 for name in self._nodes}
        for name, dep_list in deps.items():
            in_degree[name] = len(dep_list)
            for dep in dep_list:
                reverse[dep].append(name)

        queue = [n for n, d in in_degree.items() if d == 0]
        order = []
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
        results = {}

        for name in order:
            node = self._nodes[name]
            result = node.provision(context=results)
            results[name] = result

            if not result.success:
                raise ProvisionError(f"Failed to provision {name}: {result.error}")

            # Wait for readiness
            check = node.health_check()
            check.wait()

        return results

    def destroy_all(self) -> None:
        """Destroy all nodes in reverse dependency order."""
        order = self._resolve_order()
        for name in reversed(order):
            self._nodes[name].destroy()


class CycleError(Exception):
    pass


class ProvisionError(Exception):
    pass
```

### Implicit Dependencies

The platform provider (Docker, Azure) infers these automatically when building the graph. The core package defines the graph; the provider decides what depends on what.

| Resource | Implicit Dependencies |
|----------|----------------------|
| Network | none (root) |
| Postgres (sessions) | network |
| Postgres (memory) | network |
| SQLite volume | none |
| Redis | network |
| Agent container | network, sessions, memory, all services |
| Gateway | network, all agent containers it routes to |

### Explicit Dependencies

Users can declare additional dependencies on `Service` objects:

```python
# New optional field on Service
class Service(BaseModel):
    name: str = ""
    provider: Provider | None = None
    connection_string_env: str | None = None
    config: dict = {}
    depends_on: list[str] = []  # NEW: explicit dependency names
```

Example:
```python
agent = ast.Agent(
    name="bot",
    model=model,
    sessions=ast.Postgres(provider=docker),
    services=[
        ast.Redis(name="cache", provider=docker),
        ast.Qdrant(name="vectors", provider=docker, depends_on=["cache"]),
    ],
)
```

Here, `vectors` explicitly depends on `cache` — Qdrant won't be provisioned until Redis is ready.

### Docker Provider Changes

The Docker provider's `apply()` method builds a `ProvisionGraph` instead of doing flat loops.

**Before:**
```python
def apply(self, plan):
    network = ensure_network(self._client)
    for svc in self._all_services():
        info = provision_resource(self._client, svc, network, SECRETS_PATH)
    self.provision_gateways(network)
    # build image, run container...
```

**After:**
```python
def apply(self, plan):
    graph = ProvisionGraph()

    # Add network node
    graph.add(DockerNetworkNode(self._client))

    # Add service nodes (sessions, memory, services list)
    for svc in self._all_services():
        node = DockerServiceNode(self._client, svc, SECRETS_PATH)
        graph.add(node)
        graph.add_dependency(node.name, "network")  # implicit: services need network

    # Add agent container node
    agent_node = DockerAgentNode(self._client, self._agent, self._generated_code, plan)
    graph.add(agent_node)
    graph.add_dependency(agent_node.name, "network")
    for svc in self._all_services():
        graph.add_dependency(agent_node.name, svc.name)  # implicit: agent needs services

    # Add gateway nodes
    for gw_name, gw_info in self._collect_gateway_info().items():
        gw_node = DockerGatewayNode(self._client, gw_name, gw_info)
        graph.add(gw_node)
        graph.add_dependency(gw_node.name, agent_node.name)  # implicit: gateway needs agent

    # Execute in dependency order
    results = graph.execute()
    return self._build_result(plan, results)
```

Each Docker-specific node type wraps the existing provisioning logic:

- **`DockerNetworkNode`** — wraps `ensure_network()`, health check: `NoopHealthCheck`
- **`DockerServiceNode`** — wraps `provision_resource()`, health check: `CommandHealthCheck(pg_isready)` for postgres, `TcpHealthCheck(6379)` for redis, `NoopHealthCheck` for sqlite
- **`DockerAgentNode`** — wraps the image build + container run logic, health check: `HttpHealthCheck(http://localhost:PORT/health)`
- **`DockerGatewayNode`** — wraps gateway provisioning, health check: `HttpHealthCheck`

### What Gets Removed

- `_wait_for_postgres()` — replaced by `CommandHealthCheck` on the postgres node
- `_sync_postgres_password()` — moves into `DockerServiceNode.provision()` for postgres
- The flat resource loop in `apply()`
- The hardcoded ordering in `apply()`

### Package Structure

```
packages/python/agentstack/src/agentstack/provisioning/
    __init__.py          # exports ProvisionGraph, Provisionable, ProvisionResult, health checks
    graph.py             # ProvisionGraph, CycleError, ProvisionError
    node.py              # Provisionable ABC, ProvisionResult
    health.py            # HealthCheck ABC + NoopHealthCheck, TcpHealthCheck, CommandHealthCheck, HttpHealthCheck

packages/python/agentstack-provider-docker/src/agentstack_provider_docker/
    nodes/
        __init__.py
        network.py       # DockerNetworkNode
        service.py       # DockerServiceNode (postgres, sqlite, redis dispatch)
        agent.py         # DockerAgentNode
        gateway.py       # DockerGatewayNode
    provider.py          # Updated apply() using ProvisionGraph
```

## Out of Scope

- Parallel provisioning of independent nodes (future optimization — today we provision sequentially in topo order)
- Retry logic on provision failure (fail fast for now)
- Dry-run / plan mode that shows the graph without executing
- Azure provider implementation (uses the same core abstractions later)
