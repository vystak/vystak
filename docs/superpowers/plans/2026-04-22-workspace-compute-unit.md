# Workspace Compute Unit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Spec 1 of the workspace arc per `docs/superpowers/specs/2026-04-22-workspace-compute-design.md`: turn `Workspace` from a declarative schema field into a real deployed container that the agent RPCs into via JSON-RPC 2.0 over SSH channels, backed by Vault-delivered SSH keys and per-principal secrets.

**Architecture:** A new `vystak-workspace-rpc` package runs as an OpenSSH subsystem inside the workspace container, exposing `fs.*`, `exec.*`, `git.*`, and `tool.*` services over JSON-RPC 2.0. A new Docker provider node chain (`WorkspaceSshKeygenNode` → extended `VaultAgentSidecarNode` → `DockerWorkspaceNode`) deploys the workspace; the LangChain adapter generates tool wrappers that proxy into the workspace over a persistent `asyncssh` connection. SSH keypairs are generated at apply and stored in Vault under `_vystak/workspace-ssh/<agent>/*` — zero host-side key files.

**Tech Stack:** Python 3.11+, Pydantic v2, `uv` workspace, pytest, `asyncssh` (new dep), OpenSSH server (inside workspace image), HashiCorp Vault with file-template Vault-Agent config, JSON-RPC 2.0, Docker + ACA.

**Base:** `feat/secret-manager` tip. Builds on the shipped v1 Secret Manager (Azure KV) and v1 Hashi Vault implementations. Requires both to be complete.

---

## Reference

- Spec: `docs/superpowers/specs/2026-04-22-workspace-compute-design.md`
- v1 Secret Manager spec: `docs/superpowers/specs/2026-04-19-secret-manager-design.md`
- v1 Hashi Vault spec: `docs/superpowers/specs/2026-04-20-hashicorp-vault-backend-design.md`

## File structure

**Created (new package):**
- `packages/python/vystak-workspace-rpc/` — the subsystem process that runs inside the workspace container
  - `pyproject.toml`
  - `src/vystak_workspace_rpc/__init__.py`
  - `src/vystak_workspace_rpc/server.py` — JSON-RPC 2.0 loop over stdio
  - `src/vystak_workspace_rpc/services/__init__.py` — service registry
  - `src/vystak_workspace_rpc/services/fs.py` — file ops
  - `src/vystak_workspace_rpc/services/exec.py` — process execution
  - `src/vystak_workspace_rpc/services/git.py` — git operations
  - `src/vystak_workspace_rpc/services/tool.py` — user tool discovery + invoke
  - `src/vystak_workspace_rpc/progress.py` — streaming notification helper
  - `tests/test_server.py`
  - `tests/test_service_fs.py`
  - `tests/test_service_exec.py`
  - `tests/test_service_git.py`
  - `tests/test_service_tool.py`

**Created (Docker provider nodes):**
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace.py` — `DockerWorkspaceNode`
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace_ssh_keygen.py` — `WorkspaceSshKeygenNode`
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/workspace_image.py` — Dockerfile generator
- `packages/python/vystak-provider-docker/tests/test_workspace_image.py`
- `packages/python/vystak-provider-docker/tests/test_node_workspace_ssh_keygen.py`
- `packages/python/vystak-provider-docker/tests/test_node_workspace.py`
- `packages/python/vystak-provider-docker/tests/test_workspace_integration.py` — docker-marked

**Created (LangChain adapter):**
- `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/workspace_client.py` — agent-side asyncssh wrapper
- `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/builtin_tools.py` — generates fs/exec/git tool wrappers
- `packages/python/vystak-adapter-langchain/tests/test_workspace_client.py`
- `packages/python/vystak-adapter-langchain/tests/test_builtin_tools.py`

**Created (example):**
- `examples/docker-workspace-compute/vystak.yaml`
- `examples/docker-workspace-compute/vystak.py`
- `examples/docker-workspace-compute/.env.example`
- `examples/docker-workspace-compute/README.md`
- `examples/docker-workspace-compute/tools/search_project.py`

**Modified:**
- `packages/python/vystak/src/vystak/schema/workspace.py` — new fields (image, provision, copy, dockerfile, persistence, tool_deps_manager, ssh, ssh_authorized_keys, ssh_authorized_keys_file, ssh_host_port); deprecate type=
- `packages/python/vystak/src/vystak/schema/multi_loader.py` — new validator: workspace requires Vault
- `pyproject.toml` (root) — add `asyncssh>=2.14` and `vystak-workspace-rpc` workspace member
- `packages/python/vystak-adapter-langchain/pyproject.toml` — add `asyncssh` dep
- `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py` — tool generation branches on workspace presence
- `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/adapter.py` — emits workspace bootstrap code
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_agent.py` — generate SSH file templates when workspace is declared
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/__init__.py` — export new nodes
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py` — `set_workspace_context` method; mount SSH volume
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py` — wire workspace into apply graph; accept workspace-related destroy kwargs
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py` — extend `generate_agent_hcl` to emit SSH file templates on demand
- `packages/python/vystak-cli/src/vystak_cli/commands/destroy.py` — add `--delete-workspace-data`, `--keep-workspace` flags
- `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py` — add `rotate-ssh` subcommand
- `packages/python/vystak-cli/src/vystak_cli/commands/plan.py` — Workspace section in plan output
- `packages/python/vystak-cli/src/vystak_cli/commands/apply.py` — report workspace URL + human-SSH port in apply output

---

## Phase 1 — Schema foundation

### Task 1: Extend `Workspace` schema with Spec 1 fields

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/workspace.py`
- Test: `packages/python/vystak/tests/test_workspace_schema.py` (new)

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak/tests/test_workspace_schema.py`:

```python
"""Tests for Spec 1 additions to the Workspace schema."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from vystak.schema.workspace import Workspace


def test_workspace_image_and_provision():
    ws = Workspace(
        name="dev",
        image="python:3.12-slim",
        provision=["apt-get update", "pip install ruff"],
    )
    assert ws.image == "python:3.12-slim"
    assert ws.provision == ["apt-get update", "pip install ruff"]
    assert ws.persistence == "volume"  # default


def test_workspace_copy_field():
    ws = Workspace(
        name="dev",
        image="python:3.12-slim",
        copy={"./config.toml": "/workspace/config.toml"},
    )
    assert ws.copy == {"./config.toml": "/workspace/config.toml"}


def test_workspace_persistence_bind_requires_path():
    with pytest.raises(PydanticValidationError, match="persistence='bind' requires path"):
        Workspace(name="dev", image="python:3.12-slim", persistence="bind")


def test_workspace_persistence_bind_with_path_valid():
    ws = Workspace(name="dev", image="python:3.12-slim", persistence="bind", path="/tmp/proj")
    assert ws.persistence == "bind"
    assert ws.path == "/tmp/proj"


def test_workspace_dockerfile_mutually_exclusive_with_image():
    with pytest.raises(PydanticValidationError, match="mutually exclusive"):
        Workspace(name="dev", dockerfile="./Dockerfile", image="python:3.12-slim")


def test_workspace_ssh_requires_authorized_keys():
    with pytest.raises(PydanticValidationError, match="ssh=True requires ssh_authorized_keys"):
        Workspace(name="dev", image="python:3.12-slim", ssh=True)


def test_workspace_ssh_with_keys_valid():
    ws = Workspace(
        name="dev",
        image="python:3.12-slim",
        ssh=True,
        ssh_authorized_keys=["ssh-ed25519 AAA alice@laptop"],
    )
    assert ws.ssh is True
    assert len(ws.ssh_authorized_keys) == 1


def test_workspace_legacy_type_maps_to_persistence():
    # Legacy: type="persistent" + no image should still load
    from vystak.schema.common import WorkspaceType

    ws = Workspace(name="dev", type=WorkspaceType.PERSISTENT)
    # When type is set and persistence not explicitly set, persistence is derived
    assert ws.persistence == "volume"  # persistent → volume


def test_workspace_legacy_type_sandbox_maps_to_ephemeral():
    from vystak.schema.common import WorkspaceType

    ws = Workspace(name="dev", type=WorkspaceType.SANDBOX)
    assert ws.persistence == "ephemeral"


def test_workspace_legacy_type_mounted_maps_to_bind_needs_path():
    from vystak.schema.common import WorkspaceType

    # type=mounted requires path (same as persistence=bind)
    with pytest.raises(PydanticValidationError, match="bind.*path"):
        Workspace(name="dev", type=WorkspaceType.MOUNTED)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_workspace_schema.py -v`
Expected: FAIL — new fields don't exist yet.

- [ ] **Step 3: Extend Workspace model**

Replace `packages/python/vystak/src/vystak/schema/workspace.py` body:

```python
"""Workspace model — agent execution environment."""

from typing import Self

from pydantic import model_validator

from vystak.schema.common import NamedModel, WorkspaceType
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret


class Workspace(NamedModel):
    """Execution environment an agent operates in.

    When set on an Agent and a Vault is declared, deploys as a separate
    container with its own lifecycle. See Spec 1:
    docs/superpowers/specs/2026-04-22-workspace-compute-design.md
    """

    # Image + provisioning
    image: str | None = None
    provision: list[str] = []
    copy: dict[str, str] = {}
    dockerfile: str | None = None
    tool_deps_manager: str | None = None

    # Filesystem / persistence
    persistence: str = "volume"  # "volume" | "bind" | "ephemeral"
    path: str | None = None

    # Network / resources
    network: bool = True
    gpu: bool = False
    timeout: str | None = None

    # Provider (legacy — inherited from Agent.platform.provider in v1)
    provider: Provider | None = None

    # Secrets (from v1 secret-manager)
    secrets: list[Secret] = []
    identity: str | None = None

    # Human SSH (opt-in)
    ssh: bool = False
    ssh_authorized_keys: list[str] = []
    ssh_authorized_keys_file: str | None = None
    ssh_host_port: int | None = None

    # Legacy / deprecated
    type: WorkspaceType | None = None
    # Legacy no-ops (accepted for schema compatibility, now have no effect):
    filesystem: bool = False
    terminal: bool = False
    browser: bool = False
    persist: bool = False
    max_size: str | None = None

    @model_validator(mode="after")
    def _apply_legacy_type(self) -> Self:
        """If persistence wasn't explicitly set and type= is set, map it."""
        # Pydantic v2 field-default detection: compare to default
        # If user didn't pass persistence, self.persistence == "volume" (default).
        # We want to distinguish "default value" from "explicitly set to volume".
        # Use model_fields_set which Pydantic v2 exposes.
        if "persistence" not in self.model_fields_set and self.type is not None:
            mapping = {
                WorkspaceType.PERSISTENT: "volume",
                WorkspaceType.SANDBOX: "ephemeral",
                WorkspaceType.MOUNTED: "bind",
            }
            self.persistence = mapping.get(self.type, "volume")
        return self

    @model_validator(mode="after")
    def _validate_bind_path(self) -> Self:
        if self.persistence == "bind" and not self.path:
            raise ValueError(
                f"Workspace '{self.name}' has persistence='bind' requires path= "
                f"to specify the host directory to mount."
            )
        return self

    @model_validator(mode="after")
    def _validate_dockerfile_exclusivity(self) -> Self:
        if self.dockerfile is not None:
            conflicts = []
            if self.image:
                conflicts.append("image")
            if self.provision:
                conflicts.append("provision")
            if self.copy:
                conflicts.append("copy")
            if conflicts:
                raise ValueError(
                    f"Workspace '{self.name}': dockerfile= is mutually exclusive "
                    f"with {', '.join(conflicts)}."
                )
        return self

    @model_validator(mode="after")
    def _validate_ssh_config(self) -> Self:
        if self.ssh and not (self.ssh_authorized_keys or self.ssh_authorized_keys_file):
            raise ValueError(
                f"Workspace '{self.name}' has ssh=True requires ssh_authorized_keys "
                f"or ssh_authorized_keys_file to grant human access."
            )
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_workspace_schema.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/workspace.py packages/python/vystak/tests/test_workspace_schema.py
git commit -m "feat(schema): extend Workspace with Spec 1 fields (image, provision, persistence, ssh, ...)"
```

---

### Task 2: Cross-object validator — workspace requires Vault

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/multi_loader.py`
- Test: `packages/python/vystak/tests/test_multi_loader_workspace.py` (new)

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak/tests/test_multi_loader_workspace.py`:

```python
"""Tests for the 'workspace requires Vault' cross-object validator."""

import copy

import pytest

from vystak.schema.multi_loader import load_multi_yaml


BASE_CONFIG = {
    "providers": {
        "docker": {"type": "docker"},
        "anthropic": {"type": "anthropic"},
    },
    "platforms": {"local": {"type": "docker", "provider": "docker"}},
    "models": {
        "sonnet": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"}
    },
    "agents": [
        {
            "name": "assistant",
            "model": "sonnet",
            "platform": "local",
        }
    ],
}


def test_workspace_without_vault_raises():
    data = copy.deepcopy(BASE_CONFIG)
    data["agents"][0]["workspace"] = {
        "name": "dev",
        "image": "python:3.12-slim",
    }
    with pytest.raises(ValueError, match="declares a workspace but no Vault"):
        load_multi_yaml(data)


def test_workspace_with_vault_loads():
    data = copy.deepcopy(BASE_CONFIG)
    data["vault"] = {
        "name": "v",
        "provider": "docker",
        "type": "vault",
        "mode": "deploy",
        "config": {},
    }
    data["agents"][0]["workspace"] = {
        "name": "dev",
        "image": "python:3.12-slim",
    }
    agents, _channels, vault = load_multi_yaml(data)
    assert vault is not None
    assert agents[0].workspace is not None
    assert agents[0].workspace.image == "python:3.12-slim"


def test_no_workspace_no_vault_still_loads():
    """Agents without workspaces don't require Vault."""
    agents, _channels, vault = load_multi_yaml(copy.deepcopy(BASE_CONFIG))
    assert agents[0].workspace is None
    assert vault is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_multi_loader_workspace.py -v`
Expected: FAIL — validator doesn't exist.

- [ ] **Step 3: Add validator to `multi_loader.py`**

In `packages/python/vystak/src/vystak/schema/multi_loader.py`, after the loop that constructs agents (and after the existing `workspace secrets require Azure/Docker Vault` check), add:

```python
        # Spec 1: workspace requires a Vault declaration for SSH key delivery
        if agent.workspace is not None and vault is None:
            raise ValueError(
                f"Agent '{agent.name}' declares a workspace but no Vault "
                f"is declared in this deployment. Spec 1 workspaces require "
                f"a Vault for SSH key storage and workspace-secret delivery.\n"
                f"\n"
                f"Add to your config:\n"
                f"  vault:\n"
                f"    name: vystak-vault\n"
                f"    provider: {agent.platform.provider.name if agent.platform else 'docker'}\n"
                f"    type: vault\n"
                f"    mode: deploy\n"
                f"    config: {{}}\n"
                f"\n"
                f"See docs/superpowers/specs/2026-04-19-secret-manager-design.md "
                f"for the Vault schema."
            )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak/tests/test_multi_loader_workspace.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/multi_loader.py packages/python/vystak/tests/test_multi_loader_workspace.py
git commit -m "feat(schema): validator — workspace requires Vault declaration"
```

---

### Task 3: Add `asyncssh` dependency

**Files:**
- Modify: `pyproject.toml` (root)
- Modify: `packages/python/vystak-adapter-langchain/pyproject.toml`

- [ ] **Step 1: Add to root dev-deps**

Edit `pyproject.toml` (root), under `[tool.uv] dev-dependencies`:

```toml
dev-dependencies = [
    # ... existing ...
    "asyncssh>=2.14",
]
```

- [ ] **Step 2: Add to langchain adapter runtime deps**

Edit `packages/python/vystak-adapter-langchain/pyproject.toml`, under `dependencies`:

```toml
dependencies = [
    # ... existing ...
    "asyncssh>=2.14",
]
```

- [ ] **Step 3: Sync workspace**

Run: `uv sync`
Expected: `+ asyncssh==2.x.x` in the output.

- [ ] **Step 4: Smoke-test**

Run: `uv run python -c "import asyncssh; print(asyncssh.__version__)"`
Expected: version string like `2.17.0`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock packages/python/vystak-adapter-langchain/pyproject.toml
git commit -m "chore: add asyncssh dep for agent↔workspace SSH"
```

---

## Phase 2 — Workspace RPC subsystem

### Task 4: Create `vystak-workspace-rpc` package skeleton + JSON-RPC 2.0 server

**Files:**
- Create: `packages/python/vystak-workspace-rpc/pyproject.toml`
- Create: `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/__init__.py`
- Create: `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/server.py`
- Create: `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/progress.py`
- Create: `packages/python/vystak-workspace-rpc/tests/test_server.py`
- Modify: `pyproject.toml` (root) — add workspace member

- [ ] **Step 1: Create pyproject.toml**

Create `packages/python/vystak-workspace-rpc/pyproject.toml`:

```toml
[project]
name = "vystak-workspace-rpc"
version = "0.1.0"
description = "JSON-RPC 2.0 subsystem server running inside vystak workspace containers"
readme = "README.md"
requires-python = ">=3.11"
dependencies = []  # stdlib-only; runs in user-chosen base images

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vystak_workspace_rpc"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create README placeholder**

Create `packages/python/vystak-workspace-rpc/README.md`:

```markdown
# vystak-workspace-rpc

Runs inside the workspace container as an OpenSSH subsystem. Exposes
`fs.*`, `exec.*`, `git.*`, `tool.*` services over JSON-RPC 2.0 on
stdin/stdout.

Not intended to be run directly. Installed into the workspace image by
the vystak Docker provider; launched by sshd per-channel.
```

- [ ] **Step 3: Add to workspace members in root pyproject**

In root `pyproject.toml`, under `[tool.uv] dev-dependencies`:

```toml
dev-dependencies = [
    # ... existing ...
    "vystak-workspace-rpc",
]
```

And under `[tool.uv.sources]`:

```toml
vystak-workspace-rpc = { workspace = true }
```

- [ ] **Step 4: Write failing test for JSON-RPC server**

Create `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/__init__.py`:

```python
"""Vystak workspace RPC subsystem — JSON-RPC 2.0 over stdio."""

__version__ = "0.1.0"
```

Create `packages/python/vystak-workspace-rpc/tests/__init__.py` (empty).

Create `packages/python/vystak-workspace-rpc/tests/test_server.py`:

```python
"""Tests for the JSON-RPC 2.0 server core."""

import json

import pytest

from vystak_workspace_rpc.server import JsonRpcServer


@pytest.mark.asyncio
async def test_server_handles_single_request():
    async def echo(params):
        return {"echoed": params.get("message", "")}

    srv = JsonRpcServer()
    srv.register("test.echo", echo)

    req = json.dumps({"jsonrpc": "2.0", "id": "1", "method": "test.echo",
                      "params": {"message": "hi"}})
    response_line = await srv.handle_line(req)
    assert response_line is not None
    resp = json.loads(response_line)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == "1"
    assert resp["result"] == {"echoed": "hi"}


@pytest.mark.asyncio
async def test_server_handles_unknown_method():
    srv = JsonRpcServer()
    req = json.dumps({"jsonrpc": "2.0", "id": "2", "method": "nope", "params": {}})
    line = await srv.handle_line(req)
    resp = json.loads(line)
    assert resp["error"]["code"] == -32601
    assert "Method not found" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_server_handles_handler_exception():
    async def boom(params):
        raise ValueError("kaboom")

    srv = JsonRpcServer()
    srv.register("test.boom", boom)

    req = json.dumps({"jsonrpc": "2.0", "id": "3", "method": "test.boom", "params": {}})
    line = await srv.handle_line(req)
    resp = json.loads(line)
    assert resp["error"]["code"] == -32000
    assert "kaboom" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_server_handles_malformed_json():
    srv = JsonRpcServer()
    line = await srv.handle_line("not json {")
    resp = json.loads(line)
    assert resp["error"]["code"] == -32700
    assert "Parse error" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_server_notification_has_no_response():
    """Requests without an id are notifications — no response expected."""
    async def noop(params):
        return None

    srv = JsonRpcServer()
    srv.register("test.noop", noop)
    req = json.dumps({"jsonrpc": "2.0", "method": "test.noop", "params": {}})
    line = await srv.handle_line(req)
    assert line is None
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv sync && uv run pytest packages/python/vystak-workspace-rpc/tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: vystak_workspace_rpc.server`.

- [ ] **Step 6: Implement server**

Create `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/server.py`:

```python
"""JSON-RPC 2.0 server over stdio, with per-channel dispatch.

Reads newline-delimited JSON from stdin, writes responses to stdout.
One instance per SSH channel (one process spawned by sshd for each
`subsystem vystak-rpc` request).
"""

import asyncio
import json
import sys
from collections.abc import Callable

# JSON-RPC 2.0 error codes
ERROR_PARSE = -32700
ERROR_INVALID_REQUEST = -32600
ERROR_METHOD_NOT_FOUND = -32601
ERROR_INVALID_PARAMS = -32602
ERROR_INTERNAL = -32603
ERROR_SERVER = -32000  # implementation-defined server error


class JsonRpcServer:
    """Minimal JSON-RPC 2.0 handler.

    Register methods via register(); call handle_line() to process one
    request line and get the response line (or None for notifications).
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable] = {}

    def register(self, method: str, handler: Callable) -> None:
        """Register an async handler(params: dict) -> Any."""
        self._handlers[method] = handler

    async def handle_line(self, line: str) -> str | None:
        """Process one JSON-RPC request line. Returns response line or None."""
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            return self._error_response(None, ERROR_PARSE, f"Parse error: {e}")

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method is None:
            return self._error_response(req_id, ERROR_INVALID_REQUEST,
                                        "Invalid Request: method missing")

        handler = self._handlers.get(method)
        if handler is None:
            if req_id is None:
                return None  # notification to unknown method, silent
            return self._error_response(req_id, ERROR_METHOD_NOT_FOUND,
                                        f"Method not found: {method}")

        try:
            result = await handler(params)
        except Exception as e:  # noqa: BLE001
            if req_id is None:
                return None  # notification errors are silent
            return self._error_response(req_id, ERROR_SERVER, str(e))

        if req_id is None:
            return None  # notification: no response

        return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})

    def _error_response(self, req_id, code: int, message: str,
                        data: dict | None = None) -> str:
        err = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return json.dumps({"jsonrpc": "2.0", "id": req_id, "error": err})


async def run_stdio(server: JsonRpcServer) -> None:
    """Read JSONL from stdin, write JSONL responses to stdout."""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line_bytes = await reader.readline()
        if not line_bytes:
            return  # EOF
        line = line_bytes.decode("utf-8").rstrip("\n")
        if not line:
            continue
        resp = await server.handle_line(line)
        if resp is not None:
            sys.stdout.write(resp + "\n")
            sys.stdout.flush()
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest packages/python/vystak-workspace-rpc/tests/test_server.py -v`
Expected: PASS (5 tests).

- [ ] **Step 8: Commit**

```bash
git add packages/python/vystak-workspace-rpc/ pyproject.toml uv.lock
git commit -m "feat(workspace-rpc): JSON-RPC 2.0 server core with stdio transport"
```

---

### Task 5: `fs.*` service handlers

**Files:**
- Create: `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/services/__init__.py`
- Create: `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/services/fs.py`
- Create: `packages/python/vystak-workspace-rpc/tests/test_service_fs.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-workspace-rpc/tests/test_service_fs.py`:

```python
"""Tests for the fs.* service."""

from pathlib import Path

import pytest

from vystak_workspace_rpc.services.fs import register_fs


def _build_server(workspace_root: Path):
    from vystak_workspace_rpc.server import JsonRpcServer

    srv = JsonRpcServer()
    register_fs(srv, workspace_root)
    return srv


@pytest.mark.asyncio
async def test_fs_write_and_read(tmp_path):
    srv = _build_server(tmp_path)
    await srv._handlers["fs.writeFile"]({"path": "a.txt", "content": "hello"})
    result = await srv._handlers["fs.readFile"]({"path": "a.txt"})
    assert result == "hello"


@pytest.mark.asyncio
async def test_fs_exists(tmp_path):
    srv = _build_server(tmp_path)
    (tmp_path / "foo").write_text("x")
    r = await srv._handlers["fs.exists"]({"path": "foo"})
    assert r is True
    r = await srv._handlers["fs.exists"]({"path": "nope"})
    assert r is False


@pytest.mark.asyncio
async def test_fs_list_dir(tmp_path):
    (tmp_path / "a.py").write_text("1")
    (tmp_path / "b.md").write_text("2")
    (tmp_path / "sub").mkdir()
    srv = _build_server(tmp_path)
    entries = await srv._handlers["fs.listDir"]({"path": "."})
    names = {e["name"] for e in entries}
    assert names == {"a.py", "b.md", "sub"}
    sub = next(e for e in entries if e["name"] == "sub")
    assert sub["type"] == "directory"
    a = next(e for e in entries if e["name"] == "a.py")
    assert a["type"] == "file"
    assert a["size"] == 1


@pytest.mark.asyncio
async def test_fs_delete_file(tmp_path):
    (tmp_path / "gone.txt").write_text("bye")
    srv = _build_server(tmp_path)
    await srv._handlers["fs.deleteFile"]({"path": "gone.txt"})
    assert not (tmp_path / "gone.txt").exists()


@pytest.mark.asyncio
async def test_fs_mkdir_with_parents(tmp_path):
    srv = _build_server(tmp_path)
    await srv._handlers["fs.mkdir"]({"path": "a/b/c", "parents": True})
    assert (tmp_path / "a" / "b" / "c").is_dir()


@pytest.mark.asyncio
async def test_fs_move(tmp_path):
    (tmp_path / "src.txt").write_text("x")
    srv = _build_server(tmp_path)
    await srv._handlers["fs.move"]({"src": "src.txt", "dst": "dst.txt"})
    assert not (tmp_path / "src.txt").exists()
    assert (tmp_path / "dst.txt").read_text() == "x"


@pytest.mark.asyncio
async def test_fs_edit_replaces(tmp_path):
    (tmp_path / "f.py").write_text("hello world")
    srv = _build_server(tmp_path)
    result = await srv._handlers["fs.edit"]({
        "path": "f.py", "old_str": "world", "new_str": "vystak"
    })
    assert (tmp_path / "f.py").read_text() == "hello vystak"
    assert "diff" in result


@pytest.mark.asyncio
async def test_fs_edit_old_str_not_found_raises(tmp_path):
    (tmp_path / "f.py").write_text("hello world")
    srv = _build_server(tmp_path)
    with pytest.raises(ValueError, match="old_str not found"):
        await srv._handlers["fs.edit"]({
            "path": "f.py", "old_str": "missing", "new_str": "x"
        })


@pytest.mark.asyncio
async def test_fs_readFile_escape_attempt_raises(tmp_path):
    """Paths outside workspace root are rejected."""
    srv = _build_server(tmp_path)
    with pytest.raises(ValueError, match="outside workspace root"):
        await srv._handlers["fs.readFile"]({"path": "../../../etc/passwd"})
```

- [ ] **Step 2: Run to verify fails**

Run: `uv run pytest packages/python/vystak-workspace-rpc/tests/test_service_fs.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement fs service**

Create `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/services/__init__.py` (empty).

Create `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/services/fs.py`:

```python
"""fs.* service — file operations rooted at the workspace directory.

All paths are resolved relative to the workspace root. Attempts to
escape via `..` or absolute paths outside the root raise ValueError.
"""

import difflib
import shutil
from pathlib import Path


def register_fs(server, workspace_root: Path) -> None:
    """Register fs.* handlers on the given JsonRpcServer."""
    root = Path(workspace_root).resolve()

    def _resolve(path: str) -> Path:
        p = (root / path).resolve()
        try:
            p.relative_to(root)
        except ValueError:
            raise ValueError(
                f"Path '{path}' resolves outside workspace root {root}"
            ) from None
        return p

    async def read_file(params: dict) -> str:
        encoding = params.get("encoding", "utf-8")
        return _resolve(params["path"]).read_text(encoding=encoding)

    async def write_file(params: dict) -> None:
        p = _resolve(params["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        encoding = params.get("encoding", "utf-8")
        p.write_text(params["content"], encoding=encoding)
        if "mode" in params:
            p.chmod(int(params["mode"], 8) if isinstance(params["mode"], str)
                    else params["mode"])
        return None

    async def append_file(params: dict) -> None:
        p = _resolve(params["path"])
        encoding = params.get("encoding", "utf-8")
        with p.open("a", encoding=encoding) as fh:
            fh.write(params["content"])
        return None

    async def delete_file(params: dict) -> None:
        p = _resolve(params["path"])
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return None

    async def list_dir(params: dict) -> list[dict]:
        p = _resolve(params["path"])
        entries = []
        for entry in sorted(p.iterdir()):
            stat = entry.stat()
            entries.append({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })
        return entries

    async def stat(params: dict) -> dict:
        p = _resolve(params["path"])
        s = p.stat()
        return {
            "type": "directory" if p.is_dir() else "file",
            "size": s.st_size,
            "mtime": s.st_mtime,
            "permissions": oct(s.st_mode & 0o777),
        }

    async def exists(params: dict) -> bool:
        try:
            return _resolve(params["path"]).exists()
        except ValueError:
            return False

    async def mkdir(params: dict) -> None:
        p = _resolve(params["path"])
        p.mkdir(parents=bool(params.get("parents", False)), exist_ok=True)
        return None

    async def move(params: dict) -> None:
        src = _resolve(params["src"])
        dst = _resolve(params["dst"])
        shutil.move(str(src), str(dst))
        return None

    async def edit(params: dict) -> dict:
        p = _resolve(params["path"])
        old = params["old_str"]
        new = params["new_str"]
        content = p.read_text()
        if old not in content:
            raise ValueError(f"old_str not found in {params['path']}")
        updated = content.replace(old, new, 1)  # one replacement by default
        p.write_text(updated)
        diff = "\n".join(difflib.unified_diff(
            content.splitlines(), updated.splitlines(),
            fromfile=params["path"], tofile=params["path"], lineterm="",
        ))
        return {"diff": diff}

    server.register("fs.readFile", read_file)
    server.register("fs.writeFile", write_file)
    server.register("fs.appendFile", append_file)
    server.register("fs.deleteFile", delete_file)
    server.register("fs.listDir", list_dir)
    server.register("fs.stat", stat)
    server.register("fs.exists", exists)
    server.register("fs.mkdir", mkdir)
    server.register("fs.move", move)
    server.register("fs.edit", edit)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-workspace-rpc/tests/test_service_fs.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/services/ packages/python/vystak-workspace-rpc/tests/test_service_fs.py
git commit -m "feat(workspace-rpc): fs.* service with path-escape prevention"
```

---

### Task 6: `exec.*` service with streaming

**Files:**
- Create: `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/services/exec.py`
- Create: `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/progress.py`
- Create: `packages/python/vystak-workspace-rpc/tests/test_service_exec.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-workspace-rpc/tests/test_service_exec.py`:

```python
"""Tests for exec.* service."""

import asyncio

import pytest

from vystak_workspace_rpc.services.exec import register_exec


def _build_server(workspace_root, chunks_out):
    from vystak_workspace_rpc.server import JsonRpcServer

    srv = JsonRpcServer()

    async def progress_sink(channel: str, data: dict):
        chunks_out.append((channel, data))

    register_exec(srv, workspace_root, progress_emitter=progress_sink)
    return srv


@pytest.mark.asyncio
async def test_exec_run_success(tmp_path):
    chunks = []
    srv = _build_server(tmp_path, chunks)
    result = await srv._handlers["exec.run"]({
        "cmd": ["echo", "hello"], "cwd": "."
    })
    assert result["exit_code"] == 0
    assert any("hello" in c[1].get("chunk", "") for c in chunks)


@pytest.mark.asyncio
async def test_exec_run_nonzero_exit(tmp_path):
    chunks = []
    srv = _build_server(tmp_path, chunks)
    result = await srv._handlers["exec.run"]({
        "cmd": ["sh", "-c", "exit 3"]
    })
    assert result["exit_code"] == 3


@pytest.mark.asyncio
async def test_exec_run_streams_stdout(tmp_path):
    chunks = []
    srv = _build_server(tmp_path, chunks)
    await srv._handlers["exec.run"]({
        "cmd": ["sh", "-c", "echo line1; echo line2"]
    })
    stdout_chunks = [c[1]["chunk"] for c in chunks if c[0] == "stdout"]
    combined = "".join(stdout_chunks)
    assert "line1" in combined and "line2" in combined


@pytest.mark.asyncio
async def test_exec_shell_runs_script(tmp_path):
    chunks = []
    srv = _build_server(tmp_path, chunks)
    result = await srv._handlers["exec.shell"]({
        "script": "echo hi && false || echo recovered"
    })
    assert result["exit_code"] == 0
    combined = "".join(c[1].get("chunk", "") for c in chunks)
    assert "hi" in combined and "recovered" in combined


@pytest.mark.asyncio
async def test_exec_run_timeout(tmp_path):
    chunks = []
    srv = _build_server(tmp_path, chunks)
    with pytest.raises(TimeoutError):
        await srv._handlers["exec.run"]({
            "cmd": ["sleep", "10"], "timeout_s": 0.2
        })


@pytest.mark.asyncio
async def test_exec_which_found(tmp_path):
    chunks = []
    srv = _build_server(tmp_path, chunks)
    result = await srv._handlers["exec.which"]({"name": "sh"})
    assert result is not None
    assert "sh" in result


@pytest.mark.asyncio
async def test_exec_which_not_found(tmp_path):
    chunks = []
    srv = _build_server(tmp_path, chunks)
    result = await srv._handlers["exec.which"]({"name": "definitely_not_a_real_command_12345"})
    assert result is None
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-workspace-rpc/tests/test_service_exec.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement progress helper**

Create `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/progress.py`:

```python
"""Progress notification helper for streaming responses.

Handlers receive a progress_emitter callable they invoke with a channel
name (e.g. 'stdout') and a data dict. The framework forwards these as
JSON-RPC $/progress notifications back to the client.
"""

from collections.abc import Awaitable, Callable

ProgressEmitter = Callable[[str, dict], Awaitable[None]]
```

- [ ] **Step 4: Implement exec service**

Create `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/services/exec.py`:

```python
"""exec.* service — process execution with streaming stdout/stderr."""

import asyncio
import shutil
from pathlib import Path

from vystak_workspace_rpc.progress import ProgressEmitter


def register_exec(server, workspace_root: Path,
                  progress_emitter: ProgressEmitter) -> None:
    """Register exec.* handlers. progress_emitter forwards chunks to the
    JSON-RPC client as $/progress notifications."""
    root = Path(workspace_root).resolve()

    async def _stream_subprocess(argv: list[str], cwd: Path,
                                  env: dict | None, timeout_s: float | None) -> dict:
        import time

        start = time.time()
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def drain(reader, channel: str):
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    return
                await progress_emitter(channel, {"chunk": chunk.decode("utf-8",
                                                                       errors="replace")})

        drain_stdout = asyncio.create_task(drain(proc.stdout, "stdout"))
        drain_stderr = asyncio.create_task(drain(proc.stderr, "stderr"))

        try:
            if timeout_s is not None:
                await asyncio.wait_for(proc.wait(), timeout=timeout_s)
            else:
                await proc.wait()
        except asyncio.TimeoutError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            drain_stdout.cancel()
            drain_stderr.cancel()
            raise TimeoutError(f"Process exceeded timeout {timeout_s}s")

        await drain_stdout
        await drain_stderr
        duration_ms = int((time.time() - start) * 1000)
        return {"exit_code": proc.returncode, "duration_ms": duration_ms}

    async def run(params: dict) -> dict:
        cmd = params["cmd"]
        args = params.get("args", [])
        argv = [cmd] + list(args) if isinstance(cmd, str) else list(cmd)

        cwd_str = params.get("cwd", ".")
        cwd = (root / cwd_str).resolve()
        try:
            cwd.relative_to(root)
        except ValueError:
            raise ValueError(f"cwd '{cwd_str}' escapes workspace root") from None

        env = params.get("env")  # None = inherit
        timeout_s = params.get("timeout_s")
        return await _stream_subprocess(argv, cwd, env, timeout_s)

    async def shell(params: dict) -> dict:
        script = params["script"]
        cwd_str = params.get("cwd", ".")
        cwd = (root / cwd_str).resolve()
        try:
            cwd.relative_to(root)
        except ValueError:
            raise ValueError(f"cwd '{cwd_str}' escapes workspace root") from None
        timeout_s = params.get("timeout_s")
        return await _stream_subprocess(["sh", "-c", script], cwd, None, timeout_s)

    async def which(params: dict) -> str | None:
        found = shutil.which(params["name"])
        return found

    server.register("exec.run", run)
    server.register("exec.shell", shell)
    server.register("exec.which", which)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest packages/python/vystak-workspace-rpc/tests/test_service_exec.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/services/exec.py packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/progress.py packages/python/vystak-workspace-rpc/tests/test_service_exec.py
git commit -m "feat(workspace-rpc): exec.* service with streaming + timeout"
```

---

### Task 7: `git.*` service

**Files:**
- Create: `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/services/git.py`
- Create: `packages/python/vystak-workspace-rpc/tests/test_service_git.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-workspace-rpc/tests/test_service_git.py`:

```python
"""Tests for git.* service. Uses a real temp git repo."""

import asyncio
import subprocess

import pytest

from vystak_workspace_rpc.services.git import register_git


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)


def _build_server(workspace_root):
    from vystak_workspace_rpc.server import JsonRpcServer

    srv = JsonRpcServer()
    register_git(srv, workspace_root)
    return srv


@pytest.mark.asyncio
async def test_git_status_clean(tmp_path):
    _init_repo(tmp_path)
    srv = _build_server(tmp_path)
    result = await srv._handlers["git.status"]({})
    assert "branch" in result
    assert result["dirty"] is False
    assert result["staged"] == []
    assert result["unstaged"] == []
    assert result["untracked"] == []


@pytest.mark.asyncio
async def test_git_status_with_untracked_file(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "new.txt").write_text("hi")
    srv = _build_server(tmp_path)
    result = await srv._handlers["git.status"]({})
    assert result["dirty"] is True
    assert "new.txt" in result["untracked"]


@pytest.mark.asyncio
async def test_git_add_and_commit(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "f.txt").write_text("hello")
    srv = _build_server(tmp_path)
    await srv._handlers["git.add"]({"paths": ["f.txt"]})
    status = await srv._handlers["git.status"]({})
    assert "f.txt" in status["staged"]
    commit = await srv._handlers["git.commit"]({"message": "add f"})
    assert "sha" in commit
    assert len(commit["sha"]) >= 7


@pytest.mark.asyncio
async def test_git_log(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "first"], cwd=tmp_path, check=True)
    srv = _build_server(tmp_path)
    result = await srv._handlers["git.log"]({"limit": 10})
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["message"] == "first"
    assert "sha" in result[0]
    assert "author" in result[0]


@pytest.mark.asyncio
async def test_git_branch(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a").write_text("x")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    srv = _build_server(tmp_path)
    branch = await srv._handlers["git.branch"]({})
    # Default branch is either "main" or "master" depending on git version config
    assert branch in ("main", "master")


@pytest.mark.asyncio
async def test_git_not_a_repo_returns_error(tmp_path):
    # No git init
    srv = _build_server(tmp_path)
    with pytest.raises(RuntimeError, match="not a git repo"):
        await srv._handlers["git.status"]({})
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-workspace-rpc/tests/test_service_git.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement git service**

Create `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/services/git.py`:

```python
"""git.* service — thin wrapper over the git CLI."""

import asyncio
from pathlib import Path


def register_git(server, workspace_root: Path) -> None:
    root = Path(workspace_root).resolve()

    async def _git(args: list[str]) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=str(root),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode("utf-8"), stderr.decode("utf-8")

    async def _ensure_repo() -> None:
        code, _, _ = await _git(["rev-parse", "--is-inside-work-tree"])
        if code != 0:
            raise RuntimeError(f"{root} is not a git repo")

    async def status(params: dict) -> dict:
        await _ensure_repo()
        code, branch_out, _ = await _git(["rev-parse", "--abbrev-ref", "HEAD"])
        branch = branch_out.strip() if code == 0 else "HEAD"

        code, out, _ = await _git(["status", "--porcelain"])
        staged: list[str] = []
        unstaged: list[str] = []
        untracked: list[str] = []
        for line in out.splitlines():
            if not line:
                continue
            xy, _, path = line.partition(" ")
            # porcelain format: XY path, where X = staged state, Y = unstaged
            x = line[0]
            y = line[1]
            path = line[3:].strip()
            if x == "?" and y == "?":
                untracked.append(path)
            else:
                if x != " ":
                    staged.append(path)
                if y != " ":
                    unstaged.append(path)
        return {
            "branch": branch,
            "dirty": bool(staged or unstaged or untracked),
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
        }

    async def log(params: dict) -> list[dict]:
        await _ensure_repo()
        limit = params.get("limit", 10)
        path = params.get("path")
        args = ["log", f"-{limit}", "--pretty=format:%H%x00%an%x00%ad%x00%s",
                "--date=iso"]
        if path:
            args += ["--", path]
        code, out, err = await _git(args)
        if code != 0:
            raise RuntimeError(f"git log failed: {err}")
        result = []
        for line in out.splitlines():
            if not line:
                continue
            parts = line.split("\x00")
            if len(parts) < 4:
                continue
            result.append({
                "sha": parts[0],
                "author": parts[1],
                "date": parts[2],
                "message": parts[3],
            })
        return result

    async def diff(params: dict) -> str:
        await _ensure_repo()
        args = ["diff"]
        if params.get("staged"):
            args.append("--cached")
        if params.get("path"):
            args += ["--", params["path"]]
        code, out, err = await _git(args)
        if code != 0:
            raise RuntimeError(f"git diff failed: {err}")
        return out

    async def add(params: dict) -> None:
        await _ensure_repo()
        paths = params.get("paths", [])
        code, _, err = await _git(["add", *paths])
        if code != 0:
            raise RuntimeError(f"git add failed: {err}")
        return None

    async def commit(params: dict) -> dict:
        await _ensure_repo()
        args = ["commit", "-m", params["message"]]
        if params.get("author"):
            args += ["--author", params["author"]]
        code, _, err = await _git(args)
        if code != 0:
            raise RuntimeError(f"git commit failed: {err}")
        code, sha, _ = await _git(["rev-parse", "HEAD"])
        return {"sha": sha.strip()}

    async def branch(params: dict) -> str:
        await _ensure_repo()
        code, out, err = await _git(["rev-parse", "--abbrev-ref", "HEAD"])
        if code != 0:
            raise RuntimeError(f"git branch failed: {err}")
        return out.strip()

    server.register("git.status", status)
    server.register("git.log", log)
    server.register("git.diff", diff)
    server.register("git.add", add)
    server.register("git.commit", commit)
    server.register("git.branch", branch)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-workspace-rpc/tests/test_service_git.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/services/git.py packages/python/vystak-workspace-rpc/tests/test_service_git.py
git commit -m "feat(workspace-rpc): git.* service (status, log, diff, add, commit, branch)"
```

---

### Task 8: `tool.*` service — user-defined tools

**Files:**
- Create: `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/services/tool.py`
- Create: `packages/python/vystak-workspace-rpc/tests/test_service_tool.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-workspace-rpc/tests/test_service_tool.py`:

```python
"""Tests for tool.* service — user-defined tools discovery + invocation."""

import pytest

from vystak_workspace_rpc.services.tool import register_tool


def _build_server(tools_dir):
    from vystak_workspace_rpc.server import JsonRpcServer

    srv = JsonRpcServer()
    register_tool(srv, tools_dir)
    return srv


@pytest.mark.asyncio
async def test_tool_invoke_simple(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "greet.py").write_text(
        "def greet(name: str) -> str:\n    return f'hello {name}'\n"
    )
    srv = _build_server(tools)
    result = await srv._handlers["tool.invoke"]({
        "name": "greet", "args": {"name": "world"}
    })
    assert result == "hello world"


@pytest.mark.asyncio
async def test_tool_invoke_returns_dict(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "calc.py").write_text(
        "def calc(x: int, y: int) -> dict:\n    return {'sum': x+y, 'prod': x*y}\n"
    )
    srv = _build_server(tools)
    result = await srv._handlers["tool.invoke"]({
        "name": "calc", "args": {"x": 3, "y": 4}
    })
    assert result == {"sum": 7, "prod": 12}


@pytest.mark.asyncio
async def test_tool_invoke_unknown_raises(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    srv = _build_server(tools)
    with pytest.raises(FileNotFoundError, match="nope.py"):
        await srv._handlers["tool.invoke"]({"name": "nope", "args": {}})


@pytest.mark.asyncio
async def test_tool_list(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "a.py").write_text("def a(): return 1\n")
    (tools / "b.py").write_text("def b(): return 2\n")
    (tools / "__init__.py").write_text("")  # should not appear in list
    srv = _build_server(tools)
    result = await srv._handlers["tool.list"]({})
    names = {t["name"] for t in result}
    assert names == {"a", "b"}


@pytest.mark.asyncio
async def test_tool_invoke_tool_raising_propagates(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "oops.py").write_text(
        "def oops():\n    raise ValueError('user-error')\n"
    )
    srv = _build_server(tools)
    with pytest.raises(ValueError, match="user-error"):
        await srv._handlers["tool.invoke"]({"name": "oops", "args": {}})
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-workspace-rpc/tests/test_service_tool.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement tool service**

Create `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/services/tool.py`:

```python
"""tool.* service — discovers and invokes user-defined tools from tools/."""

import asyncio
import importlib.util
import inspect
import sys
from pathlib import Path


def register_tool(server, tools_dir: Path) -> None:
    """Tools are Python files in tools_dir/<name>.py containing a function
    named <name>. Invoked synchronously in-process."""
    tools_root = Path(tools_dir)

    async def invoke(params: dict) -> object:
        name = params["name"]
        args = params.get("args", {})
        tool_path = tools_root / f"{name}.py"
        if not tool_path.exists():
            raise FileNotFoundError(f"Tool {name}.py not found in {tools_root}")

        # Load module
        spec = importlib.util.spec_from_file_location(f"vystak_tool_{name}", tool_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"vystak_tool_{name}"] = module
        spec.loader.exec_module(module)

        fn = getattr(module, name, None)
        if fn is None:
            raise AttributeError(f"Tool {name}.py must define function '{name}'")

        # Call sync or async, returning Python value
        if inspect.iscoroutinefunction(fn):
            return await fn(**args)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(**args))

    async def list_tools(params: dict) -> list[dict]:
        if not tools_root.exists():
            return []
        result = []
        for entry in sorted(tools_root.iterdir()):
            if entry.suffix != ".py":
                continue
            if entry.stem.startswith("_"):
                continue
            result.append({"name": entry.stem, "path": str(entry.relative_to(tools_root))})
        return result

    server.register("tool.invoke", invoke)
    server.register("tool.list", list_tools)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-workspace-rpc/tests/test_service_tool.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/services/tool.py packages/python/vystak-workspace-rpc/tests/test_service_tool.py
git commit -m "feat(workspace-rpc): tool.* service for user-defined tools"
```

---

### Task 9: Subsystem entrypoint — `__main__.py` wiring all services

**Files:**
- Create: `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/__main__.py`
- Create: `packages/python/vystak-workspace-rpc/tests/test_main.py`

- [ ] **Step 1: Write failing test**

Create `packages/python/vystak-workspace-rpc/tests/test_main.py`:

```python
"""Smoke test for __main__ wiring all services."""

import pytest

from vystak_workspace_rpc.__main__ import build_server


def test_build_server_registers_all_services(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    srv = build_server(workspace_root=tmp_path, tools_dir=tools_dir)
    registered = set(srv._handlers.keys())
    # fs.*
    assert "fs.readFile" in registered
    assert "fs.writeFile" in registered
    # exec.*
    assert "exec.run" in registered
    assert "exec.shell" in registered
    # git.*
    assert "git.status" in registered
    # tool.*
    assert "tool.invoke" in registered
    assert "tool.list" in registered
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-workspace-rpc/tests/test_main.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `__main__.py`**

Create `packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/__main__.py`:

```python
"""Entry point. sshd runs this as the `vystak-rpc` subsystem.

Reads WORKSPACE_ROOT and TOOLS_DIR from env; defaults to /workspace and
/workspace/tools. Builds a JsonRpcServer with all services registered,
runs it against stdin/stdout.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from vystak_workspace_rpc.server import JsonRpcServer, run_stdio
from vystak_workspace_rpc.services.exec import register_exec
from vystak_workspace_rpc.services.fs import register_fs
from vystak_workspace_rpc.services.git import register_git
from vystak_workspace_rpc.services.tool import register_tool


def build_server(workspace_root: Path, tools_dir: Path) -> JsonRpcServer:
    """Build a JsonRpcServer with all services registered."""
    srv = JsonRpcServer()

    async def progress_emitter(channel: str, data: dict) -> None:
        """Forward to stdout as a JSON-RPC $/progress notification."""
        note = {
            "jsonrpc": "2.0",
            "method": "$/progress",
            "params": {"channel": channel, **data},
        }
        sys.stdout.write(json.dumps(note) + "\n")
        sys.stdout.flush()

    register_fs(srv, workspace_root)
    register_exec(srv, workspace_root, progress_emitter=progress_emitter)
    register_git(srv, workspace_root)
    register_tool(srv, tools_dir)
    return srv


def main() -> None:
    workspace_root = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))
    tools_dir = Path(os.environ.get("TOOLS_DIR", str(workspace_root / "tools")))
    srv = build_server(workspace_root, tools_dir)
    asyncio.run(run_stdio(srv))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test**

Run: `uv run pytest packages/python/vystak-workspace-rpc/tests/test_main.py -v`
Expected: PASS.

- [ ] **Step 5: Full package test**

Run: `uv run pytest packages/python/vystak-workspace-rpc/tests/ -v`
Expected: PASS (all tests from Tasks 4-9 green).

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-workspace-rpc/src/vystak_workspace_rpc/__main__.py packages/python/vystak-workspace-rpc/tests/test_main.py
git commit -m "feat(workspace-rpc): __main__ entrypoint wires all four services"
```

---

## Phase 3 — Docker workspace deployment

### Task 10: `WorkspaceSshKeygenNode` — generate + push SSH keys to Vault

**Files:**
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace_ssh_keygen.py`
- Create: `packages/python/vystak-provider-docker/tests/test_node_workspace_ssh_keygen.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-provider-docker/tests/test_node_workspace_ssh_keygen.py`:

```python
"""Tests for WorkspaceSshKeygenNode — generates SSH keypairs and pushes to Vault."""

from unittest.mock import MagicMock

import pytest

from vystak_provider_docker.nodes.workspace_ssh_keygen import WorkspaceSshKeygenNode


def test_generates_and_pushes_when_missing_from_vault():
    vault_client = MagicMock()
    vault_client.kv_get.return_value = None  # missing
    docker_client = MagicMock()

    node = WorkspaceSshKeygenNode(
        vault_client=vault_client,
        docker_client=docker_client,
        agent_name="assistant",
    )
    result = node.provision(context={})
    # Four kv_put calls: client-key, host-key, client-key-pub, host-key-pub
    assert vault_client.kv_put.call_count == 4
    paths_put = {c.args[0] for c in vault_client.kv_put.call_args_list}
    assert paths_put == {
        "_vystak/workspace-ssh/assistant/client-key",
        "_vystak/workspace-ssh/assistant/host-key",
        "_vystak/workspace-ssh/assistant/client-key-pub",
        "_vystak/workspace-ssh/assistant/host-key-pub",
    }
    assert result.success is True


def test_skips_when_all_four_keys_present():
    vault_client = MagicMock()
    vault_client.kv_get.return_value = "existing-value"  # present
    docker_client = MagicMock()

    node = WorkspaceSshKeygenNode(
        vault_client=vault_client,
        docker_client=docker_client,
        agent_name="assistant",
    )
    node.provision(context={})
    vault_client.kv_put.assert_not_called()


def test_regenerates_when_some_missing():
    vault_client = MagicMock()
    # Only client-key exists, others missing
    def kv_get_side(name):
        return "val" if name.endswith("/client-key") else None

    vault_client.kv_get.side_effect = kv_get_side
    docker_client = MagicMock()

    node = WorkspaceSshKeygenNode(
        vault_client=vault_client,
        docker_client=docker_client,
        agent_name="assistant",
    )
    node.provision(context={})
    # Any missing => regenerate ALL four (keypair integrity)
    assert vault_client.kv_put.call_count == 4
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_workspace_ssh_keygen.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace_ssh_keygen.py`:

```python
"""WorkspaceSshKeygenNode — generates SSH keypairs via throwaway alpine,
pushes the four pieces to Vault under _vystak/workspace-ssh/<agent>/*."""

from vystak.provisioning.node import Provisionable, ProvisionResult


class WorkspaceSshKeygenNode(Provisionable):
    """One per agent with a workspace. Runs after Vault KV setup."""

    def __init__(self, *, vault_client, docker_client, agent_name: str):
        self._vault = vault_client
        self._docker = docker_client
        self._agent_name = agent_name

    @property
    def name(self) -> str:
        return f"workspace-ssh-keygen:{self._agent_name}"

    @property
    def depends_on(self) -> list[str]:
        return ["hashi-vault:kv-setup"]

    def _vault_path(self, key: str) -> str:
        return f"_vystak/workspace-ssh/{self._agent_name}/{key}"

    def provision(self, context: dict) -> ProvisionResult:
        key_names = ["client-key", "host-key", "client-key-pub", "host-key-pub"]
        have = all(self._vault.kv_get(self._vault_path(k)) is not None for k in key_names)
        if have:
            return ProvisionResult(
                name=self.name, success=True, info={"regenerated": False}
            )

        # Generate both keypairs inside a throwaway alpine, capture stdout.
        # Script writes four files to /out/, we read them back via docker exec /
        # docker cp. Simpler: use a bind mount to a host tmpdir.
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            script = (
                "apk add --no-cache openssh-keygen > /dev/null 2>&1 || "
                "apk add --no-cache openssh > /dev/null 2>&1;"
                "ssh-keygen -t ed25519 -N '' -f /out/client-key -q;"
                "ssh-keygen -t ed25519 -N '' -f /out/host-key -q;"
                "chmod 644 /out/*"
            )
            self._docker.containers.run(
                image="alpine:3.19",
                command=["sh", "-c", script],
                volumes={td: {"bind": "/out", "mode": "rw"}},
                remove=True,
            )
            import pathlib
            out = pathlib.Path(td)
            client_priv = (out / "client-key").read_text()
            client_pub = (out / "client-key.pub").read_text().strip()
            host_priv = (out / "host-key").read_text()
            host_pub = (out / "host-key.pub").read_text().strip()

        self._vault.kv_put(self._vault_path("client-key"), client_priv)
        self._vault.kv_put(self._vault_path("host-key"), host_priv)
        self._vault.kv_put(self._vault_path("client-key-pub"), client_pub)
        self._vault.kv_put(self._vault_path("host-key-pub"), host_pub)

        return ProvisionResult(
            name=self.name, success=True, info={"regenerated": True}
        )

    def destroy(self) -> None:
        # Keys preserved in Vault by default, same as user secrets.
        pass
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_workspace_ssh_keygen.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace_ssh_keygen.py packages/python/vystak-provider-docker/tests/test_node_workspace_ssh_keygen.py
git commit -m "feat(provider-docker): WorkspaceSshKeygenNode — generate + push SSH keys to Vault"
```

---

### Task 11: Extend Vault Agent HCL generator to emit SSH file templates

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py`
- Test: `packages/python/vystak-provider-docker/tests/test_templates.py` (extend)

- [ ] **Step 1: Write failing test**

Append to `packages/python/vystak-provider-docker/tests/test_templates.py`:

```python
def test_agent_hcl_includes_workspace_ssh_templates():
    from vystak_provider_docker.templates import generate_agent_hcl_with_workspace_ssh

    hcl = generate_agent_hcl_with_workspace_ssh(
        vault_address="http://vystak-vault:8200",
        secret_names=["ANTHROPIC_API_KEY"],
        agent_name="assistant",
        role="agent",  # client side — renders id_ed25519 + known_hosts
    )
    # Normal secrets.env template still present
    assert "/shared/secrets.env" in hcl
    # Agent-side SSH files
    assert "/vystak/ssh/id_ed25519" in hcl
    assert "/vystak/ssh/known_hosts" in hcl
    assert '0400' in hcl  # private key perms
    # Private-key template reads client-key
    assert "_vystak/workspace-ssh/assistant/client-key" in hcl
    # known_hosts reads host-key-pub
    assert "_vystak/workspace-ssh/assistant/host-key-pub" in hcl
    # Format: "vystak-assistant-workspace ssh-ed25519 ..."
    assert "vystak-assistant-workspace" in hcl


def test_workspace_hcl_includes_workspace_ssh_templates():
    from vystak_provider_docker.templates import generate_agent_hcl_with_workspace_ssh

    hcl = generate_agent_hcl_with_workspace_ssh(
        vault_address="http://vystak-vault:8200",
        secret_names=["STRIPE_API_KEY"],
        agent_name="assistant",
        role="workspace",  # server side — renders host key + authorized_keys
    )
    assert "/shared/ssh_host_ed25519_key" in hcl
    assert "/shared/authorized_keys_vystak-agent" in hcl
    assert '0600' in hcl  # host private key perms
    assert "_vystak/workspace-ssh/assistant/host-key" in hcl
    assert "_vystak/workspace-ssh/assistant/client-key-pub" in hcl
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_templates.py -v -k workspace_ssh`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py`, add:

```python
def generate_agent_hcl_with_workspace_ssh(
    *,
    vault_address: str,
    secret_names: list[str],
    agent_name: str,
    role: str,  # "agent" or "workspace"
) -> str:
    """Extended Vault Agent HCL: user-secret env template + SSH key file
    templates for the agent↔workspace channel."""
    base = generate_agent_hcl(
        vault_address=vault_address, secret_names=secret_names
    )

    if role == "agent":
        ssh_templates = f"""
template {{
  destination = "/vystak/ssh/id_ed25519"
  perms       = "0400"
  contents    = <<-EOT
    {{{{- with secret "secret/data/_vystak/workspace-ssh/{agent_name}/client-key" }}}}{{{{ .Data.data.value }}}}{{{{- end }}}}
  EOT
}}

template {{
  destination = "/vystak/ssh/known_hosts"
  perms       = "0444"
  contents    = <<-EOT
    vystak-{agent_name}-workspace {{{{- with secret "secret/data/_vystak/workspace-ssh/{agent_name}/host-key-pub" }}}} {{{{ .Data.data.value }}}}{{{{- end }}}}
  EOT
}}
"""
    elif role == "workspace":
        ssh_templates = f"""
template {{
  destination = "/shared/ssh_host_ed25519_key"
  perms       = "0600"
  contents    = <<-EOT
    {{{{- with secret "secret/data/_vystak/workspace-ssh/{agent_name}/host-key" }}}}{{{{ .Data.data.value }}}}{{{{- end }}}}
  EOT
}}

template {{
  destination = "/shared/authorized_keys_vystak-agent"
  perms       = "0444"
  contents    = <<-EOT
    {{{{- with secret "secret/data/_vystak/workspace-ssh/{agent_name}/client-key-pub" }}}}{{{{ .Data.data.value }}}}{{{{- end }}}}
  EOT
}}
"""
    else:
        raise ValueError(f"role must be 'agent' or 'workspace', got {role!r}")

    return base + ssh_templates
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_templates.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py packages/python/vystak-provider-docker/tests/test_templates.py
git commit -m "feat(provider-docker): generate_agent_hcl_with_workspace_ssh emits file templates"
```

---

### Task 12: Workspace Dockerfile generator

**Files:**
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/workspace_image.py`
- Create: `packages/python/vystak-provider-docker/tests/test_workspace_image.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-provider-docker/tests/test_workspace_image.py`:

```python
"""Tests for workspace Dockerfile generation."""

from vystak_provider_docker.workspace_image import (
    generate_workspace_dockerfile,
    detect_tool_deps_manager,
)


def test_generates_minimal_dockerfile():
    df = generate_workspace_dockerfile(
        image="python:3.12-slim",
        provision=[],
        copy={},
        tool_deps_manager=None,
    )
    assert df.startswith("FROM python:3.12-slim")
    assert "openssh-server" in df  # vystak appendix
    assert "vystak-workspace-rpc" in df
    assert "ENTRYPOINT" in df


def test_includes_provision_run_layers():
    df = generate_workspace_dockerfile(
        image="python:3.12-slim",
        provision=["apt-get update", "pip install ruff"],
        copy={},
        tool_deps_manager=None,
    )
    assert "RUN apt-get update" in df
    assert "RUN pip install ruff" in df


def test_includes_copy_statements():
    df = generate_workspace_dockerfile(
        image="python:3.12-slim",
        provision=[],
        copy={"./config.toml": "/workspace/config.toml"},
        tool_deps_manager=None,
    )
    assert "COPY ./config.toml /workspace/config.toml" in df


def test_pip_auto_detected_for_python_image():
    assert detect_tool_deps_manager("python:3.12-slim") == "pip"
    assert detect_tool_deps_manager("python:3.11") == "pip"
    assert detect_tool_deps_manager("python:3.12-alpine") == "pip"


def test_npm_auto_detected_for_node_image():
    assert detect_tool_deps_manager("node:20") == "npm"
    assert detect_tool_deps_manager("node:22-alpine") == "npm"


def test_none_when_unknown_base():
    assert detect_tool_deps_manager("ubuntu:24.04") is None
    assert detect_tool_deps_manager("rust:1.80") is None


def test_explicit_tool_deps_manager_overrides_detection():
    df = generate_workspace_dockerfile(
        image="ubuntu:24.04",
        provision=["apt-get install -y python3 python3-pip"],
        copy={},
        tool_deps_manager="pip",
    )
    assert "pip install" in df


def test_tool_deps_none_skips_install():
    df = generate_workspace_dockerfile(
        image="python:3.12-slim",
        provision=[],
        copy={},
        tool_deps_manager="none",
    )
    assert "pip install -r tools/requirements.txt" not in df
    assert "npm install" not in df
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_workspace_image.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `packages/python/vystak-provider-docker/src/vystak_provider_docker/workspace_image.py`:

```python
"""Dockerfile generator for workspace containers.

Takes user schema fields (image, provision, copy, tool_deps_manager),
produces the full Dockerfile string. Vystak appendix handles openssh,
vystak-workspace-rpc installation, and entrypoint shim.
"""


def detect_tool_deps_manager(image: str) -> str | None:
    """Infer package manager from base image name.

    Heuristic: look for 'python' or 'node' anywhere in the image name
    (covers python:3.12-slim, python:3.12-alpine, cimg/python:3.12, etc.).
    """
    lower = image.lower()
    if "python" in lower:
        return "pip"
    if "node" in lower:
        return "npm"
    return None


def generate_workspace_dockerfile(
    *,
    image: str,
    provision: list[str],
    copy: dict[str, str],
    tool_deps_manager: str | None,
) -> str:
    """Build the workspace Dockerfile. User layers first, vystak layers last."""
    effective_manager = tool_deps_manager
    if effective_manager is None:
        effective_manager = detect_tool_deps_manager(image)

    lines = [f"FROM {image}", "WORKDIR /workspace", ""]

    for cmd in provision:
        lines.append(f"RUN {cmd}")
    if provision:
        lines.append("")

    for src, dst in copy.items():
        lines.append(f"COPY {src} {dst}")
    if copy:
        lines.append("")

    # --- Vystak appendix ---
    lines.append("# --- Vystak appendix (do not edit) ---")
    # openssh-server + vystak-workspace-rpc (installed via pip from bundled source)
    lines.append(
        "RUN apt-get update && apt-get install -y --no-install-recommends "
        "openssh-server git ca-certificates python3 python3-pip && "
        "rm -rf /var/lib/apt/lists/* && "
        "mkdir -p /var/run/sshd /vystak/ssh /shared"
    )
    # Users
    lines.append(
        "RUN useradd -m -u 100 vystak-agent && "
        "useradd -m -u 101 vystak-dev && "
        "chown -R vystak-agent /workspace"
    )
    # sshd config
    lines.append("COPY vystak-sshd.conf /etc/ssh/sshd_config.d/50-vystak.conf")
    # vystak-workspace-rpc source
    lines.append("COPY vystak_workspace_rpc /opt/vystak_workspace_rpc")
    lines.append(
        "RUN pip3 install --break-system-packages /opt/vystak_workspace_rpc && "
        "ln -s $(which vystak-workspace-rpc 2>/dev/null || "
        "echo /usr/local/bin/python3) /usr/local/bin/vystak-workspace-rpc && "
        "printf '#!/bin/sh\\nexec python3 -m vystak_workspace_rpc \"$@\"\\n' "
        "> /usr/local/bin/vystak-workspace-rpc && "
        "chmod +x /usr/local/bin/vystak-workspace-rpc"
    )
    # Tools directory
    lines.append("COPY tools/ /workspace/tools/")
    # Tool deps install
    if effective_manager == "pip":
        lines.append(
            "RUN test -f /workspace/tools/requirements.txt && "
            "pip3 install --break-system-packages -r /workspace/tools/requirements.txt "
            "|| true"
        )
    elif effective_manager == "npm":
        lines.append(
            "RUN test -f /workspace/tools/package.json && "
            "(cd /workspace/tools && npm install) || true"
        )
    # Entrypoint shim (same pattern as v1 Hashi)
    lines.append("COPY entrypoint-shim.sh /vystak/entrypoint-shim.sh")
    lines.append("RUN chmod +x /vystak/entrypoint-shim.sh")
    lines.append('ENTRYPOINT ["/vystak/entrypoint-shim.sh"]')
    lines.append('CMD ["/usr/sbin/sshd", "-D", "-e"]')

    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_workspace_image.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/workspace_image.py packages/python/vystak-provider-docker/tests/test_workspace_image.py
git commit -m "feat(provider-docker): workspace Dockerfile generator"
```

---

### Task 13: `DockerWorkspaceNode` — build + run workspace container

**Files:**
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace.py`
- Create: `packages/python/vystak-provider-docker/tests/test_node_workspace.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-provider-docker/tests/test_node_workspace.py`:

```python
"""Tests for DockerWorkspaceNode."""

from unittest.mock import MagicMock, patch

import pytest

from vystak.schema.workspace import Workspace
from vystak_provider_docker.nodes.workspace import DockerWorkspaceNode


def _workspace(**kwargs):
    defaults = {"name": "dev", "image": "python:3.12-slim", "provision": []}
    defaults.update(kwargs)
    return Workspace(**defaults)


def test_builds_image_runs_container(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docker_client = MagicMock()
    import docker.errors

    docker_client.containers.get.side_effect = docker.errors.NotFound("nope")

    node = DockerWorkspaceNode(
        client=docker_client,
        agent_name="assistant",
        workspace=_workspace(),
        tools_dir=tmp_path / "tools",
    )
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "sample.py").write_text("def sample(): return 1\n")

    context = {"network": MagicMock(info={"network": MagicMock(name="vystak-net")})}
    result = node.provision(context=context)

    assert docker_client.images.build.called
    assert docker_client.containers.run.called
    run_kwargs = docker_client.containers.run.call_args.kwargs
    assert run_kwargs["name"] == "vystak-assistant-workspace"
    # /shared mount (vault agent secret+ssh volume; wired from a sibling node)
    # /workspace data volume
    volumes = run_kwargs["volumes"]
    assert "vystak-assistant-workspace-data" in volumes
    assert result.info["container_name"] == "vystak-assistant-workspace"


def test_persistence_ephemeral_uses_tmpfs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docker_client = MagicMock()
    import docker.errors

    docker_client.containers.get.side_effect = docker.errors.NotFound("nope")

    (tmp_path / "tools").mkdir()
    node = DockerWorkspaceNode(
        client=docker_client,
        agent_name="assistant",
        workspace=_workspace(persistence="ephemeral"),
        tools_dir=tmp_path / "tools",
    )
    context = {"network": MagicMock(info={"network": MagicMock(name="vystak-net")})}
    node.provision(context=context)
    run_kwargs = docker_client.containers.run.call_args.kwargs
    # No named volume for data; uses tmpfs
    assert "vystak-assistant-workspace-data" not in run_kwargs.get("volumes", {})
    assert run_kwargs.get("tmpfs", {}).get("/workspace") is not None


def test_persistence_bind_uses_host_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docker_client = MagicMock()
    import docker.errors

    docker_client.containers.get.side_effect = docker.errors.NotFound("nope")

    host_proj = tmp_path / "my_project"
    host_proj.mkdir()
    (tmp_path / "tools").mkdir()
    node = DockerWorkspaceNode(
        client=docker_client,
        agent_name="assistant",
        workspace=_workspace(persistence="bind", path=str(host_proj)),
        tools_dir=tmp_path / "tools",
    )
    context = {"network": MagicMock(info={"network": MagicMock(name="vystak-net")})}
    node.provision(context=context)
    run_kwargs = docker_client.containers.run.call_args.kwargs
    volumes = run_kwargs["volumes"]
    assert str(host_proj.resolve()) in volumes
    assert volumes[str(host_proj.resolve())]["bind"] == "/workspace"
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_workspace.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace.py`:

```python
"""DockerWorkspaceNode — builds and runs the workspace container."""

import shutil
from pathlib import Path

import docker.errors
from vystak.provisioning.node import Provisionable, ProvisionResult
from vystak.schema.workspace import Workspace

from vystak_provider_docker.workspace_image import generate_workspace_dockerfile


class DockerWorkspaceNode(Provisionable):
    """Builds the workspace image, runs the container."""

    def __init__(
        self,
        *,
        client,
        agent_name: str,
        workspace: Workspace,
        tools_dir: Path,
    ):
        self._client = client
        self._agent_name = agent_name
        self._workspace = workspace
        self._tools_dir = Path(tools_dir)

    @property
    def container_name(self) -> str:
        return f"vystak-{self._agent_name}-workspace"

    @property
    def data_volume_name(self) -> str:
        return f"vystak-{self._agent_name}-workspace-data"

    @property
    def secrets_volume_name(self) -> str:
        # The vault-agent sidecar for the workspace principal writes here.
        return f"vystak-{self._agent_name}-workspace-secrets"

    @property
    def name(self) -> str:
        return f"workspace:{self._agent_name}"

    @property
    def depends_on(self) -> list[str]:
        # Depends on the workspace-principal vault-agent sidecar and SSH keygen.
        return [
            f"vault-agent:{self._agent_name}-workspace",
            f"workspace-ssh-keygen:{self._agent_name}",
        ]

    def provision(self, context: dict) -> ProvisionResult:
        ws = self._workspace
        build_dir = Path(".vystak") / f"{self._agent_name}-workspace"
        build_dir.mkdir(parents=True, exist_ok=True)

        # Generate Dockerfile (unless user provided custom)
        if ws.dockerfile:
            dockerfile_path = Path(ws.dockerfile).resolve()
            shutil.copy(dockerfile_path, build_dir / "Dockerfile")
        else:
            df = generate_workspace_dockerfile(
                image=ws.image,
                provision=ws.provision,
                copy=ws.copy,
                tool_deps_manager=ws.tool_deps_manager,
            )
            (build_dir / "Dockerfile").write_text(df)

        # sshd config (static)
        sshd_conf = self._generate_sshd_config(ws)
        (build_dir / "vystak-sshd.conf").write_text(sshd_conf)

        # entrypoint-shim (reuse v1 pattern)
        from vystak_provider_docker.templates import generate_entrypoint_shim
        (build_dir / "entrypoint-shim.sh").write_text(generate_entrypoint_shim())

        # Copy vystak_workspace_rpc source into build context
        import vystak_workspace_rpc
        src = Path(vystak_workspace_rpc.__file__).parent
        dst = build_dir / "vystak_workspace_rpc"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        # Also ship a minimal pyproject so pip install works
        (build_dir / "setup.py").write_text(
            "from setuptools import setup, find_packages\n"
            "setup(name='vystak-workspace-rpc', version='0.1.0',\n"
            "      packages=find_packages())\n"
        )

        # Tools dir
        tools_dst = build_dir / "tools"
        if tools_dst.exists():
            shutil.rmtree(tools_dst)
        if self._tools_dir.exists():
            shutil.copytree(self._tools_dir, tools_dst)
        else:
            tools_dst.mkdir()

        # Human authorized_keys if ssh=True
        if ws.ssh:
            keys_content = "\n".join(ws.ssh_authorized_keys)
            if ws.ssh_authorized_keys_file:
                keys_content += "\n" + Path(ws.ssh_authorized_keys_file).read_text()
            (build_dir / "human-authorized_keys").write_text(keys_content)

        # Build
        image_tag = f"{self.container_name}:latest"
        self._client.images.build(path=str(build_dir), tag=image_tag, rm=True)

        # Run
        network = context["network"].info["network"]
        # Stop existing
        try:
            existing = self._client.containers.get(self.container_name)
            existing.stop()
            existing.remove()
        except docker.errors.NotFound:
            pass

        volumes: dict = {
            self.secrets_volume_name: {"bind": "/shared", "mode": "ro"},
        }
        tmpfs: dict = {}
        if ws.persistence == "volume":
            # Ensure data volume exists
            try:
                self._client.volumes.get(self.data_volume_name)
            except docker.errors.NotFound:
                self._client.volumes.create(name=self.data_volume_name)
            volumes[self.data_volume_name] = {"bind": "/workspace", "mode": "rw"}
        elif ws.persistence == "bind":
            host_path = str(Path(ws.path).expanduser().resolve())
            volumes[host_path] = {"bind": "/workspace", "mode": "rw"}
        elif ws.persistence == "ephemeral":
            tmpfs["/workspace"] = "rw,size=512m"

        ports = {}
        if ws.ssh and ws.ssh_host_port:
            ports["22/tcp"] = ws.ssh_host_port
        elif ws.ssh:
            ports["22/tcp"] = None  # Docker auto-allocates

        self._client.containers.run(
            image=image_tag,
            name=self.container_name,
            detach=True,
            network=network.name,
            volumes=volumes,
            tmpfs=tmpfs,
            ports=ports,
            labels={
                "vystak.workspace": self._agent_name,
                "vystak.workspace.persistence": ws.persistence,
            },
        )

        container = self._client.containers.get(self.container_name)
        info = {
            "container_name": self.container_name,
            "workspace_host": self.container_name,  # internal DNS
            "data_volume_name": (
                self.data_volume_name if ws.persistence == "volume" else None
            ),
        }
        if ws.ssh:
            # Read the host port assigned by Docker
            port_info = container.ports.get("22/tcp")
            if port_info:
                info["ssh_host_port"] = port_info[0]["HostPort"]

        return ProvisionResult(name=self.name, success=True, info=info)

    def _generate_sshd_config(self, ws: Workspace) -> str:
        lines = [
            "HostKey /shared/ssh_host_ed25519_key",
            "Subsystem vystak-rpc /usr/local/bin/vystak-workspace-rpc",
            "PermitRootLogin no",
            "PasswordAuthentication no",
            "PubkeyAuthentication yes",
            "ClientAliveInterval 60",
            "ClientAliveCountMax 3",
            "",
            "Match User vystak-agent",
            "    AuthenticationMethods publickey",
            "    AuthorizedKeysFile /shared/authorized_keys_vystak-agent",
            "    ForceCommand /usr/local/bin/vystak-workspace-rpc",
            "    PermitTTY no",
            "    X11Forwarding no",
            "    AllowTcpForwarding yes",
            "    GatewayPorts no",
            "    PermitOpen any",
        ]
        if ws.ssh:
            lines += [
                "",
                "Match User vystak-dev",
                "    AuthenticationMethods publickey",
                "    AuthorizedKeysFile /etc/vystak-ssh/human-authorized_keys",
                "    X11Forwarding no",
                "    PermitTTY yes",
            ]
        return "\n".join(lines) + "\n"

    def destroy(self) -> None:
        try:
            c = self._client.containers.get(self.container_name)
            c.stop()
            c.remove()
        except docker.errors.NotFound:
            pass
        # Data volume preserved by default; destroy() only called on
        # --delete-workspace-data flag.
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_workspace.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace.py packages/python/vystak-provider-docker/tests/test_node_workspace.py
git commit -m "feat(provider-docker): DockerWorkspaceNode — build + run workspace container"
```

---

## Phase 4 — Docker agent wiring

### Task 14: `set_workspace_context` on DockerAgentNode + agent Dockerfile wiring

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py`
- Test: `packages/python/vystak-provider-docker/tests/test_agent_workspace.py` (new)

- [ ] **Step 1: Write failing test**

Create `packages/python/vystak-provider-docker/tests/test_agent_workspace.py`:

```python
"""Tests that DockerAgentNode gets workspace context wired correctly."""

from unittest.mock import MagicMock, patch
from pathlib import Path

from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider

from vystak_provider_docker.nodes.agent import DockerAgentNode


def _agent_fixture():
    docker_p = Provider(name="docker", type="docker")
    platform = Platform(name="local", type="docker", provider=docker_p)
    anthropic = Provider(name="anthropic", type="anthropic")
    return Agent(
        name="assistant",
        model=Model(name="m", provider=anthropic, model_name="claude-sonnet-4-20250514"),
        platform=platform,
    )


def test_set_workspace_context_populates_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    import docker.errors
    client.containers.get.side_effect = docker.errors.NotFound("nope")

    from vystak.providers.base import GeneratedCode, DeployPlan

    gc = GeneratedCode(files={"server.py": "", "requirements.txt": ""},
                       entrypoint="server.py")
    node = DockerAgentNode(
        client=client, agent=_agent_fixture(),
        generated_code=gc,
        plan=DeployPlan(agent_name="assistant", current_hash=None, target_hash="h",
                        actions=[], changes={}),
    )
    node.set_workspace_context(workspace_host="vystak-assistant-workspace")
    with patch("vystak_provider_docker.nodes.agent.shutil"), \
         patch("vystak_provider_docker.nodes.agent.vystak"), \
         patch("vystak_provider_docker.nodes.agent.vystak_transport_http"), \
         patch("vystak_provider_docker.nodes.agent.vystak_transport_nats"):
        node.provision(context={"network": MagicMock(info={"network": MagicMock(name="n")})})

    run_kwargs = client.containers.run.call_args.kwargs
    env = run_kwargs.get("environment", {})
    assert env.get("VYSTAK_WORKSPACE_HOST") == "vystak-assistant-workspace"
    # SSH volume mount for agent-side keys (written by agent's vault-agent sidecar)
    volumes = run_kwargs.get("volumes", {})
    assert any(v.get("bind") == "/vystak/ssh" and v.get("mode") == "ro"
               for v in volumes.values())
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_agent_workspace.py -v`
Expected: FAIL — `set_workspace_context` doesn't exist.

- [ ] **Step 3: Modify `nodes/agent.py`**

In `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py`:

Add field init in `__init__`:
```python
self._workspace_host: str | None = None
```

Add method:
```python
def set_workspace_context(self, *, workspace_host: str) -> None:
    """Declare that the agent should RPC to this workspace host over SSH.
    Env var VYSTAK_WORKSPACE_HOST is set; vystak-agent-secrets volume
    picks up /vystak/ssh/ files rendered by the agent's vault-agent sidecar."""
    self._workspace_host = workspace_host
```

In `provision()`, extend env and volumes when `_workspace_host` is set:
```python
if self._workspace_host:
    env_vars["VYSTAK_WORKSPACE_HOST"] = self._workspace_host
    # The agent's vault-agent sidecar renders id_ed25519 and known_hosts
    # into the agent-secrets volume (agent principal's /shared volume),
    # but we need them mounted at /vystak/ssh in the agent container.
    # They're rendered at /shared/ by the vault-agent and we mount the same
    # volume at /vystak/ssh here.
    volumes[f"vystak-{self._agent.name}-agent-secrets"] = {
        "bind": "/vystak/ssh",
        "mode": "ro",
    }
```

**Important — note on this mapping:** the vault-agent for the agent principal renders `/vystak/ssh/id_ed25519` and `/vystak/ssh/known_hosts` via template destinations (per Task 11). The secrets volume is mounted at `/shared` in the agent container. Since we want `/vystak/ssh/*` paths visible in the agent container, we either mount the same volume at both paths OR change the vault-agent destinations. **Chosen**: update Task 11's agent-role HCL to target `/shared/ssh/id_ed25519` and `/shared/ssh/known_hosts`, then mount the `vystak-<agent>-agent-secrets` volume at `/shared` in the agent container (as today), and symlink `/vystak/ssh` → `/shared/ssh` in the agent Dockerfile.

Apply the Dockerfile change: in the agent's Dockerfile generation, add:
```python
# After entrypoint-shim lines:
dockerfile_content += "RUN mkdir -p /vystak && ln -s /shared/ssh /vystak/ssh\n"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_agent_workspace.py -v`
Expected: PASS.

Also: `uv run pytest packages/python/vystak-provider-docker/tests/ -v -k "not integration"`
Expected: PASS (no regressions from earlier tests).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py packages/python/vystak-provider-docker/tests/test_agent_workspace.py
git commit -m "feat(provider-docker): DockerAgentNode.set_workspace_context wires SSH volume + env"
```

Note: this task's Task-11 HCL-destination-path harmonization is done in Task 11's impl; no separate task needed. Ensure when implementing Task 11 that the agent-role template destinations are `/shared/ssh/id_ed25519` and `/shared/ssh/known_hosts`.

---

### Task 15: Wire workspace into DockerProvider.apply graph

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py`
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/__init__.py`
- Test: extend `packages/python/vystak-provider-docker/tests/test_provider.py`

- [ ] **Step 1: Update nodes export**

In `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/__init__.py`, add:

```python
from vystak_provider_docker.nodes.workspace import DockerWorkspaceNode
from vystak_provider_docker.nodes.workspace_ssh_keygen import WorkspaceSshKeygenNode

__all__ = [
    # ... existing ...
    "DockerWorkspaceNode",
    "WorkspaceSshKeygenNode",
]
```

- [ ] **Step 2: Write failing test**

Append to `packages/python/vystak-provider-docker/tests/test_provider.py`:

```python
def test_docker_provider_adds_workspace_node_when_workspace_declared(make_agent_fixture):
    """When agent has a workspace AND vault is declared, graph contains
    workspace + SSH keygen nodes."""
    from vystak_provider_docker.provider import DockerProvider
    from vystak.schema.vault import Vault
    from vystak.schema.workspace import Workspace
    from vystak.schema.common import VaultType, VaultMode
    from vystak.schema.provider import Provider

    provider = DockerProvider()
    provider.set_vault(
        Vault(
            name="v",
            provider=Provider(name="docker", type="docker"),
            type=VaultType.VAULT,
            mode=VaultMode.DEPLOY,
            config={},
        )
    )
    agent = make_agent_fixture()
    agent.workspace = Workspace(name="dev", image="python:3.12-slim")
    provider.set_agent(agent)

    graph = provider._build_graph_for_tests(agent, tools_dir=None)
    node_names = {n.name for n in graph.nodes()}
    assert f"workspace-ssh-keygen:{agent.name}" in node_names
    assert f"workspace:{agent.name}" in node_names
```

- [ ] **Step 3: Run to verify fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_provider.py -v -k workspace_node`
Expected: FAIL.

- [ ] **Step 4: Implement**

In `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py`, modify `_add_vault_nodes` (or add a new `_add_workspace_nodes` called from `apply` after `_add_vault_nodes`):

```python
def _add_workspace_nodes(self, graph, tools_dir):
    """Add workspace + SSH-keygen nodes when Agent.workspace is declared."""
    if not self._agent.workspace:
        return

    from vystak_provider_docker.nodes import (
        DockerWorkspaceNode,
        WorkspaceSshKeygenNode,
    )
    from vystak_provider_docker.vault_client import VaultClient

    # VaultClient is already instantiated in _add_vault_nodes; re-fetch
    # from context-level state or instantiate fresh (both work since
    # hvac client is thin).
    cfg = self._vault.config or {}
    port = cfg.get("port", 8200)
    host_port = cfg.get("host_port", port)
    vault_client = VaultClient(f"http://localhost:{host_port}")
    # Token will be set by the kv-setup node context flow; the SSH keygen
    # runs after kv-setup, so set_token happens then. For simplicity we
    # use the same late-bound trick as v1 Hashi (pass a callable).

    # SSH keygen runs after kv-setup
    from .nodes import WorkspaceSshKeygenNode  # re-import for clarity
    keygen = WorkspaceSshKeygenNode(
        vault_client=vault_client,
        docker_client=self._client,
        agent_name=self._agent.name,
    )
    graph.add(keygen)
    graph.add_dependency(keygen.name, "hashi-vault:kv-setup")

    # Workspace container depends on workspace-principal vault-agent sidecar
    # + ssh-keygen (so the host key exists when sshd reads it)
    from .nodes import DockerWorkspaceNode
    ws_node = DockerWorkspaceNode(
        client=self._client,
        agent_name=self._agent.name,
        workspace=self._agent.workspace,
        tools_dir=tools_dir or Path.cwd() / "tools",
    )
    graph.add(ws_node)
    graph.add_dependency(ws_node.name, keygen.name)
    graph.add_dependency(ws_node.name, f"vault-agent:{self._agent.name}-workspace")

    return ws_node.container_name
```

And in `apply()`, after `_add_vault_nodes(graph)`:

```python
workspace_host = None
if getattr(self, "_vault", None) and self._agent.workspace:
    workspace_host = self._add_workspace_nodes(graph, tools_dir=Path(".") / "tools")
```

And when constructing the agent node:
```python
if workspace_host:
    agent_node.set_workspace_context(workspace_host=workspace_host)
    graph.add_dependency(agent_node.name, f"workspace:{self._agent.name}")
```

Also update `_build_graph_for_tests` to accept an optional `tools_dir` parameter and call `_add_workspace_nodes`.

- [ ] **Step 5: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_provider.py -v`
Expected: PASS (new test + no regression).

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/__init__.py packages/python/vystak-provider-docker/tests/test_provider.py
git commit -m "feat(provider-docker): _add_workspace_nodes wires workspace + ssh-keygen into apply graph"
```

---

## Phase 5 — LangChain adapter: agent-side SSH client + tool wrappers

### Task 16: Agent-side asyncssh client wrapper

**Files:**
- Create: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/workspace_client.py`
- Create: `packages/python/vystak-adapter-langchain/tests/test_workspace_client.py`

- [ ] **Step 1: Write failing test**

Create `packages/python/vystak-adapter-langchain/tests/test_workspace_client.py`:

```python
"""Tests for the agent-side WorkspaceRpcClient."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vystak_adapter_langchain.workspace_client import WorkspaceRpcClient


@pytest.mark.asyncio
async def test_invoke_sends_jsonrpc_and_returns_result():
    """Non-streaming call sends one request, reads one response line."""
    client = WorkspaceRpcClient(
        host="test-workspace", port=22, username="vystak-agent",
        client_keys=["/fake/key"], known_hosts="/fake/known_hosts",
    )

    mock_channel = AsyncMock()
    # The response will be written to the write side; we simulate it on read
    response_line = json.dumps({"jsonrpc": "2.0", "id": "x", "result": "hi"})
    mock_channel.readline = AsyncMock(return_value=response_line + "\n")

    mock_session = AsyncMock()
    mock_conn = AsyncMock()
    mock_conn.create_session = AsyncMock(return_value=(mock_session, None))

    with patch.object(client, "_conn", mock_conn):
        client._conn = mock_conn

        # Short-circuit _open_channel to return mock_channel
        with patch.object(client, "_open_channel", AsyncMock(return_value=mock_channel)):
            result = await client.invoke("fs.readFile", path="foo.py")
    assert result == "hi"


@pytest.mark.asyncio
async def test_invoke_raises_on_error_response():
    client = WorkspaceRpcClient(
        host="x", port=22, username="u",
        client_keys=["/k"], known_hosts="/kh",
    )
    err_line = json.dumps({
        "jsonrpc": "2.0", "id": "x",
        "error": {"code": -32000, "message": "disk full"}
    })
    mock_channel = AsyncMock()
    mock_channel.readline = AsyncMock(return_value=err_line + "\n")
    with patch.object(client, "_open_channel", AsyncMock(return_value=mock_channel)):
        with pytest.raises(Exception, match="disk full"):
            await client.invoke("fs.readFile", path="foo.py")


@pytest.mark.asyncio
async def test_invoke_stream_yields_progress_then_result():
    """Streaming call: multiple progress notifications then final result."""
    progress = json.dumps({"jsonrpc": "2.0", "method": "$/progress",
                           "params": {"chunk": "hello\n"}})
    final = json.dumps({"jsonrpc": "2.0", "id": "x", "result": {"exit_code": 0}})

    client = WorkspaceRpcClient(
        host="x", port=22, username="u",
        client_keys=["/k"], known_hosts="/kh",
    )

    lines = [progress + "\n", final + "\n", ""]
    mock_channel = AsyncMock()
    mock_channel.readline = AsyncMock(side_effect=lines)

    with patch.object(client, "_open_channel", AsyncMock(return_value=mock_channel)):
        chunks = []
        async for item in client.invoke_stream("exec.run", cmd=["echo", "hello"]):
            chunks.append(item)

    # Last item is the result; earlier items are progress chunks
    assert chunks[-1] == {"exit_code": 0}
    assert any("hello" in (c.get("chunk", "") if isinstance(c, dict) else "")
               for c in chunks[:-1])
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-adapter-langchain/tests/test_workspace_client.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/workspace_client.py`:

```python
"""Agent-side SSH client for the workspace JSON-RPC subsystem.

Manages one persistent asyncssh connection; opens a channel per tool
call to the vystak-rpc subsystem; reads JSONL responses.
"""

import json
import uuid
from collections.abc import AsyncIterator

import asyncssh


class WorkspaceRpcClient:
    def __init__(
        self,
        *,
        host: str,
        port: int = 22,
        username: str = "vystak-agent",
        client_keys: list[str],
        known_hosts: str | None,
    ):
        self._host = host
        self._port = port
        self._username = username
        self._client_keys = list(client_keys)
        self._known_hosts = known_hosts
        self._conn: asyncssh.SSHClientConnection | None = None

    async def connect(self) -> None:
        if self._conn is not None:
            return
        self._conn = await asyncssh.connect(
            self._host,
            port=self._port,
            username=self._username,
            client_keys=self._client_keys,
            known_hosts=self._known_hosts,
        )

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None

    async def _open_channel(self):
        """Open one SSH channel to the vystak-rpc subsystem."""
        assert self._conn is not None, "connect() first"
        # asyncssh: use create_session for subsystem access
        chan, session = await self._conn.create_session(
            asyncssh.SSHClientSession,
            subsystem="vystak-rpc",
        )
        return chan

    async def invoke(self, method: str, **params) -> object:
        """Single-shot call. Returns result or raises on error."""
        await self.connect()
        chan = await self._open_channel()
        req = {
            "jsonrpc": "2.0", "id": uuid.uuid4().hex,
            "method": method, "params": params,
        }
        chan.write(json.dumps(req) + "\n")
        chan.write_eof()

        while True:
            line = await chan.readline()
            if not line:
                raise RuntimeError(f"RPC channel closed without response for {method}")
            msg = json.loads(line)
            if msg.get("method") == "$/progress":
                continue  # skip progress for non-streaming invoke
            if "error" in msg:
                err = msg["error"]
                raise RuntimeError(f"{method}: {err.get('message')}")
            if "result" in msg:
                return msg["result"]

    async def invoke_stream(self, method: str, **params) -> AsyncIterator[object]:
        """Streaming call. Yields progress chunks (dicts from params) then
        the final result. Caller consumes via `async for`."""
        await self.connect()
        chan = await self._open_channel()
        req = {
            "jsonrpc": "2.0", "id": uuid.uuid4().hex,
            "method": method, "params": params,
        }
        chan.write(json.dumps(req) + "\n")
        chan.write_eof()

        while True:
            line = await chan.readline()
            if not line:
                return
            msg = json.loads(line)
            if msg.get("method") == "$/progress":
                yield msg.get("params", {})
                continue
            if "error" in msg:
                raise RuntimeError(f"{method}: {msg['error'].get('message')}")
            if "result" in msg:
                yield msg["result"]
                return
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-adapter-langchain/tests/test_workspace_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/workspace_client.py packages/python/vystak-adapter-langchain/tests/test_workspace_client.py
git commit -m "feat(adapter-langchain): WorkspaceRpcClient — asyncssh + JSON-RPC 2.0"
```

---

### Task 17: Built-in tool wrappers (`fs.*`, `exec.*`, `git.*`) for LangChain

**Files:**
- Create: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/builtin_tools.py`
- Create: `packages/python/vystak-adapter-langchain/tests/test_builtin_tools.py`

- [ ] **Step 1: Write failing test**

Create `packages/python/vystak-adapter-langchain/tests/test_builtin_tools.py`:

```python
"""Tests that generate_builtin_tools produces wrapped @tool functions
that delegate to WorkspaceRpcClient."""

from unittest.mock import AsyncMock

import pytest

from vystak_adapter_langchain.builtin_tools import generate_builtin_tools


def test_generates_fs_read_file_tool(tmp_path):
    files = generate_builtin_tools(
        skill_tool_names=["fs.readFile", "exec.run", "git.status"],
    )
    content = files["builtin_tools.py"]
    # Each built-in method generates a wrapper
    assert "async def read_file" in content
    assert "async def run" in content
    assert "async def status" in content
    # Wrappers call the workspace client
    assert "workspace_client.invoke" in content or "workspace_client.invoke_stream" in content
    # @tool decorator applied
    assert "@tool" in content


def test_skips_unrecognized_prefixes():
    files = generate_builtin_tools(
        skill_tool_names=["fs.readFile", "nope.something", "custom_tool"],
    )
    # Only fs.* built-in is rendered; nope.* is neither built-in nor user
    content = files["builtin_tools.py"]
    assert "async def read_file" in content
    assert "nope" not in content


def test_exec_run_is_streaming():
    files = generate_builtin_tools(skill_tool_names=["exec.run", "fs.readFile"])
    content = files["builtin_tools.py"]
    # exec.* uses invoke_stream
    assert "async def run" in content
    # The generated body for run() accumulates streamed chunks
    assert "invoke_stream" in content
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-adapter-langchain/tests/test_builtin_tools.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/builtin_tools.py`:

```python
"""Generates LangChain @tool wrappers for built-in workspace services
(fs.*, exec.*, git.*). User-defined tools (under tool.*) are generated
by the existing tools discovery path."""

# Built-in method specs: (rpc_method, local_function_name, positional_params, streams)
BUILTIN_SPECS = {
    "fs.readFile": ("read_file", ["path"], False),
    "fs.writeFile": ("write_file", ["path", "content"], False),
    "fs.appendFile": ("append_file", ["path", "content"], False),
    "fs.deleteFile": ("delete_file", ["path"], False),
    "fs.listDir": ("list_dir", ["path"], False),
    "fs.stat": ("stat_file", ["path"], False),
    "fs.exists": ("exists", ["path"], False),
    "fs.mkdir": ("mkdir", ["path"], False),
    "fs.move": ("move", ["src", "dst"], False),
    "fs.edit": ("edit_file", ["path", "old_str", "new_str"], False),
    "exec.run": ("run", ["cmd"], True),
    "exec.shell": ("shell", ["script"], True),
    "exec.which": ("which", ["name"], False),
    "git.status": ("git_status", [], False),
    "git.log": ("git_log", [], False),
    "git.diff": ("git_diff", [], False),
    "git.add": ("git_add", ["paths"], False),
    "git.commit": ("git_commit", ["message"], False),
    "git.branch": ("git_branch", [], False),
}


def generate_builtin_tools(skill_tool_names: list[str]) -> dict[str, str]:
    """Given the set of tool names referenced by all skills, emit a
    builtin_tools.py file defining @tool-decorated async functions that
    delegate to WorkspaceRpcClient."""
    recognized = [n for n in skill_tool_names if n in BUILTIN_SPECS]

    lines = [
        '"""Auto-generated built-in tool wrappers for workspace services."""',
        "",
        "from langchain_core.tools import tool",
        "",
        "from vystak_adapter_langchain.workspace_client import WorkspaceRpcClient",
        "",
        "# Populated at module load by the bootstrap code.",
        "workspace_client: WorkspaceRpcClient | None = None",
        "",
        "",
        "def _require_client() -> WorkspaceRpcClient:",
        "    assert workspace_client is not None, 'WorkspaceRpcClient not initialized'",
        "    return workspace_client",
        "",
    ]

    for rpc_method in recognized:
        local_name, params, streams = BUILTIN_SPECS[rpc_method]
        # Function signature (params as keyword-only args in LangChain tool model)
        sig_params = ", ".join(f"{p}" for p in params) if params else ""
        lines.append("@tool")
        lines.append(f"async def {local_name}({sig_params}) -> object:")
        lines.append(f'    """Workspace {rpc_method}"""')
        lines.append("    c = _require_client()")
        if streams:
            lines.append("    result = None")
            if params:
                kwargs = ", ".join(f"{p}={p}" for p in params)
                lines.append(f"    async for item in c.invoke_stream('{rpc_method}', {kwargs}):")
            else:
                lines.append(f"    async for item in c.invoke_stream('{rpc_method}'):")
            lines.append("        result = item")
            lines.append("    return result")
        else:
            if params:
                kwargs = ", ".join(f"{p}={p}" for p in params)
                lines.append(f"    return await c.invoke('{rpc_method}', {kwargs})")
            else:
                lines.append(f"    return await c.invoke('{rpc_method}')")
        lines.append("")

    return {"builtin_tools.py": "\n".join(lines)}
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-adapter-langchain/tests/test_builtin_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/builtin_tools.py packages/python/vystak-adapter-langchain/tests/test_builtin_tools.py
git commit -m "feat(adapter-langchain): generate_builtin_tools emits @tool wrappers for fs/exec/git services"
```

---

### Task 18: Wire builtin_tools + bootstrap into adapter code generation

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/adapter.py`
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py` (minor)
- Test: extend `packages/python/vystak-adapter-langchain/tests/test_adapter.py`

- [ ] **Step 1: Write failing test**

Append to `packages/python/vystak-adapter-langchain/tests/test_adapter.py`:

```python
def test_workspace_declared_generates_builtin_tools_and_bootstrap():
    from vystak_adapter_langchain.adapter import LangChainAdapter
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.platform import Platform
    from vystak.schema.provider import Provider
    from vystak.schema.skill import Skill
    from vystak.schema.workspace import Workspace
    from pathlib import Path
    import tempfile

    docker_p = Provider(name="docker", type="docker")
    platform = Platform(name="local", type="docker", provider=docker_p)
    anthropic = Provider(name="anthropic", type="anthropic")
    agent = Agent(
        name="coder",
        model=Model(name="m", provider=anthropic, model_name="claude-sonnet-4-20250514"),
        platform=platform,
        skills=[Skill(name="edit", tools=["fs.readFile", "fs.writeFile", "exec.run"])],
        workspace=Workspace(name="dev", image="python:3.12-slim"),
    )
    with tempfile.TemporaryDirectory() as td:
        tools_dir = Path(td) / "tools"
        tools_dir.mkdir()
        code = LangChainAdapter().generate(agent, base_dir=Path(td))

    files = code.files
    # Built-in tools file generated
    assert "builtin_tools.py" in files
    assert "read_file" in files["builtin_tools.py"]
    # Bootstrap code initializes workspace client
    assert "WorkspaceRpcClient" in files.get("server.py", "")
    assert "VYSTAK_WORKSPACE_HOST" in files.get("server.py", "")


def test_no_workspace_no_builtin_tools():
    from vystak_adapter_langchain.adapter import LangChainAdapter
    # (construct agent without workspace)
    # ... same fixture without workspace= ...
    # Assert 'builtin_tools.py' not in code.files
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-adapter-langchain/tests/test_adapter.py -v -k workspace_declared`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/adapter.py`, modify `generate`:

```python
def generate(self, agent, base_dir):
    # ... existing tool discovery ...
    files = {}  # ... existing ...

    if agent.workspace is not None:
        from vystak_adapter_langchain.builtin_tools import generate_builtin_tools
        all_skill_tools = []
        for s in agent.skills:
            all_skill_tools.extend(s.tools)
        builtin = generate_builtin_tools(skill_tool_names=all_skill_tools)
        files.update(builtin)
        # Inject workspace bootstrap into server.py
        server_py = files.get("server.py", "")
        bootstrap = (
            "\n\n"
            "# --- Workspace bootstrap (Spec 1) ---\n"
            "import os\n"
            "from vystak_adapter_langchain.workspace_client import WorkspaceRpcClient\n"
            "from vystak_adapter_langchain import builtin_tools as _bt\n"
            "\n"
            "_ws_host = os.environ.get('VYSTAK_WORKSPACE_HOST')\n"
            "if _ws_host:\n"
            "    _bt.workspace_client = WorkspaceRpcClient(\n"
            "        host=_ws_host,\n"
            "        port=22,\n"
            "        username='vystak-agent',\n"
            "        client_keys=['/vystak/ssh/id_ed25519'],\n"
            "        known_hosts='/vystak/ssh/known_hosts',\n"
            "    )\n"
            "    import asyncio as _asyncio\n"
            "    _asyncio.get_event_loop().run_until_complete(_bt.workspace_client.connect())\n"
            "# --- end Workspace bootstrap ---\n"
        )
        files["server.py"] = server_py + bootstrap
    return code_with_files(files)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-adapter-langchain/tests/test_adapter.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/adapter.py packages/python/vystak-adapter-langchain/tests/test_adapter.py
git commit -m "feat(adapter-langchain): emit builtin_tools.py + workspace bootstrap when workspace declared"
```

---

## Phase 6 — CLI

### Task 19: `vystak destroy` new flags

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/destroy.py`
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py` — extend destroy kwargs
- Test: `packages/python/vystak-cli/tests/test_destroy_workspace.py` (new)

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-cli/tests/test_destroy_workspace.py`:

```python
"""Tests for --delete-workspace-data and --keep-workspace flags."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from vystak_cli.commands.destroy import destroy as destroy_cmd


YAML = """\
providers: {docker: {type: docker}, anthropic: {type: anthropic}}
platforms: {local: {type: docker, provider: docker}}
vault: {name: v, provider: docker, type: vault, mode: deploy, config: {}}
models: {sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}}
agents:
  - name: assistant
    model: sonnet
    platform: local
    workspace: {name: dev, image: python:3.12-slim}
"""


def test_destroy_delete_workspace_data(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(YAML)
    provider = MagicMock()
    runner = CliRunner()
    with patch("vystak_cli.commands.destroy.get_provider", return_value=provider):
        result = runner.invoke(destroy_cmd, ["--file", str(config), "--delete-workspace-data"])
    assert result.exit_code == 0, result.output
    assert provider.destroy.call_args.kwargs.get("delete_workspace_data") is True


def test_destroy_keep_workspace(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(YAML)
    provider = MagicMock()
    runner = CliRunner()
    with patch("vystak_cli.commands.destroy.get_provider", return_value=provider):
        result = runner.invoke(destroy_cmd, ["--file", str(config), "--keep-workspace"])
    assert result.exit_code == 0, result.output
    assert provider.destroy.call_args.kwargs.get("keep_workspace") is True
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-cli/tests/test_destroy_workspace.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `destroy.py`, add two more flags (`--delete-workspace-data`, `--keep-workspace`) and thread as kwargs to `provider.destroy`. Same pattern as v1's `--delete-vault` / `--keep-sidecars`.

In `DockerProvider.destroy`:

```python
delete_workspace_data = bool(kwargs.get("delete_workspace_data", False))
keep_workspace = bool(kwargs.get("keep_workspace", False))

if not keep_workspace:
    # Stop and remove workspace container
    try:
        ws = self._client.containers.get(f"vystak-{agent_name}-workspace")
        ws.stop()
        ws.remove()
    except docker.errors.NotFound:
        pass
    if delete_workspace_data:
        try:
            vol = self._client.volumes.get(f"vystak-{agent_name}-workspace-data")
            vol.remove()
        except docker.errors.NotFound:
            pass
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-cli/tests/test_destroy_workspace.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/destroy.py packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py packages/python/vystak-cli/tests/test_destroy_workspace.py
git commit -m "feat(cli): vystak destroy gains --delete-workspace-data, --keep-workspace"
```

---

### Task 20: `vystak secrets rotate-ssh <agent>` subcommand

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py`
- Test: `packages/python/vystak-cli/tests/test_secrets_rotate_ssh.py` (new)

- [ ] **Step 1: Write failing test**

Create `packages/python/vystak-cli/tests/test_secrets_rotate_ssh.py`:

```python
"""Tests for vystak secrets rotate-ssh <agent>."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from vystak_cli.commands.secrets import secrets


YAML = """\
providers: {docker: {type: docker}, anthropic: {type: anthropic}}
platforms: {local: {type: docker, provider: docker}}
vault: {name: v, provider: docker, type: vault, mode: deploy, config: {}}
models: {sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}}
agents:
  - name: assistant
    model: sonnet
    platform: local
    workspace: {name: dev, image: python:3.12-slim}
"""


def test_rotate_ssh_regenerates_and_pushes(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(YAML)
    runner = CliRunner()
    mock_vault = MagicMock()
    mock_docker = MagicMock()
    with patch("vystak_cli.commands.secrets._make_vault_client", return_value=mock_vault), \
         patch("vystak_cli.commands.secrets._get_docker_client", return_value=mock_docker):
        result = runner.invoke(
            secrets, ["rotate-ssh", "assistant", "--file", str(config)]
        )
    assert result.exit_code == 0, result.output
    # Four kv_put calls (client-key, host-key, client-key-pub, host-key-pub)
    assert mock_vault.kv_put.call_count == 4


def test_rotate_ssh_for_nonexistent_agent_errors(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(YAML)
    runner = CliRunner()
    result = runner.invoke(secrets, ["rotate-ssh", "nope", "--file", str(config)])
    assert result.exit_code != 0
    assert "nope" in result.output.lower()
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-cli/tests/test_secrets_rotate_ssh.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add to `secrets.py`:

```python
@secrets.command("rotate-ssh")
@click.argument("agent_name", required=True)
@click.option("--file", default="vystak.yaml")
def rotate_ssh_cmd(agent_name, file):
    """Regenerate the SSH keypairs for a workspace-backed agent."""
    # Load config, find the named agent, verify it has a workspace + Vault
    from pathlib import Path
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml

    data = yaml.safe_load(Path(file).read_text())
    agents, _channels, vault = load_multi_yaml(data)
    if vault is None:
        raise click.ClickException("rotate-ssh requires a Vault declaration.")
    matching = [a for a in agents if a.name == agent_name]
    if not matching:
        raise click.ClickException(
            f"Agent '{agent_name}' not found. Known: "
            f"{', '.join(a.name for a in agents)}"
        )
    agent = matching[0]
    if agent.workspace is None:
        raise click.ClickException(
            f"Agent '{agent_name}' has no workspace; nothing to rotate."
        )

    vault_client = _make_vault_client(vault)
    docker_client = _get_docker_client()

    # Invalidate existing keys (delete from Vault) then regenerate.
    for key in ("client-key", "host-key", "client-key-pub", "host-key-pub"):
        try:
            vault_client.kv_delete(f"_vystak/workspace-ssh/{agent_name}/{key}")
        except Exception:
            pass

    from vystak_provider_docker.nodes.workspace_ssh_keygen import WorkspaceSshKeygenNode
    node = WorkspaceSshKeygenNode(
        vault_client=vault_client,
        docker_client=docker_client,
        agent_name=agent_name,
    )
    node.provision(context={})

    click.echo(f"  rotated  {agent_name}")


def _get_docker_client():
    import docker
    return docker.from_env()
```

And add `kv_delete` to the vault_client if not present (v1 may not have it — add):
```python
def kv_delete(self, name: str) -> None:
    self._client.secrets.kv.v2.delete_metadata_and_all_versions(path=name)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-cli/tests/test_secrets_rotate_ssh.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/secrets.py packages/python/vystak-provider-docker/src/vystak_provider_docker/vault_client.py packages/python/vystak-cli/tests/test_secrets_rotate_ssh.py
git commit -m "feat(cli): vystak secrets rotate-ssh <agent> regenerates SSH keypairs"
```

---

### Task 21: `vystak plan` / `vystak apply` Workspace section

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/plan.py`
- Test: extend `packages/python/vystak-cli/tests/test_plan_secret_manager.py` or new file

- [ ] **Step 1: Write failing test**

Append to `packages/python/vystak-cli/tests/test_plan_secret_manager.py`:

```python
def test_plan_workspace_section_shown_when_declared(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text("""\
providers: {docker: {type: docker}, anthropic: {type: anthropic}}
platforms: {local: {type: docker, provider: docker}}
vault: {name: v, provider: docker, type: vault, mode: deploy, config: {}}
models: {sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}}
agents:
  - name: coder
    model: sonnet
    platform: local
    workspace:
      name: dev
      image: python:3.12-slim
      provision: ["pip install ruff"]
      persistence: volume
""")
    runner = CliRunner()
    with patch("vystak_cli.commands.plan.get_provider", return_value=_stub_provider_for_plan()):
        result = runner.invoke(plan_cmd, ["--file", str(config)])
    assert result.exit_code == 0, result.output
    assert "Workspace:" in result.output
    assert "python:3.12-slim" in result.output
    assert "persistence" in result.output.lower()
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-cli/tests/test_plan_secret_manager.py -v -k workspace_section`
Expected: FAIL.

- [ ] **Step 3: Add workspace section emitter in plan.py**

After vault emission in `plan.py`, add:

```python
def _print_workspace_section(agents):
    ws_agents = [a for a in agents if a.workspace is not None]
    if not ws_agents:
        return
    click.echo()
    click.echo("Workspaces:")
    for a in ws_agents:
        ws = a.workspace
        if ws.dockerfile:
            img = f"from Dockerfile {ws.dockerfile}"
        else:
            img = ws.image or "<no image>"
        click.echo(f"  {a.name}-workspace  image={img}  persistence={ws.persistence}")
        if ws.provision:
            click.echo(f"    provision steps: {len(ws.provision)}")
        if ws.ssh:
            click.echo(f"    human SSH enabled (authorized_keys: {len(ws.ssh_authorized_keys)})")
```

Call it from the main plan command after vault section.

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-cli/tests/test_plan_secret_manager.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/plan.py packages/python/vystak-cli/tests/test_plan_secret_manager.py
git commit -m "feat(cli): plan output includes Workspaces: section"
```

---

## Phase 7 — Example + integration test

### Task 22: `examples/docker-workspace-compute/`

**Files:**
- Create: `examples/docker-workspace-compute/vystak.yaml`
- Create: `examples/docker-workspace-compute/vystak.py`
- Create: `examples/docker-workspace-compute/.env.example`
- Create: `examples/docker-workspace-compute/README.md`
- Create: `examples/docker-workspace-compute/tools/search_project.py`
- Extend: `packages/python/vystak/tests/test_examples.py`

- [ ] **Step 1: Create example files**

`examples/docker-workspace-compute/vystak.yaml`:
```yaml
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}

platforms:
  local: {type: docker, provider: docker}

vault:
  name: vystak-vault
  provider: docker
  type: vault
  mode: deploy
  config: {}

models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-4-20250514

agents:
  - name: coder
    instructions: |
      You are a coding assistant. Use fs.readFile to read, fs.edit to change,
      exec.run to test, git.status / git.diff to review changes.
    model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
    skills:
      - name: editing
        tools: [fs.readFile, fs.writeFile, fs.listDir, fs.edit]
      - name: shell
        tools: [exec.run, exec.shell]
      - name: vcs
        tools: [git.status, git.diff, git.commit]
      - name: search
        tools: [search_project]
    workspace:
      name: dev
      image: python:3.12-slim
      provision:
        - apt-get update && apt-get install -y git ripgrep
        - pip install ruff pytest
      persistence: volume
```

`examples/docker-workspace-compute/.env.example`:
```
ANTHROPIC_API_KEY=your-anthropic-api-key-here
```

`examples/docker-workspace-compute/README.md`:
```markdown
# docker-workspace-compute

Coding assistant with a real workspace — persistent filesystem, shell
access, git, and an example custom tool (ripgrep-backed project search).

## What this demonstrates

- Workspace deployed as a separate Docker container
- fs/exec/git built-in services via the SSH+JSON-RPC channel
- User tool (`search_project`) running in the workspace container
- Workspace secrets + SSH keys delivered via Vault (v1 Hashi)

## Run

```bash
cp .env.example .env   # then edit
vystak apply
# ... the agent's endpoint is printed ...
vystak destroy          # preserves workspace data volume
vystak destroy --delete-workspace-data  # full teardown
```
```

`examples/docker-workspace-compute/tools/search_project.py`:
```python
"""Project search tool — uses ripgrep inside the workspace."""

import subprocess


def search_project(pattern: str, max_results: int = 50) -> list[str]:
    """Search for pattern in /workspace/ using ripgrep. Returns matching file paths."""
    result = subprocess.run(
        ["rg", "--files-with-matches", pattern, "/workspace/"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"rg failed: {result.stderr}")
    paths = [line for line in result.stdout.splitlines() if line]
    return paths[:max_results]
```

- [ ] **Step 2: Add loader test**

Append to `packages/python/vystak/tests/test_examples.py`:
```python
def test_docker_workspace_compute_example_loads():
    from pathlib import Path
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml

    p = Path(__file__).parent.parent.parent.parent.parent / "examples/docker-workspace-compute/vystak.yaml"
    data = yaml.safe_load(p.read_text())
    agents, _channels, vault = load_multi_yaml(data)
    assert vault is not None
    assert agents[0].workspace is not None
    assert agents[0].workspace.image == "python:3.12-slim"
    assert "pip install ruff pytest" in agents[0].workspace.provision[1]
```

- [ ] **Step 3: Run**

Run: `uv run pytest packages/python/vystak/tests/test_examples.py -v -k docker_workspace_compute`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add examples/docker-workspace-compute/ packages/python/vystak/tests/test_examples.py
git commit -m "examples: add docker-workspace-compute with fs/exec/git + custom search tool"
```

---

### Task 23: Docker-marked integration test

**Files:**
- Create: `packages/python/vystak-provider-docker/tests/test_workspace_integration.py`

- [ ] **Step 1: Write the integration test**

Create `packages/python/vystak-provider-docker/tests/test_workspace_integration.py`:

```python
"""End-to-end: deploy an agent with a workspace, RPC in and out.

Opt-in: `uv run pytest -m docker`.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


AGENT_NAME = "ws-test-agent"


def _docker_available() -> bool:
    try:
        import docker as _docker
        _docker.from_env().ping()
        return True
    except Exception:
        return False


VYSTAK_YAML = f"""\
providers:
  docker: {{type: docker}}
  anthropic: {{type: anthropic}}
platforms:
  local: {{type: docker, provider: docker}}
vault:
  name: v
  provider: docker
  type: vault
  mode: deploy
  config: {{}}
models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-4-20250514
agents:
  - name: {AGENT_NAME}
    model: sonnet
    platform: local
    secrets: [{{name: ANTHROPIC_API_KEY}}]
    skills:
      - name: edit
        tools: [fs.readFile, fs.writeFile, fs.listDir]
    workspace:
      name: dev
      image: python:3.12-slim
      provision:
        - apt-get update && apt-get install -y --no-install-recommends git
"""


def _run_vystak(project_dir: Path, *args, timeout=600):
    env = os.environ.copy()
    env.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-for-test")
    return subprocess.run(
        [sys.executable, "-m", "vystak_cli", *args],
        cwd=project_dir,
        env=env, capture_output=True, text=True, timeout=timeout,
    )


def _cleanup():
    import docker as _docker
    client = _docker.from_env()
    names = [
        f"vystak-{AGENT_NAME}",
        f"vystak-{AGENT_NAME}-workspace",
        f"vystak-{AGENT_NAME}-agent-vault-agent",
        f"vystak-{AGENT_NAME}-workspace-vault-agent",
        "vystak-vault",
    ]
    for n in names:
        try:
            c = client.containers.get(n)
            c.stop(); c.remove()
        except _docker.errors.NotFound:
            pass
    for vol in (
        "vystak-vault-data",
        f"vystak-{AGENT_NAME}-agent-secrets",
        f"vystak-{AGENT_NAME}-agent-approle",
        f"vystak-{AGENT_NAME}-workspace-secrets",
        f"vystak-{AGENT_NAME}-workspace-approle",
        f"vystak-{AGENT_NAME}-workspace-data",
    ):
        try:
            v = client.volumes.get(vol); v.remove()
        except _docker.errors.NotFound:
            pass


@pytest.mark.docker
@pytest.mark.skipif(not _docker_available(), reason="Docker not reachable")
def test_workspace_deploy_and_rpc(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "vystak.yaml").write_text(VYSTAK_YAML)
    (project / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-fake\n")

    _cleanup()
    try:
        result = _run_vystak(project, "apply", "--file", "vystak.yaml")
        assert result.returncode == 0, (
            f"apply failed:\nSTDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

        import docker as _docker
        client = _docker.from_env()

        # Workspace container exists and is running
        ws = client.containers.get(f"vystak-{AGENT_NAME}-workspace")
        assert ws.status == "running"

        # Agent container exists and is running
        ag = client.containers.get(f"vystak-{AGENT_NAME}")
        assert ag.status == "running"

        # Agent's /vystak/ssh contains private key + known_hosts
        # (via symlink to /shared/ssh rendered by vault-agent)
        exec_result = ag.exec_run(
            ["sh", "-c", "ls -la /vystak/ssh/ 2>&1"]
        )
        out = exec_result.output.decode()
        assert "id_ed25519" in out
        assert "known_hosts" in out

        # Workspace /shared contains host key + authorized_keys
        exec_result = ws.exec_run(
            ["sh", "-c", "ls -la /shared/ 2>&1"]
        )
        out = exec_result.output.decode()
        assert "ssh_host_ed25519_key" in out
        assert "authorized_keys_vystak-agent" in out

        # vystak-workspace-rpc is installed in the workspace
        exec_result = ws.exec_run(
            ["sh", "-c", "which vystak-workspace-rpc"]
        )
        out = exec_result.output.decode()
        assert "/usr/local/bin/vystak-workspace-rpc" in out

    finally:
        _cleanup()
```

- [ ] **Step 2: Smoke-run collection**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_workspace_integration.py --collect-only`
Expected: `1 test collected`.

- [ ] **Step 3: Commit**

```bash
git add packages/python/vystak-provider-docker/tests/test_workspace_integration.py
git commit -m "test(provider-docker): docker-marked workspace integration test"
```

**Do NOT run the integration test here** — user will run it manually (requires Docker + network). Plan doesn't dictate it runs green in CI.

---

## Phase 8 — Final validation

### Task 24: Full lint + non-docker test suite

- [ ] **Step 1: Lint**

Run: `uv run ruff check packages/python/`
Expected: clean.

- [ ] **Step 2: Full non-docker suite**

Run: `uv run pytest packages/python/ -q -m 'not docker'`
Expected: all pass. Count grows by ~70 tests from this plan.

- [ ] **Step 3: Smoke-test CLI**

Run: `uv run vystak secrets --help`
Expected: includes `rotate-ssh`.

Run: `uv run vystak destroy --help`
Expected: includes `--delete-workspace-data`, `--keep-workspace`.

- [ ] **Step 4: If any regressions, fix with focused commits**

Pattern: `fix: <specific issue>`. Don't bundle unrelated.

---

## Self-review

**Spec coverage:**
- [x] Schema changes → Task 1
- [x] Cross-object validator (workspace requires Vault) → Task 2
- [x] asyncssh dependency → Task 3
- [x] JSON-RPC 2.0 server core → Task 4
- [x] fs.* service → Task 5
- [x] exec.* service with streaming → Task 6
- [x] git.* service → Task 7
- [x] tool.* service → Task 8
- [x] Subsystem entrypoint → Task 9
- [x] WorkspaceSshKeygenNode → Task 10
- [x] Vault Agent HCL extensions for SSH file templates → Task 11
- [x] Workspace Dockerfile generator → Task 12
- [x] DockerWorkspaceNode → Task 13
- [x] DockerAgentNode.set_workspace_context → Task 14
- [x] Provider graph wiring → Task 15
- [x] Agent-side WorkspaceRpcClient → Task 16
- [x] Built-in tool wrappers → Task 17
- [x] Adapter bootstrap emission → Task 18
- [x] Destroy flags → Task 19
- [x] rotate-ssh CLI → Task 20
- [x] Plan/apply output → Task 21
- [x] Example → Task 22
- [x] Integration test → Task 23
- [x] Final validation → Task 24

Azure provider is NOT in this plan. The spec mentions both Docker and Azure; this plan lands Docker only. Azure workspace support will be a follow-up plan after Docker lands. Documented as a known cut.

**Placeholder scan:** No "TBD", no "similar to Task N", no "add error handling." Every step has concrete code or exact command. A handful of integration-test assertions use fake fixture values to prove isolation; all fixtures explicit.

**Type consistency:**
- `WorkspaceRpcClient` methods `invoke` / `invoke_stream` consistent across Tasks 16-18
- `generate_builtin_tools(skill_tool_names=...)` signature stable
- Node names consistent: `workspace-ssh-keygen:<agent>`, `workspace:<agent>`, `vault-agent:<agent>-workspace`
- `/shared/ssh/*` paths (vault-agent destinations for agent-role) consistent with `/vystak/ssh/*` (agent container symlink target) per Task 14 harmonization note

**Scope check:** Tightly bounded to Spec 1. Sandbox (Spec 2), LSP (Spec 3), orchestrator (follow-up), Azure workspace node (follow-up) all left out.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-22-workspace-compute-unit.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
