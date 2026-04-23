# Secret Manager Simplification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Vault` optional for workspace-bearing deploys. The default path uses per-container `--env-file`-equivalent delivery on Docker and inline `configuration.secrets` on Azure ACA, preserving the full isolation guarantee without requiring Vault.

**Architecture:** The simplification is almost entirely additive-and-gated. Four phases across four PRs. Phase 1 combines schema validator removal + Docker default-path implementation to avoid a transient load-succeeds-but-plan-fails regression. Phase 2 confirms Azure parity. Phase 3 polishes CLI and the LangChain adapter. Phase 4 updates examples and docs.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, Docker SDK (docker-py), Azure SDK.

**Reference spec:** `docs/superpowers/specs/2026-04-22-secret-manager-simplification-design.md`

---

## File Structure

### Phase 1 — Schema + Docker default path

| File | Action | Responsibility |
|---|---|---|
| `packages/python/vystak/src/vystak/schema/multi_loader.py` | Modify (-40 lines) | Remove three vault-required validators |
| `packages/python/vystak/tests/test_multi_loader_workspace.py` | Modify | Flip expect-raise to expect-success |
| `packages/python/vystak/tests/test_multi_loader_vault.py` | Modify | Same |
| `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/env_file.py` | **Create (~70 lines)** | `DockerEnvFileNode` — generates per-principal env dicts; optionally writes audit file |
| `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/__init__.py` | Modify | Export `DockerEnvFileNode` |
| `packages/python/vystak-provider-docker/tests/test_node_env_file.py` | **Create** | Unit tests for the new node |
| `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace_ssh_keygen.py` | Modify | Branch: default path writes host files; Vault path pushes to Vault |
| `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py` | Modify (~30 lines) | Default-path env from context + SSH bind mounts; shim gated |
| `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace.py` | Modify (~30 lines) | Default-path env from context + SSH bind mounts |
| `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py` | Modify (~40 lines) | Branch `apply()` on `vault is None`; add `_add_default_path_nodes()` |
| `packages/python/vystak-provider-docker/tests/test_node_workspace_ssh_keygen.py` | Modify | Add default-path coverage |
| `packages/python/vystak-provider-docker/tests/test_default_path_integration.py` | **Create** | `-m docker` end-to-end isolation test |

### Phase 2 — Azure default path confirmation

| File | Action | Responsibility |
|---|---|---|
| `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py` | Modify if needed | Confirm per-container inline-secrets scoping for workspace |
| `packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py` | Modify | Add default-path workspace test |

### Phase 3 — CLI + adapter

| File | Action | Responsibility |
|---|---|---|
| `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py` | Modify | Branch each subcommand on vault presence |
| `packages/python/vystak-cli/src/vystak_cli/commands/plan.py` | Modify | `EnvFiles:` section; orphan-resource detection |
| `packages/python/vystak-cli/src/vystak_cli/commands/destroy.py` | Modify | Clean `.vystak/env/` and `.vystak/ssh/` on default path |
| `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py` | Modify | Gate entrypoint-shim emission on Vault presence |

### Phase 4 — Examples + docs

| File | Action | Responsibility |
|---|---|---|
| `examples/docker-workspace-nodejs/vystak.py` | Modify | Drop `vault:` block |
| `examples/docker-workspace-nodejs/README.md` | Modify | Update to the new default path |
| `docs/getting-started.md` | Modify | Update secrets section |
| `CHANGELOG.md` (if exists) or release notes file | Create/modify | Release notes |

---

## Phase 1 — Schema validators + Docker default path (one PR)

### Task 1: Remove the "workspace secrets on Docker requires Hashi Vault" validator

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/multi_loader.py:112-136`
- Modify: `packages/python/vystak/tests/test_multi_loader_vault.py`

- [ ] **Step 1: Read the current validator block**

Run: `grep -n 'declares secrets on a Docker platform' packages/python/vystak/src/vystak/schema/multi_loader.py`
Expected: Matches at lines 112-136 region.

- [ ] **Step 2: Write a failing test asserting workspace-secrets-on-Docker-without-Vault loads cleanly**

Add to `packages/python/vystak/tests/test_multi_loader_workspace.py`:

```python
def test_workspace_secrets_on_docker_without_vault_loads():
    """Default-path delivery handles per-container isolation via --env-file.
    Vault declaration is no longer required."""
    data = {
        "providers": {"docker": {"type": "docker"}, "anthropic": {"type": "anthropic"}},
        "platforms": {"docker": {"provider": "docker", "type": "docker"}},
        "models": {"sonnet": {"provider": "anthropic", "model_name": "claude-sonnet-4-6"}},
        "agents": [
            {
                "name": "assistant",
                "model": "sonnet",
                "platform": "docker",
                "secrets": [{"name": "ANTHROPIC_API_KEY"}],
                "workspace": {
                    "name": "ws",
                    "secrets": [{"name": "STRIPE_API_KEY"}],
                },
            }
        ],
    }
    from vystak.schema.multi_loader import load_multi_yaml

    agents, channels, vault = load_multi_yaml(data)
    assert len(agents) == 1
    assert agents[0].workspace is not None
    assert [s.name for s in agents[0].workspace.secrets] == ["STRIPE_API_KEY"]
    assert vault is None
```

- [ ] **Step 3: Run the test — it fails with ValueError from the old validator**

Run: `uv run pytest packages/python/vystak/tests/test_multi_loader_workspace.py::test_workspace_secrets_on_docker_without_vault_loads -v`
Expected: FAIL — raises ValueError with "declares secrets on a Docker platform".

- [ ] **Step 4: Delete the validator block at multi_loader.py lines 112-155**

Edit `packages/python/vystak/src/vystak/schema/multi_loader.py` — remove the block starting with the comment `# Cross-object check: workspace secrets need a compatible backend.` (line 105) through the end of the Spec 1 block (line 155). The surrounding code should go from:

```python
        agent = Agent.model_validate(agent_data)

        # Cross-object check: workspace secrets need a compatible backend.
        # ... (all the removed validator logic) ...

        agents.append(agent)
```

to:

```python
        agent = Agent.model_validate(agent_data)

        agents.append(agent)
```

- [ ] **Step 5: Run the new test — it passes**

Run: `uv run pytest packages/python/vystak/tests/test_multi_loader_workspace.py::test_workspace_secrets_on_docker_without_vault_loads -v`
Expected: PASS.

- [ ] **Step 6: Find and update existing tests that expected the old validator to raise**

Run: `uv run pytest packages/python/vystak/tests/ -v 2>&1 | grep -E 'FAIL|ERROR' | head -20`
Expected: 0 or a handful of failures in `test_multi_loader_vault.py` / `test_multi_loader_workspace.py` asserting "requires a Vault" or "declares secrets on a Docker platform".

For each failing test, either delete it (if its only purpose was asserting the removed error) or flip its assertion to expect success. Commit them together with the validator removal.

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/multi_loader.py \
  packages/python/vystak/tests/test_multi_loader_workspace.py \
  packages/python/vystak/tests/test_multi_loader_vault.py
git commit -m "$(cat <<'EOF'
schema: drop vault-required validators for workspaces

Per-container isolation is provided by the container boundary itself, not
by Vault. Each provider's default delivery path (--env-file on Docker,
inline configuration.secrets on Azure) handles per-principal scoping.
Vault declaration is now purely opt-in.

Removes three validators from multi_loader.py totaling ~40 lines:
- workspace-secrets-on-Docker-requires-Hashi-Vault
- workspace-secrets-on-non-Azure-non-Docker-rejected
- Spec 1 workspace-requires-Vault-for-SSH-storage

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Add `DockerEnvFileNode`

**Files:**
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/env_file.py`
- Create: `packages/python/vystak-provider-docker/tests/test_node_env_file.py`
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/__init__.py`

- [ ] **Step 1: Write failing unit tests**

Create `packages/python/vystak-provider-docker/tests/test_node_env_file.py`:

```python
"""Unit tests for DockerEnvFileNode."""

from pathlib import Path

import pytest

from vystak_provider_docker.nodes.env_file import DockerEnvFileNode


def test_writes_env_file_with_declared_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    node = DockerEnvFileNode(
        principal_name="assistant-agent",
        declared_secret_names=["ANTHROPIC_API_KEY"],
        env_values={"ANTHROPIC_API_KEY": "sk-test", "OTHER": "ignored"},
    )
    result = node.provision(context={})
    assert result.success
    env_file = tmp_path / ".vystak" / "env" / "assistant-agent.env"
    assert env_file.exists()
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert env_file.read_text() == "ANTHROPIC_API_KEY=sk-test\n"
    assert result.info["env"] == {"ANTHROPIC_API_KEY": "sk-test"}
    assert result.info["env_file_path"] == str(env_file)


def test_declared_but_missing_from_env_aborts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    node = DockerEnvFileNode(
        principal_name="assistant-agent",
        declared_secret_names=["ANTHROPIC_API_KEY", "MISSING_KEY"],
        env_values={"ANTHROPIC_API_KEY": "sk-test"},
    )
    result = node.provision(context={})
    assert not result.success
    assert "MISSING_KEY" in (result.error or "")


def test_allow_missing_does_not_abort(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    node = DockerEnvFileNode(
        principal_name="assistant-agent",
        declared_secret_names=["ANTHROPIC_API_KEY", "MISSING_KEY"],
        env_values={"ANTHROPIC_API_KEY": "sk-test"},
        allow_missing=True,
    )
    result = node.provision(context={})
    assert result.success
    assert result.info["missing"] == ["MISSING_KEY"]
    assert result.info["env"] == {"ANTHROPIC_API_KEY": "sk-test"}


def test_empty_declared_is_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    node = DockerEnvFileNode(
        principal_name="assistant-agent",
        declared_secret_names=[],
        env_values={"WHATEVER": "x"},
    )
    result = node.provision(context={})
    assert result.success
    assert result.info["env"] == {}
    env_file = tmp_path / ".vystak" / "env" / "assistant-agent.env"
    assert not env_file.exists()


def test_node_name():
    node = DockerEnvFileNode(
        principal_name="assistant-agent",
        declared_secret_names=[],
        env_values={},
    )
    assert node.name == "env-file:assistant-agent"
```

- [ ] **Step 2: Run tests — they fail with ModuleNotFoundError**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_env_file.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vystak_provider_docker.nodes.env_file'`.

- [ ] **Step 3: Implement `DockerEnvFileNode`**

Create `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/env_file.py`:

```python
"""DockerEnvFileNode — per-principal env file generation for the default
(no-Vault) delivery path.

For each principal, writes `.vystak/env/<principal>.env` containing only the
secrets declared on that principal, resolved from deployer-supplied env values
(typically from `.env`). The file is chmod 600 and gitignored via `.vystak/`.

The generated env dict is also returned in the provision result so downstream
container nodes can pass it directly to docker-py `environment=` without
re-reading the file.
"""

from pathlib import Path

from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult


class DockerEnvFileNode(Provisionable):
    """Generates a per-principal env file + env dict for the default path."""

    def __init__(
        self,
        *,
        principal_name: str,
        declared_secret_names: list[str],
        env_values: dict[str, str],
        allow_missing: bool = False,
    ):
        self._principal = principal_name
        self._declared = list(declared_secret_names)
        self._env = dict(env_values)
        self._allow_missing = allow_missing

    @property
    def name(self) -> str:
        return f"env-file:{self._principal}"

    @property
    def depends_on(self) -> list[str]:
        return []

    def provision(self, context: dict) -> ProvisionResult:
        resolved: dict[str, str] = {}
        missing: list[str] = []
        for key in self._declared:
            if key in self._env:
                resolved[key] = self._env[key]
            else:
                missing.append(key)

        if missing and not self._allow_missing:
            return ProvisionResult(
                name=self.name,
                success=False,
                error=(
                    f"Secrets declared on principal '{self._principal}' but "
                    f"missing from .env: {', '.join(missing)}. Set them in "
                    f".env, remove from the declaration, or run apply with "
                    f"--allow-missing."
                ),
            )

        env_file_path: str | None = None
        if resolved:
            out_dir = Path(".vystak") / "env"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"{self._principal}.env"
            lines = [f"{k}={v}" for k, v in resolved.items()]
            out_file.write_text("\n".join(lines) + "\n")
            out_file.chmod(0o600)
            env_file_path = str(out_file)

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "env": resolved,
                "env_file_path": env_file_path,
                "missing": missing,
            },
        )

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        """Best-effort removal of the env file; leave the directory."""
        out_file = Path(".vystak") / "env" / f"{self._principal}.env"
        if out_file.exists():
            out_file.unlink()
```

- [ ] **Step 4: Export the node**

Modify `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/__init__.py` to add the import. Find the existing re-exports and add:

```python
from vystak_provider_docker.nodes.env_file import DockerEnvFileNode
```

and add `"DockerEnvFileNode"` to `__all__` if one is defined.

- [ ] **Step 5: Run tests — they pass**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_env_file.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/env_file.py \
  packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/__init__.py \
  packages/python/vystak-provider-docker/tests/test_node_env_file.py
git commit -m "feat(provider-docker): DockerEnvFileNode — per-principal env file generation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Teach `WorkspaceSshKeygenNode` the default path

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace_ssh_keygen.py`
- Modify: `packages/python/vystak-provider-docker/tests/test_node_workspace_ssh_keygen.py`

- [ ] **Step 1: Write failing test for default-path host-file mode**

Add to `packages/python/vystak-provider-docker/tests/test_node_workspace_ssh_keygen.py`:

```python
def test_default_path_writes_keypair_to_host(tmp_path, monkeypatch, mock_docker_client):
    """When vault_client is None, keypair is written to .vystak/ssh/<agent>/
    with chmod 600 on private keys and 644 on public keys. Nothing pushed to
    Vault."""
    monkeypatch.chdir(tmp_path)
    from vystak_provider_docker.nodes.workspace_ssh_keygen import (
        WorkspaceSshKeygenNode,
    )

    node = WorkspaceSshKeygenNode(
        vault_client=None,
        docker_client=mock_docker_client,
        agent_name="assistant",
    )
    result = node.provision(context={})
    assert result.success

    ssh_dir = tmp_path / ".vystak" / "ssh" / "assistant"
    assert (ssh_dir / "client-key").exists()
    assert (ssh_dir / "client-key.pub").exists()
    assert (ssh_dir / "host-key").exists()
    assert (ssh_dir / "host-key.pub").exists()

    assert (ssh_dir / "client-key").stat().st_mode & 0o777 == 0o600
    assert (ssh_dir / "host-key").stat().st_mode & 0o777 == 0o600
    assert (ssh_dir / "client-key.pub").stat().st_mode & 0o777 == 0o644
    assert (ssh_dir / "host-key.pub").stat().st_mode & 0o777 == 0o644


def test_default_path_noop_on_second_apply(tmp_path, monkeypatch, mock_docker_client):
    """Re-running should preserve existing keys."""
    monkeypatch.chdir(tmp_path)
    from vystak_provider_docker.nodes.workspace_ssh_keygen import (
        WorkspaceSshKeygenNode,
    )

    node = WorkspaceSshKeygenNode(
        vault_client=None, docker_client=mock_docker_client, agent_name="assistant"
    )
    node.provision(context={})
    first = (tmp_path / ".vystak" / "ssh" / "assistant" / "client-key").read_bytes()

    # Second provision — should not regenerate
    result = node.provision(context={})
    assert result.success
    assert result.info["regenerated"] is False
    second = (tmp_path / ".vystak" / "ssh" / "assistant" / "client-key").read_bytes()
    assert first == second
```

Add a fixture for `mock_docker_client` at module top if not already present:

```python
@pytest.fixture
def mock_docker_client():
    """Mock docker client whose containers.run returns successfully after
    writing keys to the /out bind-mount. Matches the real alpine behavior."""
    from unittest.mock import MagicMock
    client = MagicMock()

    def _run(image, command, volumes, remove, **kwargs):
        # Extract the host tmpdir from the volumes dict
        host_dir = list(volumes.keys())[0]
        import subprocess
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", f"{host_dir}/client-key", "-q"],
            check=True,
        )
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", f"{host_dir}/host-key", "-q"],
            check=True,
        )
        return None

    client.containers.run.side_effect = _run
    return client
```

- [ ] **Step 2: Run tests — they fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_workspace_ssh_keygen.py -v -k default_path`
Expected: FAIL — existing node requires `vault_client` and tries to call `.kv_get()` on it.

- [ ] **Step 3: Branch `WorkspaceSshKeygenNode.provision()` on `vault_client is None`**

Replace the body of `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace_ssh_keygen.py` with:

```python
"""WorkspaceSshKeygenNode — generates SSH keypairs.

Default path (vault_client is None): writes four files to
.vystak/ssh/<agent>/ with chmod 600 on private keys, 644 on public keys.
Agent and workspace containers bind-mount these directly.

Vault path (vault_client provided): pushes the four pieces to Vault under
_vystak/workspace-ssh/<agent>/*. Vault Agent sidecars render into per-
principal /shared volumes. No host file is written.
"""

import pathlib
import tempfile

from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult


class WorkspaceSshKeygenNode(Provisionable):
    """One per agent with a workspace. Runs after Vault KV setup on the
    Vault path, or after network setup on the default path."""

    def __init__(self, *, vault_client, docker_client, agent_name: str):
        self._vault = vault_client
        self._docker = docker_client
        self._agent_name = agent_name

    @property
    def name(self) -> str:
        return f"workspace-ssh-keygen:{self._agent_name}"

    @property
    def depends_on(self) -> list[str]:
        return (
            ["hashi-vault:kv-setup"]
            if self._vault is not None
            else ["network"]
        )

    def _vault_path(self, key: str) -> str:
        return f"_vystak/workspace-ssh/{self._agent_name}/{key}"

    def _host_ssh_dir(self) -> pathlib.Path:
        return pathlib.Path(".vystak") / "ssh" / self._agent_name

    def provision(self, context: dict) -> ProvisionResult:
        if self._vault is not None:
            return self._provision_vault()
        return self._provision_host()

    def _provision_vault(self) -> ProvisionResult:
        key_names = ["client-key", "host-key", "client-key-pub", "host-key-pub"]
        have = all(
            self._vault.kv_get(self._vault_path(k)) is not None for k in key_names
        )
        if have:
            return ProvisionResult(
                name=self.name, success=True, info={"regenerated": False}
            )

        with tempfile.TemporaryDirectory() as td:
            client_priv, client_pub, host_priv, host_pub = self._keygen_via_docker(td)

        self._vault.kv_put(self._vault_path("client-key"), client_priv)
        self._vault.kv_put(self._vault_path("host-key"), host_priv)
        self._vault.kv_put(self._vault_path("client-key-pub"), client_pub)
        self._vault.kv_put(self._vault_path("host-key-pub"), host_pub)

        return ProvisionResult(
            name=self.name, success=True, info={"regenerated": True}
        )

    def _provision_host(self) -> ProvisionResult:
        host_dir = self._host_ssh_dir()
        existing = [
            host_dir / "client-key",
            host_dir / "client-key.pub",
            host_dir / "host-key",
            host_dir / "host-key.pub",
        ]
        if all(p.exists() for p in existing):
            return ProvisionResult(
                name=self.name, success=True, info={"regenerated": False}
            )

        host_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as td:
            client_priv, client_pub, host_priv, host_pub = self._keygen_via_docker(td)

        (host_dir / "client-key").write_text(client_priv)
        (host_dir / "client-key").chmod(0o600)
        (host_dir / "host-key").write_text(host_priv)
        (host_dir / "host-key").chmod(0o600)
        (host_dir / "client-key.pub").write_text(client_pub + "\n")
        (host_dir / "client-key.pub").chmod(0o644)
        (host_dir / "host-key.pub").write_text(host_pub + "\n")
        (host_dir / "host-key.pub").chmod(0o644)

        return ProvisionResult(
            name=self.name, success=True, info={"regenerated": True}
        )

    def _keygen_via_docker(self, td: str) -> tuple[str, str, str, str]:
        """Generate both keypairs inside a throwaway alpine, return pieces."""
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
        out = pathlib.Path(td)
        return (
            (out / "client-key").read_text(),
            (out / "client-key.pub").read_text().strip(),
            (out / "host-key").read_text(),
            (out / "host-key.pub").read_text().strip(),
        )

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        """Keys preserved by default on both paths; explicit rotate-ssh removes."""
        pass
```

- [ ] **Step 4: Run tests — default path and vault path tests both pass**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_workspace_ssh_keygen.py -v`
Expected: all tests PASS (existing Vault-path tests + new default-path tests).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace_ssh_keygen.py \
  packages/python/vystak-provider-docker/tests/test_node_workspace_ssh_keygen.py
git commit -m "feat(provider-docker): SSH keygen supports default (no-Vault) path

Default path writes keypair to .vystak/ssh/<agent>/ with chmod 600 on
private keys. Vault path unchanged (pushes to Vault, nothing on host).
Mutually exclusive — the property that 'Vault path's only sensitive host
file is init.json' is preserved.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Modify `DockerAgentNode` for default path

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py`
- Modify: `packages/python/vystak-provider-docker/tests/` (whichever file covers agent-node build behavior)

- [ ] **Step 1: Write failing test for default-path env + SSH bind-mount wiring**

Add to `packages/python/vystak-provider-docker/tests/test_provider.py` (or a dedicated `test_node_agent_default_path.py`):

```python
def test_agent_node_default_path_env_and_ssh_mount(tmp_path, monkeypatch):
    """Without Vault context, agent container gets env from provider-supplied
    dict and SSH bind-mounts the agent private key from .vystak/ssh/<agent>/."""
    monkeypatch.chdir(tmp_path)

    from unittest.mock import MagicMock
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak.schema.secret import Secret
    from vystak_provider_docker.nodes.agent import DockerAgentNode

    client = MagicMock()
    client.containers.get.side_effect = __import__("docker").errors.NotFound("x")
    container = MagicMock()
    container.ports = {"8000/tcp": [{"HostPort": "9000"}]}
    # Second call to containers.get — after run — returns the new container
    client.containers.get.side_effect = [
        __import__("docker").errors.NotFound("x"),
        container,
    ]

    anthropic = Provider(name="anthropic", type="anthropic")
    agent = Agent(
        name="assistant",
        model=Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-6"),
        secrets=[Secret(name="ANTHROPIC_API_KEY")],
    )
    code = type("_GC", (), {"files": {"server.py": "print('ok')", "requirements.txt": ""}, "entrypoint": "server.py"})()
    plan = type("_Plan", (), {"target_hash": "abc"})()

    node = DockerAgentNode(client, agent, code, plan)
    node.set_default_path_context(
        env={"ANTHROPIC_API_KEY": "sk-test"},
        ssh_host_dir=str(tmp_path / ".vystak" / "ssh" / "assistant"),
    )
    node.set_workspace_context(workspace_host="vystak-assistant-workspace")

    network_info = MagicMock()
    network_info.name = "vystak-net"
    context = {"network": MagicMock(info={"network": network_info})}

    result = node.provision(context)
    assert result.success

    _, kwargs = client.containers.run.call_args
    assert kwargs["environment"]["ANTHROPIC_API_KEY"] == "sk-test"
    # SSH client key bound in at the canonical path
    ssh_key_host = str(tmp_path / ".vystak" / "ssh" / "assistant" / "client-key")
    assert ssh_key_host in kwargs["volumes"]
    assert kwargs["volumes"][ssh_key_host]["bind"] == "/shared/ssh/id_ed25519"
    assert kwargs["volumes"][ssh_key_host]["mode"] == "ro"
```

- [ ] **Step 2: Run test — it fails (no `set_default_path_context` method)**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_provider.py::test_agent_node_default_path_env_and_ssh_mount -v`
Expected: FAIL — AttributeError on `set_default_path_context`.

- [ ] **Step 3: Add `set_default_path_context` and gate the Dockerfile/mount logic**

Edit `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py`:

In `__init__`, add a new attribute:

```python
        self._default_path_env: dict[str, str] | None = None
        self._default_path_ssh_host_dir: str | None = None
```

Add a new method under `set_workspace_context`:

```python
    def set_default_path_context(
        self,
        *,
        env: dict[str, str],
        ssh_host_dir: str | None = None,
    ) -> None:
        """Declare the default (no-Vault) delivery context.

        ``env`` is added directly to the container environment (equivalent to
        ``--env-file``). ``ssh_host_dir`` is the host directory produced by
        ``WorkspaceSshKeygenNode`` — files are individually bind-mounted into
        the container's /shared/ssh/ path so existing agent-side code (which
        reads /vystak/ssh/* via the symlink) works unchanged.
        """
        self._default_path_env = dict(env)
        self._default_path_ssh_host_dir = ssh_host_dir
```

Modify the Dockerfile-building block around lines 143-159. Replace the current conditionals with:

```python
            # Vault path uses the entrypoint shim to block until /shared/secrets.env
            # exists. Default path ships env via docker run `environment=` and
            # needs no shim.
            if self._vault_secrets_volume:
                from vystak_provider_docker.templates import generate_entrypoint_shim

                (build_dir / "entrypoint-shim.sh").write_text(generate_entrypoint_shim())
                dockerfile_content += (
                    "COPY entrypoint-shim.sh /vystak/entrypoint-shim.sh\n"
                    "RUN chmod +x /vystak/entrypoint-shim.sh\n"
                    'ENTRYPOINT ["/vystak/entrypoint-shim.sh"]\n'
                )
            if self._workspace_host:
                # Agent-side code reads SSH keys from /vystak/ssh/*. On the Vault
                # path, Vault Agent renders them into /shared/ssh/*; on the default
                # path, they are bind-mounted directly to /shared/ssh/*. Either
                # way, the symlink /vystak/ssh -> /shared/ssh does the job.
                dockerfile_content += (
                    "RUN mkdir -p /vystak && ln -sf /shared/ssh /vystak/ssh\n"
                )
            dockerfile_content += (
                f'CMD ["python", "{self._generated_code.entrypoint}"]\n'
            )
```

Modify the env-building block (around line 170+). Add at the end, before the `if self._workspace_host:` that sets `VYSTAK_WORKSPACE_HOST`:

```python
            # Default path delivers secrets via docker run environment=;
            # Vault path delivers via Vault Agent → /shared/secrets.env → shim.
            if self._default_path_env is not None:
                for key, value in self._default_path_env.items():
                    env[key] = value
```

Modify the volumes-building block (around line 197+). Replace the current conditional with:

```python
            # Build volumes
            volumes = {}
            for dep_name in self.depends_on:
                if dep_name == "network":
                    continue
                dep_result = context.get(dep_name)
                if dep_result and dep_result.info.get("engine") == "sqlite":
                    volumes[dep_result.info["volume_name"]] = {
                        "bind": "/data",
                        "mode": "rw",
                    }
            if self._vault_secrets_volume:
                # Vault-path: entire /shared populated by Vault Agent sidecar.
                volumes[self._vault_secrets_volume] = {
                    "bind": "/shared",
                    "mode": "ro",
                }
            elif self._default_path_ssh_host_dir:
                # Default path: bind-mount individual SSH files to /shared/ssh/*.
                from pathlib import Path as _Path

                ssh_dir = _Path(self._default_path_ssh_host_dir)
                volumes[str(ssh_dir / "client-key")] = {
                    "bind": "/shared/ssh/id_ed25519",
                    "mode": "ro",
                }
                volumes[str(ssh_dir / "host-key.pub")] = {
                    "bind": "/shared/ssh/host_key.pub",
                    "mode": "ro",
                }
```

- [ ] **Step 4: Run test — it passes**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_provider.py::test_agent_node_default_path_env_and_ssh_mount -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py \
  packages/python/vystak-provider-docker/tests/test_provider.py
git commit -m "feat(provider-docker): DockerAgentNode default-path wiring

Agent container accepts env dict + SSH host dir via set_default_path_context.
Entrypoint shim is gated on Vault presence — default path ships env directly
via docker run environment= and bind-mounts individual SSH files to /shared/ssh/*.
The /vystak/ssh symlink works identically on both paths.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Modify `DockerWorkspaceNode` for default path

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace.py`
- Modify: `packages/python/vystak-provider-docker/tests/test_node_workspace.py`

- [ ] **Step 1: Write failing test for default-path env + SSH mount on workspace**

Add to `packages/python/vystak-provider-docker/tests/test_node_workspace.py`:

```python
def test_workspace_default_path_env_and_ssh_mount(tmp_path, monkeypatch):
    """Without Vault context, workspace container gets env from provider-
    supplied dict and SSH bind-mounts (host-key, client-key.pub) from
    .vystak/ssh/<agent>/."""
    monkeypatch.chdir(tmp_path)

    from unittest.mock import MagicMock
    from vystak.schema.workspace import Workspace
    from vystak_provider_docker.nodes.workspace import DockerWorkspaceNode

    client = MagicMock()
    client.containers.get.side_effect = __import__("docker").errors.NotFound("x")
    container = MagicMock()
    container.ports = {}
    client.containers.get.side_effect = [
        __import__("docker").errors.NotFound("x"),
        container,
    ]

    ws = Workspace(name="ws", secrets=[])
    node = DockerWorkspaceNode(
        client=client,
        agent_name="assistant",
        workspace=ws,
        tools_dir=tmp_path / "tools",
    )
    node.set_default_path_context(
        env={"STRIPE_API_KEY": "sk-test"},
        ssh_host_dir=str(tmp_path / ".vystak" / "ssh" / "assistant"),
    )

    network_info = MagicMock()
    network_info.name = "vystak-net"
    context = {"network": MagicMock(info={"network": network_info})}

    result = node.provision(context)
    assert result.success

    _, kwargs = client.containers.run.call_args
    # Workspace also fails the test if the build step tries the image-build
    # — we allow it because client is mocked and containers.run is mocked.
    # Env is the important part:
    # Note: environment= is set only when default_path_env is provided.
    assert kwargs["environment"]["STRIPE_API_KEY"] == "sk-test"
    # SSH bind-mounts (workspace side)
    ssh_dir_host = str(tmp_path / ".vystak" / "ssh" / "assistant")
    assert f"{ssh_dir_host}/host-key" in kwargs["volumes"]
    assert kwargs["volumes"][f"{ssh_dir_host}/host-key"]["bind"] == "/shared/ssh_host_ed25519_key"
    assert f"{ssh_dir_host}/client-key.pub" in kwargs["volumes"]
    assert kwargs["volumes"][f"{ssh_dir_host}/client-key.pub"]["bind"] == "/shared/authorized_keys_vystak-agent"
```

Note: if `DockerWorkspaceNode.provision()` actually builds a Docker image (via `self._client.images.build(...)`) the mock needs to tolerate it; since `client` is a `MagicMock`, unspecified methods return MagicMock silently, which is fine.

- [ ] **Step 2: Run the test — it fails**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_workspace.py::test_workspace_default_path_env_and_ssh_mount -v`
Expected: FAIL — missing `set_default_path_context` method.

- [ ] **Step 3: Add default-path wiring to `DockerWorkspaceNode`**

Edit `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace.py`.

In `__init__`, add:

```python
        self._default_path_env: dict[str, str] | None = None
        self._default_path_ssh_host_dir: str | None = None
```

Add new method:

```python
    def set_default_path_context(
        self,
        *,
        env: dict[str, str],
        ssh_host_dir: str,
    ) -> None:
        """Declare the default (no-Vault) delivery context.

        Env dict is passed directly to docker run environment=. SSH host
        directory is bind-mounted piece-by-piece into the workspace's /shared
        path (matching the sshd_config expectations for
        /shared/ssh_host_ed25519_key and /shared/authorized_keys_vystak-agent).
        """
        self._default_path_env = dict(env)
        self._default_path_ssh_host_dir = ssh_host_dir
```

Change `depends_on` to reflect the default path (no vault-agent dependency):

```python
    @property
    def depends_on(self) -> list[str]:
        if self._default_path_env is not None:
            return [f"workspace-ssh-keygen:{self._agent_name}"]
        return [
            f"vault-agent:{self._agent_name}-workspace",
            f"workspace-ssh-keygen:{self._agent_name}",
        ]
```

Replace the volume-building block around line 124 with default-path awareness:

```python
        volumes: dict = {}
        if self._default_path_ssh_host_dir is not None:
            ssh_dir = Path(self._default_path_ssh_host_dir)
            volumes[str(ssh_dir / "host-key")] = {
                "bind": "/shared/ssh_host_ed25519_key",
                "mode": "ro",
            }
            volumes[str(ssh_dir / "client-key.pub")] = {
                "bind": "/shared/authorized_keys_vystak-agent",
                "mode": "ro",
            }
        else:
            # Vault path: /shared is populated by the workspace-principal
            # Vault Agent sidecar volume.
            volumes[self.secrets_volume_name] = {"bind": "/shared", "mode": "ro"}
        tmpfs: dict = {}
```

Add an `environment=` arg to the `containers.run(...)` call. Find the existing run call and add:

```python
        run_kwargs = dict(
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
        if self._default_path_env is not None:
            run_kwargs["environment"] = dict(self._default_path_env)

        self._client.containers.run(**run_kwargs)
```

- [ ] **Step 4: Run test — passes**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_workspace.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace.py \
  packages/python/vystak-provider-docker/tests/test_node_workspace.py
git commit -m "feat(provider-docker): DockerWorkspaceNode default-path wiring

Workspace container accepts env + SSH host dir via set_default_path_context.
sshd config paths (/shared/ssh_host_ed25519_key, /shared/authorized_keys_vystak-agent)
are satisfied by bind-mounting individual files from .vystak/ssh/<agent>/ —
matches the Vault path's filesystem view without needing a populated volume.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Branch `DockerProvider.apply()` on `vault is None`

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py`
- Modify: `packages/python/vystak-provider-docker/tests/test_provider.py`

- [ ] **Step 1: Write failing test asserting the default-path graph shape**

Add to `packages/python/vystak-provider-docker/tests/test_provider.py`:

```python
def test_apply_graph_default_path_no_vault_nodes(tmp_path, monkeypatch):
    """When vault is None, the build_graph_for_tests helper emits no Vault
    nodes — only network, env-file per principal, optional ssh-keygen,
    optional workspace, and agent."""
    monkeypatch.chdir(tmp_path)

    from unittest.mock import MagicMock
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.platform import Platform
    from vystak.schema.provider import Provider
    from vystak.schema.secret import Secret
    from vystak.schema.workspace import Workspace
    from vystak_provider_docker.provider import DockerProvider

    prov = DockerProvider.__new__(DockerProvider)
    prov._client = MagicMock()
    prov._generated_code = type("_GC", (), {"files": {}, "entrypoint": "server.py"})()
    prov._vault = None
    prov._env_values = {"ANTHROPIC_API_KEY": "sk-a", "STRIPE_API_KEY": "sk-s"}
    prov._force_sync = False
    prov._allow_missing = False

    docker_provider = Provider(name="docker", type="docker")
    anthropic = Provider(name="anthropic", type="anthropic")
    agent = Agent(
        name="assistant",
        model=Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-6"),
        platform=Platform(name="docker", type="docker", provider=docker_provider),
        secrets=[Secret(name="ANTHROPIC_API_KEY")],
        workspace=Workspace(name="ws", secrets=[Secret(name="STRIPE_API_KEY")]),
    )

    graph = prov._build_graph_for_tests(agent)
    node_names = set(graph.nodes.keys())

    # No Vault nodes
    assert not any("hashi-vault" in n for n in node_names), node_names
    assert not any("approle" in n for n in node_names), node_names
    assert not any(n.startswith("vault-agent:") for n in node_names), node_names

    # Default-path nodes present
    assert "network" in node_names
    assert "env-file:assistant-agent" in node_names
    assert "env-file:assistant-workspace" in node_names
    assert "workspace-ssh-keygen:assistant" in node_names
    assert "workspace:assistant" in node_names
    assert "agent:assistant" in node_names
```

- [ ] **Step 2: Run — fails (unknown node names or error accessing `.nodes`)**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_provider.py::test_apply_graph_default_path_no_vault_nodes -v`
Expected: FAIL — current `_build_graph_for_tests` still expects Vault context when workspace is present; may error on `_add_workspace_nodes` raising.

- [ ] **Step 3: Add `_add_default_path_nodes` helper and branch `apply()` + `_build_graph_for_tests`**

Edit `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py`.

Add a new helper method (before `apply`):

```python
    def _add_default_path_nodes(
        self, graph, *, tools_dir: Path | None = None
    ) -> tuple[dict[str, dict], str | None, str | None]:
        """Default delivery path — no Vault.

        Returns:
            principal_envs: ``{principal_name → env dict}`` for containers.
            ssh_host_dir: ``.vystak/ssh/<agent>/`` path when workspace is
                declared, else None.
            workspace_host: internal DNS name for the workspace container,
                or None when no workspace is declared.
        """
        from vystak_provider_docker.nodes import (
            DockerEnvFileNode,
            DockerWorkspaceNode,
            WorkspaceSshKeygenNode,
        )

        agent = self._agent
        principal_envs: dict[str, dict] = {}

        # Principals: agent + (workspace if declared)
        principals: dict[str, list[str]] = {}
        if agent and agent.secrets:
            principals[f"{agent.name}-agent"] = [s.name for s in agent.secrets]
        else:
            principals[f"{agent.name}-agent"] = []
        if agent and agent.workspace is not None:
            principals[f"{agent.name}-workspace"] = [
                s.name for s in agent.workspace.secrets
            ]

        for p_name, secret_names in principals.items():
            node = DockerEnvFileNode(
                principal_name=p_name,
                declared_secret_names=secret_names,
                env_values=self._env_values or {},
                allow_missing=self._allow_missing,
            )
            graph.add(node)
            # Capture a reference to the node for later lookup; actual env
            # dict becomes available after graph.execute() via context.
            principal_envs[p_name] = node  # placeholder; see below

        ssh_host_dir: str | None = None
        workspace_host: str | None = None
        if agent and agent.workspace is not None:
            keygen = WorkspaceSshKeygenNode(
                vault_client=None,
                docker_client=self._client,
                agent_name=agent.name,
            )
            graph.add(keygen)
            graph.add_dependency(keygen.name, "network")

            ssh_host_dir = str(
                Path(".vystak") / "ssh" / agent.name
            )

            tools_path = tools_dir or (Path.cwd() / "tools")
            ws_node = DockerWorkspaceNode(
                client=self._client,
                agent_name=agent.name,
                workspace=agent.workspace,
                tools_dir=tools_path,
            )
            graph.add(ws_node)
            graph.add_dependency(ws_node.name, keygen.name)
            graph.add_dependency(
                ws_node.name, f"env-file:{agent.name}-workspace"
            )
            workspace_host = ws_node.container_name

        return principal_envs, ssh_host_dir, workspace_host
```

Now: the tricky bit is that the env dict is known only after the env-file node runs. Downstream container nodes need it. The cleanest pattern matches what vault-agent does — use a late-bound wrapper that reads from the provision context. Add a small helper class:

```python
class _LateBoundDefaultAgentConfig:
    """Wires env dict from the env-file node's ProvisionResult into the
    agent node at run time."""

    def __init__(
        self,
        *,
        agent_node,
        env_file_node_name: str,
        ssh_host_dir: str | None,
        workspace_host: str | None,
    ):
        self._agent_node = agent_node
        self._env_file = env_file_node_name
        self._ssh_host_dir = ssh_host_dir
        self._workspace_host = workspace_host

    @property
    def name(self) -> str:
        return f"{self._agent_node.name}-default-wire"

    @property
    def depends_on(self) -> list[str]:
        deps = [self._env_file]
        return deps

    def provision(self, context: dict) -> ProvisionResult:
        env = context[self._env_file].info["env"]
        self._agent_node.set_default_path_context(
            env=env, ssh_host_dir=self._ssh_host_dir
        )
        if self._workspace_host:
            self._agent_node.set_workspace_context(
                workspace_host=self._workspace_host
            )
        return ProvisionResult(name=self.name, success=True, info={})

    def destroy(self) -> None:
        pass
```

Similar for workspace.

Actually, the simplest approach: since `apply()` already executes the graph sequentially and captures results, just execute the env-file node's `.provision({})` eagerly inside `apply()` to get the env dict before creating the dependent nodes. Update the helper to construct container nodes after env is known:

Replace the `_add_default_path_nodes` body above with the eager version:

```python
    def _add_default_path_nodes(
        self, graph, *, tools_dir: Path | None = None
    ) -> tuple[dict[str, dict], str | None, str | None]:
        """Default delivery path — eagerly resolves env-file nodes so
        container nodes can be configured with env dicts at graph-build time.
        """
        from vystak_provider_docker.nodes import (
            DockerEnvFileNode,
            DockerWorkspaceNode,
            WorkspaceSshKeygenNode,
        )

        agent = self._agent
        resolved_envs: dict[str, dict] = {}

        principals: dict[str, list[str]] = {
            f"{agent.name}-agent": [s.name for s in (agent.secrets or [])],
        }
        if agent.workspace is not None:
            principals[f"{agent.name}-workspace"] = [
                s.name for s in agent.workspace.secrets
            ]

        for p_name, secret_names in principals.items():
            node = DockerEnvFileNode(
                principal_name=p_name,
                declared_secret_names=secret_names,
                env_values=self._env_values or {},
                allow_missing=self._allow_missing,
            )
            # Eager-resolve so container nodes can be configured
            result = node.provision(context={})
            if not result.success:
                raise RuntimeError(result.error or "env-file node failed")
            resolved_envs[p_name] = result.info["env"]
            # Still add to graph for plan/observability, but mark as
            # already-executed by wrapping in a passthrough.
            graph.add(_ResolvedPassthroughNode(result, name_hint=node.name))

        ssh_host_dir: str | None = None
        workspace_host: str | None = None
        if agent.workspace is not None:
            keygen = WorkspaceSshKeygenNode(
                vault_client=None,
                docker_client=self._client,
                agent_name=agent.name,
            )
            graph.add(keygen)
            graph.add_dependency(keygen.name, "network")

            ssh_host_dir = str(Path(".vystak") / "ssh" / agent.name)

            tools_path = tools_dir or (Path.cwd() / "tools")
            ws_node = DockerWorkspaceNode(
                client=self._client,
                agent_name=agent.name,
                workspace=agent.workspace,
                tools_dir=tools_path,
            )
            ws_node.set_default_path_context(
                env=resolved_envs[f"{agent.name}-workspace"],
                ssh_host_dir=ssh_host_dir,
            )
            graph.add(ws_node)
            graph.add_dependency(ws_node.name, keygen.name)
            workspace_host = ws_node.container_name

        return resolved_envs, ssh_host_dir, workspace_host
```

Add the passthrough helper class near `_LateBoundUnsealNode`:

```python
class _ResolvedPassthroughNode(Provisionable):
    """Pre-resolved ProvisionResult exposed as a node for graph observability.
    Used when a node's side effects complete at graph-build time (e.g. the
    default-path env-file generation)."""

    def __init__(self, result: ProvisionResult, *, name_hint: str):
        self._result = result
        self._name = name_hint

    @property
    def name(self) -> str:
        return self._name

    @property
    def depends_on(self) -> list[str]:
        return []

    def provision(self, context: dict) -> ProvisionResult:
        return self._result

    def destroy(self) -> None:
        pass
```

Now branch `apply()`. Find the block around line 540 that reads:

```python
            if self._vault is not None:
                from vystak.schema.common import VaultType

                if self._vault.type is VaultType.VAULT:
                    vault_volume_map = self._add_vault_nodes(graph)
                    workspace_host = self._add_workspace_nodes(graph)
```

Replace with:

```python
            default_envs: dict[str, dict] = {}
            ssh_host_dir: str | None = None
            if self._vault is not None:
                from vystak.schema.common import VaultType

                if self._vault.type is VaultType.VAULT:
                    vault_volume_map = self._add_vault_nodes(graph)
                    workspace_host = self._add_workspace_nodes(graph)
            else:
                default_envs, ssh_host_dir, workspace_host = (
                    self._add_default_path_nodes(graph)
                )
```

Then after `agent_node = DockerAgentNode(...)` and its Vault wiring, add default-path wiring:

```python
            if agent_principal and agent_principal in default_envs:
                agent_node.set_default_path_context(
                    env=default_envs[agent_principal],
                    ssh_host_dir=ssh_host_dir,
                )
```

Mirror the same changes in `_build_graph_for_tests`.

- [ ] **Step 4: Run the graph-shape test — passes**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_provider.py::test_apply_graph_default_path_no_vault_nodes -v`
Expected: PASS.

- [ ] **Step 5: Run the full docker provider test suite — all existing Vault-path tests still pass**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/ -v -m "not docker" --ignore=packages/python/vystak-provider-docker/tests/test_vault_integration.py`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py \
  packages/python/vystak-provider-docker/tests/test_provider.py
git commit -m "feat(provider-docker): DockerProvider.apply() branches on vault=None

Default path assembles: network + env-file per principal + workspace SSH
keygen + workspace container + agent container — no Vault nodes. Existing
Vault path is unchanged; gated on vault.type == VAULT.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Docker-marked integration test for default path

**Files:**
- Create: `packages/python/vystak-provider-docker/tests/test_default_path_integration.py`

- [ ] **Step 1: Write the integration test**

Create `packages/python/vystak-provider-docker/tests/test_default_path_integration.py`:

```python
"""Docker-marked end-to-end test: deploy agent+workspace+secrets without
a Vault, verify per-container isolation."""

import os
import subprocess
import time
from pathlib import Path

import pytest


pytestmark = pytest.mark.docker


def _run(cmd: list[str], check: bool = True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check, **kw)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Minimal project directory with a workspace-declaring agent, no Vault."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vystak.yaml").write_text(
        """
providers:
  docker:
    type: docker
  anthropic:
    type: anthropic
platforms:
  docker:
    provider: docker
    type: docker
models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-4-6
agents:
  - name: isolation-test
    model: sonnet
    platform: docker
    secrets:
      - name: ANTHROPIC_API_KEY
    workspace:
      name: ws
      persistence: ephemeral
      secrets:
        - name: STRIPE_API_KEY
""".strip()
    )
    (tmp_path / ".env").write_text(
        "ANTHROPIC_API_KEY=sk-agent-sentinel\n"
        "STRIPE_API_KEY=sk-workspace-sentinel\n"
    )
    (tmp_path / "tools").mkdir()
    yield tmp_path


def test_default_path_isolates_workspace_secret_from_agent(project):
    """Apply the config; exec into the agent container; assert the workspace
    secret is not present in its env."""
    # Apply
    result = _run(["vystak", "apply", "--yes"])
    assert result.returncode == 0, result.stderr

    # Wait briefly for containers to start
    time.sleep(2)

    # Check agent container env does NOT contain STRIPE_API_KEY
    agent_env = _run(
        ["docker", "exec", "vystak-isolation-test", "env"], check=True
    ).stdout
    assert "STRIPE_API_KEY" not in agent_env
    assert "ANTHROPIC_API_KEY=sk-agent-sentinel" in agent_env

    # Check workspace container env DOES contain STRIPE_API_KEY and NOT ANTHROPIC_API_KEY
    ws_env = _run(
        ["docker", "exec", "vystak-isolation-test-workspace", "env"], check=True
    ).stdout
    assert "STRIPE_API_KEY=sk-workspace-sentinel" in ws_env
    assert "ANTHROPIC_API_KEY" not in ws_env

    # Cleanup
    _run(["vystak", "destroy", "--yes"], check=False)
```

- [ ] **Step 2: Run it (requires Docker running)**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_default_path_integration.py -v -m docker`
Expected: PASS if Docker daemon is up. SKIP if not.

- [ ] **Step 3: Commit**

```bash
git add packages/python/vystak-provider-docker/tests/test_default_path_integration.py
git commit -m "test(provider-docker): docker-marked default-path isolation test

Deploys agent + workspace + per-container secrets without a Vault and
asserts each container sees only its own declared secrets.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Verify full Phase 1 test suite is green

- [ ] **Step 1: Run every non-docker-marked test**

Run: `just test-python` (or `uv run pytest packages/python/ -v -m "not docker"`)
Expected: PASS. Any failure is a Phase 1 bug — fix inline before moving on.

- [ ] **Step 2: Run docker-marked integration tests (requires Docker)**

Run: `uv run pytest packages/python/ -v -m docker`
Expected: PASS.

- [ ] **Step 3: Lint + typecheck**

Run: `just lint-python`
Run: `just fmt-python` (apply autofixes if any)
Expected: clean.

- [ ] **Step 4: Push a PR branch and open PR for Phase 1**

```bash
git push -u origin feat/secret-manager-simplification-p1
gh pr create --title "Secret manager simplification — Phase 1 (schema + Docker default path)" --body "$(cat <<'EOF'
## Summary
- Remove three vault-required validators from `multi_loader.py`
- Add `DockerEnvFileNode` for per-principal env delivery on the default path
- Teach `WorkspaceSshKeygenNode` to write host files when no Vault is declared
- Branch `DockerAgentNode`, `DockerWorkspaceNode`, and `DockerProvider.apply()` on vault presence
- New docker-marked integration test exercises the default path end-to-end

Follows `docs/superpowers/specs/2026-04-22-secret-manager-simplification-design.md`.
Zero deletions of Vault-specific code — all Vault paths are bit-for-bit unchanged when declared.

## Test plan
- [x] `just test-python` green
- [x] `just lint-python` clean
- [x] Docker-marked integration test `test_default_path_integration.py` passes against a live daemon
- [x] All existing Vault-path tests still pass

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Phase 2 — Azure default path confirmation

### Task 9: Investigate ACAAppNode multi-container secret scoping

**Files (read-only investigation):**
- `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py`
- `packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py`

- [ ] **Step 1: Read the current ACAAppNode, look for multi-container support**

Run: `grep -n 'containers' packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py | head -30`
Expected: Lines showing how containers array is constructed.

Look at how `env[].secretRef` is populated per container and whether workspace secrets flow into workspace-container env when `vault is None`.

- [ ] **Step 2: Write a test that documents the expected behavior**

Add to `packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py`:

```python
def test_aca_app_default_path_workspace_secretref_scoping():
    """Without a Vault, each container's env[].secretRef entries pull from
    inline configuration.secrets, and each container gets only its own
    principal's declared secrets."""
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.platform import Platform
    from vystak.schema.provider import Provider
    from vystak.schema.secret import Secret
    from vystak.schema.workspace import Workspace
    from vystak_provider_azure.nodes.aca_app import ACAAppNode

    azure = Provider(name="azure", type="azure", config={"resource_group": "rg"})
    anthropic = Provider(name="anthropic", type="anthropic")
    agent = Agent(
        name="assistant",
        model=Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-6"),
        platform=Platform(name="aca", type="container-apps", provider=azure),
        secrets=[Secret(name="ANTHROPIC_API_KEY")],
        workspace=Workspace(name="ws", secrets=[Secret(name="STRIPE_API_KEY")]),
    )

    # Simulate env values (deployer-supplied) — no Vault
    env_values = {
        "ANTHROPIC_API_KEY": "sk-a-val",
        "STRIPE_API_KEY": "sk-s-val",
    }

    node = ACAAppNode(
        agent=agent,
        env_values=env_values,
        vault=None,
        # Other constructor args per the existing signature...
    )

    template = node.build_aca_template()

    # Revision-level secrets contain both
    secret_names = {s["name"] for s in template["properties"]["configuration"]["secrets"]}
    assert {"anthropic-api-key", "stripe-api-key"} <= secret_names

    # Per-container scoping
    containers = template["properties"]["template"]["containers"]
    agent_container = next(c for c in containers if c["name"] == "assistant")
    ws_container = next(c for c in containers if c["name"] == "workspace")

    agent_env_names = {e["name"] for e in agent_container["env"]}
    ws_env_names = {e["name"] for e in ws_container["env"]}

    assert "ANTHROPIC_API_KEY" in agent_env_names
    assert "STRIPE_API_KEY" not in agent_env_names
    assert "STRIPE_API_KEY" in ws_env_names
    assert "ANTHROPIC_API_KEY" not in ws_env_names
```

- [ ] **Step 2b: Run the test — this is the investigation result**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py::test_aca_app_default_path_workspace_secretref_scoping -v`
Expected: UNKNOWN — either PASS (feature already works — skip to commit), FAIL (must implement multi-container scoping), or ERROR on constructor signature (adapt the test to match the real signature).

- [ ] **Step 3: If test fails, implement per-container secretRef scoping in ACAAppNode**

(Defer-fix pattern.) If the test currently fails, read `ACAAppNode.build_aca_template()` and adjust the container-env generation so that:

1. The revision-level `configuration.secrets` pool contains every declared secret across principals (using inline `value` when no Vault, `keyVaultUrl` + `identity` when Vault is declared).
2. Each container's `env[]` references only its own principal's secrets via `secretRef`.

Concretely, change the container-env loop from:

```python
# pseudocode — current likely shape:
for secret in agent.secrets:
    container_env.append({"name": secret.name, "secretRef": normalize(secret.name)})
```

to iterate over the specific principal's secrets:

```python
def _env_for_principal(principal_secrets):
    return [
        {"name": s.name, "secretRef": _normalize_secret_name(s.name)}
        for s in principal_secrets
    ]

agent_container["env"].extend(_env_for_principal(agent.secrets))
if agent.workspace is not None:
    workspace_container["env"].extend(
        _env_for_principal(agent.workspace.secrets)
    )
```

If the current code lumps all secrets into every container, narrow it to the principal whose container is being built.

Re-run the test until it passes.

- [ ] **Step 4: Run the full azure provider test suite**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py \
  packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py
git commit -m "fix(provider-azure): per-container secretRef scoping for workspace on default path

Ensures each container's env[] references only its own principal's declared
secrets — agent container has agent secrets, workspace container has workspace
secrets. Works identically on the inline-secrets (no-Vault) path and the
Vault path; the only difference is the source of the secret values.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Open Phase 2 PR

- [ ] **Step 1: Push + PR**

```bash
git push -u origin feat/secret-manager-simplification-p2
gh pr create --title "Secret manager simplification — Phase 2 (Azure default-path confirmation)" --body "$(cat <<'EOF'
## Summary
- Verify and/or fix multi-container inline-secret scoping in `ACAAppNode`
- Add unit test asserting per-container env boundary on the default (no-Vault) path

## Test plan
- [x] `just test-python` green
- [x] New test `test_aca_app_default_path_workspace_secretref_scoping` passes

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Phase 3 — CLI + adapter

### Task 11: Branch `secrets list/push/diff` on Vault presence

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py`
- Modify: `packages/python/vystak-cli/tests/test_secrets_command.py`

- [ ] **Step 1: Write failing test — `vystak secrets list` with no Vault shows declared secrets + .env presence**

Add to `packages/python/vystak-cli/tests/test_secrets_command.py`:

```python
def test_secrets_list_default_path(tmp_path, monkeypatch, capsys):
    """Without Vault, `list` shows declared secrets and whether they exist in .env."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vystak.yaml").write_text(
        """
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  docker: {provider: docker, type: docker}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-6}
agents:
  - name: a
    model: sonnet
    platform: docker
    secrets: [{name: PRESENT}, {name: MISSING}]
""".strip()
    )
    (tmp_path / ".env").write_text("PRESENT=x\n")

    from vystak_cli.commands.secrets import list_secrets

    list_secrets()  # prints to stdout
    out = capsys.readouterr().out
    assert "PRESENT" in out
    assert "MISSING" in out
    assert "in .env" in out or "present" in out.lower()
    assert "missing" in out.lower()
```

- [ ] **Step 2: Run — fails**

Run: `uv run pytest packages/python/vystak-cli/tests/test_secrets_command.py::test_secrets_list_default_path -v`
Expected: FAIL — existing code probably asserts Vault is present before listing.

- [ ] **Step 3: Branch `list_secrets` on Vault presence**

Edit `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py`.

Find the existing `list_secrets` function and add a Vault-None branch at the top:

```python
def list_secrets():
    agents, channels, vault = _load_deployment()
    declared = _collect_declared_secrets(agents, channels)
    env_values = _load_dotenv()

    if vault is None:
        print("Secrets (default path — delivered via --env-file per container):")
        print()
        for name in sorted(declared):
            status = "present in .env" if name in env_values else "MISSING from .env"
            print(f"  {name}: {status}")
        return

    # Existing Vault-dispatch path unchanged below
    ...
```

Where `_collect_declared_secrets` walks the agents/channels and returns all declared names, and `_load_dotenv()` is the existing helper.

- [ ] **Step 4: Run the test — passes**

Expected: PASS.

- [ ] **Step 5: Mirror the pattern for `push`, `set`, `diff` in the same file**

Add the same `if vault is None:` guard at the top of each command, returning before the Vault dispatch:

```python
def push_secrets(names: list[str] | None = None, force: bool = False, allow_missing: bool = False):
    agents, channels, vault = _load_deployment()
    if vault is None:
        print("Default path: env-file generation happens at 'vystak apply'.")
        print("No out-of-band push needed — secret values flow from .env at apply time.")
        return
    # Existing Vault/KV dispatch below unchanged
    ...


def set_secret(assignment: str):
    """vystak secrets set NAME=VAL"""
    agents, channels, vault = _load_deployment()
    if vault is None:
        print(
            "Default path: `secrets set` is not supported. "
            "Edit .env directly, then run `vystak apply` to materialize.",
            file=sys.stderr,
        )
        sys.exit(2)
    # Existing Vault/KV dispatch below unchanged
    ...


def diff_secrets():
    agents, channels, vault = _load_deployment()
    if vault is None:
        declared = _collect_declared_secrets(agents, channels)
        env_values = _load_dotenv()
        env_file_dir = Path(".vystak") / "env"
        materialized: set[str] = set()
        if env_file_dir.exists():
            for f in env_file_dir.glob("*.env"):
                for line in f.read_text().splitlines():
                    if "=" in line:
                        materialized.add(line.split("=", 1)[0])
        for name in sorted(declared):
            in_env = "yes" if name in env_values else "no"
            in_materialized = "yes" if name in materialized else "no"
            print(f"  {name}: .env={in_env}  .vystak/env={in_materialized}")
        return
    # Existing Vault/KV dispatch below unchanged
    ...
```

Add matching tests for each in `test_secrets_command.py`:

```python
def test_secrets_push_default_path_is_noop(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vystak.yaml").write_text(_MINIMAL_NO_VAULT_YAML)
    (tmp_path / ".env").write_text("X=y\n")
    from vystak_cli.commands.secrets import push_secrets
    push_secrets()
    assert "env-file generation happens at 'vystak apply'" in capsys.readouterr().out


def test_secrets_set_default_path_refuses(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vystak.yaml").write_text(_MINIMAL_NO_VAULT_YAML)
    from vystak_cli.commands.secrets import set_secret
    with pytest.raises(SystemExit):
        set_secret("X=y")
    assert "Edit .env directly" in capsys.readouterr().err


def test_secrets_diff_default_path(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vystak.yaml").write_text(_MINIMAL_NO_VAULT_YAML)
    (tmp_path / ".env").write_text("K=x\n")
    env_dir = tmp_path / ".vystak" / "env"
    env_dir.mkdir(parents=True)
    (env_dir / "a-agent.env").write_text("K=x\n")
    from vystak_cli.commands.secrets import diff_secrets
    diff_secrets()
    out = capsys.readouterr().out
    assert ".env=yes" in out
    assert ".vystak/env=yes" in out
```

Where `_MINIMAL_NO_VAULT_YAML` is the same single-agent-with-one-secret config as `test_secrets_list_default_path`. Run all four together until green.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/secrets.py \
  packages/python/vystak-cli/tests/test_secrets_command.py
git commit -m "feat(cli): vystak secrets list/push/set/diff branch on Vault presence

Default-path behaviors:
- list: shows declared + .env presence, no KV/Vault calls
- push: info message (env-file generated at apply)
- set: rejected with pointer to editing .env directly
- diff: declared vs .env vs .vystak/env/*

Vault paths unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: `vystak plan` — add `EnvFiles:` section and orphan detection

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/plan.py`
- Modify: `packages/python/vystak-cli/tests/test_plan_secret_manager.py`

- [ ] **Step 1: Write failing test — plan with no Vault shows EnvFiles section**

Add to `packages/python/vystak-cli/tests/test_plan_secret_manager.py`:

```python
def test_plan_default_path_shows_env_files_section(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vystak.yaml").write_text("""
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  docker: {provider: docker, type: docker}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-6}
agents:
  - name: a
    model: sonnet
    platform: docker
    secrets: [{name: K}]
    workspace: {name: ws, secrets: [{name: W}]}
""".strip())
    (tmp_path / ".env").write_text("K=x\nW=y\n")

    from vystak_cli.commands.plan import plan as run_plan

    run_plan()
    out = capsys.readouterr().out
    assert "EnvFiles:" in out
    assert "a-agent" in out
    assert "a-workspace" in out
    assert "Vault:" not in out
```

- [ ] **Step 2: Write failing test — plan detects orphan Vault resources when config has no Vault but resources exist on host**

```python
def test_plan_detects_orphan_vault_resources(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    # Config has no Vault
    (tmp_path / "vystak.yaml").write_text("""
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  docker: {provider: docker, type: docker}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-6}
agents:
  - name: a
    model: sonnet
    platform: docker
    secrets: [{name: K}]
""".strip())
    (tmp_path / ".env").write_text("K=x\n")
    # State indicates prior Vault-backed deploy
    (tmp_path / ".vystak" / "vault").mkdir(parents=True)
    (tmp_path / ".vystak" / "vault" / "init.json").write_text("{}")

    from vystak_cli.commands.plan import plan as run_plan

    run_plan()
    out = capsys.readouterr().out
    assert "Orphan" in out
    assert "destroy --delete-vault" in out
```

- [ ] **Step 3: Run both tests — fail**

Expected: FAIL — sections not yet emitted.

- [ ] **Step 4: Add section rendering + orphan detection to plan.py**

Edit `packages/python/vystak-cli/src/vystak_cli/commands/plan.py`. Find the section renderer and add:

```python
def _render_env_files_section(agents, env_values):
    print("EnvFiles:")
    for agent in agents:
        principals = [(f"{agent.name}-agent", [s.name for s in agent.secrets])]
        if agent.workspace is not None:
            principals.append(
                (f"{agent.name}-workspace", [s.name for s in agent.workspace.secrets])
            )
        for p_name, secret_names in principals:
            resolved = sum(1 for n in secret_names if n in env_values)
            missing = sum(1 for n in secret_names if n not in env_values)
            status = f"{resolved}/{len(secret_names)} resolved"
            if missing:
                status += f", {missing} MISSING from .env"
            print(f"  {p_name}: {status}")
    print()


def _detect_orphan_vault_resources(vault_is_none: bool) -> list[str]:
    if not vault_is_none:
        return []
    orphans: list[str] = []
    if (Path(".vystak") / "vault" / "init.json").exists():
        orphans.append(".vystak/vault/init.json (Hashi Vault state)")
    # Docker containers/volumes — best-effort detection
    try:
        import docker as _docker

        client = _docker.from_env()
        for c in client.containers.list(all=True, filters={"name": "vystak-vault"}):
            orphans.append(f"container: {c.name}")
        for c in client.containers.list(
            all=True, filters={"name": "-vault-agent"}
        ):
            orphans.append(f"container: {c.name}")
        for v in client.volumes.list():
            if v.name.startswith("vystak-") and (
                v.name.endswith("-approle")
                or v.name.endswith("-secrets")
                or v.name == "vystak-vault-data"
            ):
                orphans.append(f"volume: {v.name}")
    except Exception:
        pass  # Docker not reachable — skip
    return orphans


def _render_orphans(orphans: list[str]) -> None:
    if not orphans:
        return
    print("Orphan resources detected:")
    for o in orphans:
        print(f"  {o}")
    print()
    print("These are from a previous Vault-backed deploy. To clean up:")
    print("  vystak destroy --delete-vault")
    print("  vystak apply")
    print()
```

Wire these calls into the top-level `plan()` function, emitting `Vault:` / `Identities:` / `Grants:` only when `vault is not None` and `EnvFiles:` only when `vault is None`.

- [ ] **Step 5: Run tests — pass**

Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/plan.py \
  packages/python/vystak-cli/tests/test_plan_secret_manager.py
git commit -m "feat(cli): plan output — EnvFiles section + orphan Vault detection

When no Vault is declared, plan emits an EnvFiles: section showing each
principal's resolved/missing secret count. If orphan Vault resources
(init.json, vystak-vault container/volumes) are detected, a migration
warning is printed with the cleanup command.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: `vystak destroy` — clean default-path state files

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/destroy.py`

- [ ] **Step 1: Write failing test**

Add to the relevant destroy tests file (or create `test_destroy_default_path.py`):

```python
def test_destroy_removes_default_path_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env_dir = tmp_path / ".vystak" / "env"
    ssh_dir = tmp_path / ".vystak" / "ssh" / "assistant"
    env_dir.mkdir(parents=True)
    ssh_dir.mkdir(parents=True)
    (env_dir / "assistant-agent.env").write_text("X=y")
    (ssh_dir / "client-key").write_text("stub")

    from vystak_cli.commands.destroy import _cleanup_default_path_state

    _cleanup_default_path_state(agent_names=["assistant"])
    assert not (env_dir / "assistant-agent.env").exists()
    assert not ssh_dir.exists()
```

- [ ] **Step 2: Add `_cleanup_default_path_state` and wire into destroy flow**

Edit `packages/python/vystak-cli/src/vystak_cli/commands/destroy.py`:

```python
def _cleanup_default_path_state(*, agent_names: list[str]) -> None:
    """Remove .vystak/env/*.env and .vystak/ssh/<agent>/* for destroyed agents.
    Called on the default (no-Vault) path only."""
    from pathlib import Path
    import shutil

    env_dir = Path(".vystak") / "env"
    if env_dir.exists():
        for agent in agent_names:
            for suffix in ("-agent.env", "-workspace.env"):
                p = env_dir / f"{agent}{suffix}"
                if p.exists():
                    p.unlink()

    ssh_root = Path(".vystak") / "ssh"
    if ssh_root.exists():
        for agent in agent_names:
            d = ssh_root / agent
            if d.exists():
                shutil.rmtree(d)
```

Call it in `destroy()` when `vault is None`.

- [ ] **Step 3: Run — passes**

Run: `uv run pytest packages/python/vystak-cli/tests/ -v -k destroy`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/destroy.py \
  packages/python/vystak-cli/tests/
git commit -m "feat(cli): vystak destroy cleans default-path state

Removes .vystak/env/<principal>.env and .vystak/ssh/<agent>/ on the
default path. --delete-vault behavior unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Gate LangChain adapter shim emission on Vault presence

**Files:**
- Modify: `packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py`
- Modify: `packages/python/vystak-adapter-langchain/tests/`

- [ ] **Step 1: Read the current shim-emission code**

Run: `grep -n 'entrypoint-shim\|entrypoint_shim' packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain/templates.py`
Expected: Lines emitting Dockerfile ENTRYPOINT + shim file.

- [ ] **Step 2: Write failing test — adapter emits NO shim when Vault is absent**

Add to an adapter test file:

```python
def test_adapter_does_not_emit_shim_when_no_vault():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak_adapter_langchain import generate_code

    anthropic = Provider(name="anthropic", type="anthropic")
    agent = Agent(
        name="a",
        model=Model(name="s", provider=anthropic, model_name="claude-sonnet-4-6"),
    )
    code = generate_code(agent, vault=None)
    df = code.files.get("Dockerfile", "")
    assert "entrypoint-shim" not in df
    assert "entrypoint-shim.sh" not in code.files


def test_adapter_emits_shim_when_vault_declared():
    from vystak.schema.agent import Agent
    from vystak.schema.common import VaultType
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak.schema.vault import Vault
    from vystak_adapter_langchain import generate_code

    anthropic = Provider(name="anthropic", type="anthropic")
    docker = Provider(name="docker", type="docker")
    agent = Agent(
        name="a",
        model=Model(name="s", provider=anthropic, model_name="claude-sonnet-4-6"),
    )
    vault = Vault(name="v", provider=docker, type=VaultType.VAULT)
    code = generate_code(agent, vault=vault)
    df = code.files.get("Dockerfile", "")
    assert "entrypoint-shim" in df
```

- [ ] **Step 3: Run — fails (shim always emitted)**

Expected: FAIL — shim emission is unconditional today.

- [ ] **Step 4: Gate the shim-emitting code path on a `vault` parameter threading through `generate_code`**

Adjust `generate_code` (and whatever function emits the shim) to accept `vault: Vault | None = None` and skip shim emission when `vault is None`. Thread the parameter through call sites; the docker provider passes `self._vault` to the adapter.

- [ ] **Step 5: Run tests — pass**

Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-adapter-langchain/
git commit -m "feat(adapter-langchain): gate entrypoint-shim on Vault presence

Shim waits for /shared/secrets.env to appear; not needed on the default
path where env ships via docker run environment=. Emitted only when
Vault is declared.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 15: Open Phase 3 PR

- [ ] **Step 1: Push + PR**

```bash
git push -u origin feat/secret-manager-simplification-p3
gh pr create --title "Secret manager simplification — Phase 3 (CLI + adapter)" --body "$(cat <<'EOF'
## Summary
- `vystak secrets list/push/set/diff` branch on Vault presence
- `vystak plan` emits EnvFiles: section on default path and detects orphan Vault resources
- `vystak destroy` cleans .vystak/env/ and .vystak/ssh/ on default path
- LangChain adapter gates entrypoint-shim emission on Vault presence

## Test plan
- [x] `just test-python` green
- [x] New unit tests for each CLI subcommand default-path branch
- [x] Plan orphan-detection test exercises filesystem + Docker-list paths

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Phase 4 — Examples + docs

### Task 16: Simplify `examples/docker-workspace-nodejs`

**Files:**
- Modify: `examples/docker-workspace-nodejs/vystak.py` (or `vystak.yaml`)
- Modify: `examples/docker-workspace-nodejs/README.md`

- [ ] **Step 1: Read the current example**

Run: `cat examples/docker-workspace-nodejs/vystak.py 2>/dev/null || cat examples/docker-workspace-nodejs/vystak.yaml`

- [ ] **Step 2: Remove the `vault:` block**

Edit the example config to drop the entire Vault declaration. Keep agent + workspace + secrets unchanged.

- [ ] **Step 3: Update the README**

Edit `examples/docker-workspace-nodejs/README.md` to:
1. Remove any mention of Vault init, unseal keys, `init.json`.
2. Add a "Secrets" section explaining that `.env` values are delivered per-container via `--env-file`.
3. Add a "Want rotation/audit? Opt into Vault" appendix section showing the same example with a `vault:` block added back.

- [ ] **Step 4: Run the example end-to-end (if Docker is available)**

Run: `cd examples/docker-workspace-nodejs && vystak apply --yes && sleep 5 && docker ps && vystak destroy --yes`
Expected: 2 containers running (agent + workspace), no Vault container, destroy leaves nothing behind.

- [ ] **Step 5: Commit**

```bash
git add examples/docker-workspace-nodejs/
git commit -m "examples: docker-workspace-nodejs drops Vault block

Uses the new default path — 2 containers instead of 5, ~10x faster cold start.
README gains an appendix showing how to opt back into Vault for rotation/audit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 17: Update `docs/getting-started.md` secrets section

**Files:**
- Modify: `docs/getting-started.md`

- [ ] **Step 1: Read the current secrets section**

Run: `grep -n -A 30 -i 'secrets\|vault' docs/getting-started.md | head -60`

- [ ] **Step 2: Rewrite the secrets section**

Update to present the default path first:

1. "Declare secrets on the agent or workspace. Values come from `.env`."
2. "Per-container isolation: each principal's declared secrets land only in its container's env."
3. "Want rotation, audit, or shared storage? Add a `vault:` block" (with a short example).

- [ ] **Step 3: Commit**

```bash
git add docs/getting-started.md
git commit -m "docs: update getting-started secrets section

Leads with the default .env-based path; Vault is presented as an opt-in
for users who need rotation/audit/shared storage.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 18: Release notes

**Files:**
- Modify: `CHANGELOG.md` (if present) or create release notes file

- [ ] **Step 1: Check for existing changelog**

Run: `ls CHANGELOG.md RELEASE_NOTES.md 2>&1`

- [ ] **Step 2: Append release notes from the spec's "Release notes draft" section**

Use verbatim the release notes from `docs/superpowers/specs/2026-04-22-secret-manager-simplification-design.md` (the "Release notes draft" subsection).

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: release notes for secret manager simplification

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 19: Open Phase 4 PR

- [ ] **Step 1: Push + PR**

```bash
git push -u origin feat/secret-manager-simplification-p4
gh pr create --title "Secret manager simplification — Phase 4 (examples + docs)" --body "$(cat <<'EOF'
## Summary
- examples/docker-workspace-nodejs no longer requires Vault
- getting-started.md leads with the default .env path
- Release notes capture the user-facing migration

## Test plan
- [x] Example deploys successfully without Vault
- [x] `just test-python` still green
- [x] Docs render correctly in the docusaurus preview

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Post-merge verification

### Task 20: Full-CI green after all four phases merge

- [ ] **Step 1: Run full CI locally**

Run: `just ci`
Expected: all green (or same pre-existing failures as documented in CLAUDE.md; nothing new).

- [ ] **Step 2: Verify no orphan Vault code references remain outside of gated paths**

Run: `grep -rn 'requires a Vault\|Spec 1 workspaces require\|workspace secrets on a Docker platform' packages/python/ 2>&1`
Expected: no matches (validators are gone).

- [ ] **Step 3: Sanity-test the Vault path still works**

Run: `cd examples/docker-workspace-vault && vystak apply --yes && sleep 10 && docker ps && vystak destroy --delete-vault --yes`
Expected: Vault + sidecars start, run, and destroy cleanly.

- [ ] **Step 4: Celebrate — the default path is 2 containers and 2–3s cold start**

Done.
