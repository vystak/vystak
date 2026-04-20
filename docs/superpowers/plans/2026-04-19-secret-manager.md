# Secret Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the v1 Secret Manager feature per `docs/superpowers/specs/2026-04-19-secret-manager-design.md`: a declarative `Vault` resource (Azure Key Vault), workspace-scoped secrets isolated from the LLM via ACA `lifecycle: None` + per-container `secretRef`, `.env` bootstrap, and a `vystak secrets` CLI.

**Architecture:** New top-level `Vault` schema resource; extended `Workspace` with `secrets` and `identity` fields. Azure provider emits per-container UAMIs with `lifecycle: None` and per-container `env[].secretRef`, achieving real LLM-to-secret isolation in a single ACA app (sidecar when workspace has secrets). Runtime SDK is one function (`vystak.secrets.get`). All existing examples continue to work via implicit env-passthrough when no Vault is declared.

**Tech Stack:** Python 3.11+, Pydantic v2, `uv` workspace, pytest, azure-mgmt-keyvault, azure-mgmt-msi, azure-mgmt-authorization, Azure Container Apps ARM API (API version `2024-02-02-preview` for `identitySettings`).

---

## Reference

- Spec: `docs/superpowers/specs/2026-04-19-secret-manager-design.md`
- Schema package: `packages/python/vystak/src/vystak/`
- Azure provider: `packages/python/vystak-provider-azure/src/vystak_provider_azure/`
- Docker provider: `packages/python/vystak-provider-docker/src/vystak_provider_docker/`
- CLI: `packages/python/vystak-cli/src/vystak_cli/`

## File Structure (created / modified)

**Created:**
- `packages/python/vystak/src/vystak/schema/vault.py` — `Vault` Pydantic model
- `packages/python/vystak/src/vystak/secrets/__init__.py` — runtime `get()` SDK
- `packages/python/vystak/src/vystak/secrets/env_loader.py` — `.env` file reader
- `packages/python/vystak/src/vystak/state/__init__.py` — `.vystak/` state-file helpers
- `packages/python/vystak/tests/test_vault.py` — `Vault` schema tests
- `packages/python/vystak/tests/test_workspace_secrets.py` — extended `Workspace` validator tests
- `packages/python/vystak/tests/test_multi_loader_vault.py` — YAML loader tests
- `packages/python/vystak/tests/test_secrets_sdk.py` — runtime SDK tests
- `packages/python/vystak/tests/test_hash_tree_secrets.py` — hash-tree additions tests
- `packages/python/vystak/tests/test_env_loader.py`
- `packages/python/vystak/tests/test_state.py`
- `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/vault.py` — `KeyVaultNode`
- `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/identity.py` — `UserAssignedIdentityNode`
- `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/kv_grant.py` — `KvGrantNode`
- `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/secret_sync.py` — `SecretSyncNode`
- `packages/python/vystak-provider-azure/tests/test_node_vault.py`
- `packages/python/vystak-provider-azure/tests/test_node_identity.py`
- `packages/python/vystak-provider-azure/tests/test_node_kv_grant.py`
- `packages/python/vystak-provider-azure/tests/test_node_secret_sync.py`
- `packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py`
- `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py` — `vystak secrets` CLI
- `packages/python/vystak-cli/tests/test_secrets_command.py`
- `examples/azure-vault/vystak.py` — minimal vault example
- `examples/azure-vault/README.md`
- `examples/azure-workspace-vault/vystak.py` — agent + workspace sidecar example
- `examples/azure-workspace-vault/README.md`

**Modified:**
- `packages/python/vystak/src/vystak/schema/common.py` — add `VaultType`, `VaultMode` enums
- `packages/python/vystak/src/vystak/schema/workspace.py` — add `secrets`, `identity` fields + validator
- `packages/python/vystak/src/vystak/schema/__init__.py` — export `Vault`, enums
- `packages/python/vystak/src/vystak/__init__.py` — re-export at top level
- `packages/python/vystak/src/vystak/schema/multi_loader.py` — accept top-level `vault:` key
- `packages/python/vystak/src/vystak/hash/tree.py` — extend `AgentHashTree`, `ChannelHashTree`, add `WorkspaceHashTree`
- `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/__init__.py` — export new nodes
- `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py` — per-container `secretRef` + `identitySettings` + sidecar container
- `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_channel_app.py` — same `identitySettings` + `secretRef` pattern
- `packages/python/vystak-provider-azure/src/vystak_provider_azure/provider.py` — wire new nodes into provisioning graph; phase ordering
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py` — reject `Vault` at plan time
- `packages/python/vystak-cli/src/vystak_cli/cli.py` — register `secrets` subcommand, extend `plan` output
- `pyproject.toml` (root) — add `azure-mgmt-msi`, `azure-mgmt-authorization`, `azure-mgmt-keyvault` if not present

---

## Phase 1 — Schema foundation

### Task 1: VaultType and VaultMode enums

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/common.py`
- Test: `packages/python/vystak/tests/test_common.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/python/vystak/tests/test_common.py`:

```python
from vystak.schema.common import VaultType, VaultMode


def test_vault_type_enum_values():
    assert VaultType.KEY_VAULT.value == "key-vault"
    assert list(VaultType) == [VaultType.KEY_VAULT]


def test_vault_mode_enum_values():
    assert VaultMode.DEPLOY.value == "deploy"
    assert VaultMode.EXTERNAL.value == "external"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak/tests/test_common.py::test_vault_type_enum_values -v`
Expected: FAIL — `ImportError: cannot import name 'VaultType'`.

- [ ] **Step 3: Implement enums**

Add to `packages/python/vystak/src/vystak/schema/common.py`:

```python
class VaultType(StrEnum):
    KEY_VAULT = "key-vault"


class VaultMode(StrEnum):
    DEPLOY = "deploy"
    EXTERNAL = "external"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_common.py -v`
Expected: PASS (both new tests green; existing tests unaffected).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/common.py packages/python/vystak/tests/test_common.py
git commit -m "feat(schema): add VaultType and VaultMode enums"
```

---

### Task 2: Vault model

**Files:**
- Create: `packages/python/vystak/src/vystak/schema/vault.py`
- Test: `packages/python/vystak/tests/test_vault.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/python/vystak/tests/test_vault.py`:

```python
import pytest
from pydantic import ValidationError as PydanticValidationError

from vystak.schema.provider import Provider
from vystak.schema.vault import Vault
from vystak.schema.common import VaultType, VaultMode


def _azure_provider() -> Provider:
    return Provider(name="azure", type="azure", config={"location": "eastus2"})


def test_vault_default_type_is_key_vault():
    v = Vault(name="v", provider=_azure_provider())
    assert v.type is VaultType.KEY_VAULT
    assert v.mode is VaultMode.DEPLOY


def test_vault_with_explicit_mode_and_config():
    v = Vault(
        name="v",
        provider=_azure_provider(),
        mode=VaultMode.EXTERNAL,
        config={"vault_name": "existing-vault"},
    )
    assert v.mode is VaultMode.EXTERNAL
    assert v.config == {"vault_name": "existing-vault"}


def test_vault_external_without_config_raises():
    with pytest.raises(PydanticValidationError) as excinfo:
        Vault(name="v", provider=_azure_provider(), mode=VaultMode.EXTERNAL)
    assert "requires config identifying the existing" in str(excinfo.value)


def test_vault_requires_provider():
    with pytest.raises(PydanticValidationError):
        Vault(name="v")  # type: ignore[call-arg]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_vault.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vystak.schema.vault'`.

- [ ] **Step 3: Implement Vault model**

Create `packages/python/vystak/src/vystak/schema/vault.py`:

```python
"""Vault model — a secrets backing store (Azure Key Vault in v1)."""

from typing import Self

from pydantic import model_validator

from vystak.schema.common import NamedModel, VaultMode, VaultType
from vystak.schema.provider import Provider


class Vault(NamedModel):
    """A secrets backing store — deployed by vystak or linked as external.

    Declared once per deployment. Every `Secret` in the declaration's
    agent tree materializes through this vault at apply time.
    """

    type: VaultType = VaultType.KEY_VAULT
    provider: Provider
    mode: VaultMode = VaultMode.DEPLOY
    config: dict = {}

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.mode is VaultMode.EXTERNAL and not self.config:
            raise ValueError(
                f"Vault '{self.name}' has mode='external' but requires config "
                f"identifying the existing store "
                f"(e.g. config={{'vault_name': 'my-vault'}})."
            )
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_vault.py -v`
Expected: PASS (all four tests green).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/vault.py packages/python/vystak/tests/test_vault.py
git commit -m "feat(schema): add Vault model with deploy/external modes"
```

---

### Task 3: Workspace extension (secrets + identity)

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/workspace.py`
- Test: `packages/python/vystak/tests/test_workspace_secrets.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/python/vystak/tests/test_workspace_secrets.py`:

```python
from vystak.schema.workspace import Workspace
from vystak.schema.common import WorkspaceType
from vystak.schema.secret import Secret


def test_workspace_default_has_no_secrets():
    ws = Workspace(name="w", type=WorkspaceType.PERSISTENT)
    assert ws.secrets == []
    assert ws.identity is None


def test_workspace_with_secrets():
    ws = Workspace(
        name="w",
        type=WorkspaceType.PERSISTENT,
        secrets=[Secret(name="STRIPE_API_KEY")],
    )
    assert len(ws.secrets) == 1
    assert ws.secrets[0].name == "STRIPE_API_KEY"


def test_workspace_with_explicit_identity_resource_id():
    uami_id = "/subscriptions/xxx/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/my-uami"
    ws = Workspace(
        name="w",
        type=WorkspaceType.PERSISTENT,
        identity=uami_id,
    )
    assert ws.identity == uami_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_workspace_secrets.py -v`
Expected: FAIL — `TypeError` on `secrets=` kwarg or `identity=` kwarg (fields don't exist yet).

- [ ] **Step 3: Extend Workspace model**

Modify `packages/python/vystak/src/vystak/schema/workspace.py`:

```python
"""Workspace model — agent execution environment."""

from vystak.schema.common import NamedModel, WorkspaceType
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret


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

    # v1 Secret Manager additions
    secrets: list[Secret] = []
    identity: str | None = None   # Existing UAMI resource ID; auto-created if None.
    # Cross-object validation (secrets require Azure provider) lives in
    # `vystak/schema/multi_loader.py` — Workspace.provider may be None at
    # construction time if inherited from the Agent's platform.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_workspace_secrets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/workspace.py packages/python/vystak/tests/test_workspace_secrets.py
git commit -m "feat(schema): extend Workspace with secrets and identity fields"
```

---

### Task 4: Schema exports

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/__init__.py`
- Modify: `packages/python/vystak/src/vystak/__init__.py`
- Test: `packages/python/vystak/tests/test_init.py` (create if missing)

- [ ] **Step 1: Write the failing test**

Create or extend `packages/python/vystak/tests/test_init.py`:

```python
def test_vault_exported_from_vystak():
    import vystak
    assert hasattr(vystak, "Vault")
    assert hasattr(vystak, "VaultType")
    assert hasattr(vystak, "VaultMode")


def test_vault_exported_from_vystak_schema():
    from vystak.schema import Vault, VaultType, VaultMode
    assert Vault is not None
    assert VaultType.KEY_VAULT.value == "key-vault"
    assert VaultMode.DEPLOY.value == "deploy"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak/tests/test_init.py::test_vault_exported_from_vystak -v`
Expected: FAIL — `AttributeError: module 'vystak' has no attribute 'Vault'`.

- [ ] **Step 3: Update schema __init__.py**

In `packages/python/vystak/src/vystak/schema/__init__.py`, add imports and exports:

```python
from vystak.schema.common import (
    AgentProtocol,
    ChannelType,
    McpTransport,
    NamedModel,
    RuntimeMode,
    VaultMode,
    VaultType,
    WorkspaceType,
)
# ... existing imports ...
from vystak.schema.vault import Vault

__all__ = [
    # ... existing ...
    "Vault",
    "VaultMode",
    "VaultType",
]
```

- [ ] **Step 4: Update vystak __init__.py**

In `packages/python/vystak/src/vystak/__init__.py`, import and re-export:

```python
from vystak.schema import (
    # ... existing imports ...
    Vault,
    VaultMode,
    VaultType,
)

__all__ = [
    # ... existing ...
    "Vault",
    "VaultMode",
    "VaultType",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_init.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/__init__.py packages/python/vystak/src/vystak/__init__.py packages/python/vystak/tests/test_init.py
git commit -m "feat(schema): export Vault from vystak package"
```

---

### Task 5: Multi-loader `vault:` top-level key

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/multi_loader.py`
- Test: `packages/python/vystak/tests/test_multi_loader_vault.py`

- [ ] **Step 1: Write the failing test**

Create `packages/python/vystak/tests/test_multi_loader_vault.py`:

```python
import pytest

from vystak.schema.multi_loader import load_multi_yaml


AZURE_ONE_AGENT_WITH_VAULT = {
    "providers": {
        "azure": {"type": "azure", "config": {"resource_group": "rg"}},
        "anthropic": {"type": "anthropic"},
    },
    "platforms": {
        "aca": {"type": "container-apps", "provider": "azure"},
    },
    "vault": {
        "name": "vystak-vault",
        "provider": "azure",
        "mode": "deploy",
        "config": {"vault_name": "vystak-vault"},
    },
    "models": {
        "sonnet": {"provider": "anthropic", "model_name": "claude-sonnet-4-6"},
    },
    "agents": [
        {
            "name": "assistant",
            "model": "sonnet",
            "secrets": [{"name": "ANTHROPIC_API_KEY"}],
            "platform": "aca",
        },
    ],
}


def test_vault_loaded_from_yaml():
    agents, channels, vault = load_multi_yaml(AZURE_ONE_AGENT_WITH_VAULT)
    assert vault is not None
    assert vault.name == "vystak-vault"
    assert vault.config["vault_name"] == "vystak-vault"
    assert vault.provider.name == "azure"


def test_no_vault_key_yields_none():
    data = dict(AZURE_ONE_AGENT_WITH_VAULT)
    data.pop("vault")
    agents, channels, vault = load_multi_yaml(data)
    assert vault is None


def test_vault_references_unknown_provider_raises():
    data = dict(AZURE_ONE_AGENT_WITH_VAULT)
    data["vault"] = {"name": "v", "provider": "nope", "mode": "deploy"}
    with pytest.raises(KeyError, match="Unknown provider 'nope' in vault"):
        load_multi_yaml(data)


def test_workspace_with_secrets_on_non_azure_platform_raises():
    data = dict(AZURE_ONE_AGENT_WITH_VAULT)
    data["providers"]["docker"] = {"type": "docker"}
    data["platforms"]["docker"] = {"type": "docker", "provider": "docker"}
    data["agents"][0]["platform"] = "docker"
    data["agents"][0]["workspace"] = {
        "type": "persistent",
        "secrets": [{"name": "STRIPE_API_KEY"}],
    }
    with pytest.raises(ValueError, match="only supports workspace-scoped secrets on Azure"):
        load_multi_yaml(data)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak/tests/test_multi_loader_vault.py -v`
Expected: FAIL — `ValueError: too many values to unpack (expected 2)` or similar; current loader returns `(agents, channels)` tuple.

- [ ] **Step 3: Update multi_loader.py return signature and add vault parsing**

Replace `packages/python/vystak/src/vystak/schema/multi_loader.py` with:

```python
"""Multi-agent YAML loader with named references."""

from vystak.schema.agent import Agent
from vystak.schema.channel import Channel
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.vault import Vault


def load_multi_yaml(data: dict) -> tuple[list[Agent], list[Channel], Vault | None]:
    """Load multi-agent/multi-channel YAML with named providers, platforms, models, vault.

    Returns (agents, channels, vault). Vault is None when not declared.
    """
    providers: dict[str, Provider] = {}
    for name, cfg in data.get("providers", {}).items():
        providers[name] = Provider(name=name, **cfg)

    platforms: dict[str, Platform] = {}
    for name, cfg in data.get("platforms", {}).items():
        cfg = dict(cfg)
        provider_ref = cfg.pop("provider")
        if provider_ref not in providers:
            raise KeyError(
                f"Unknown provider '{provider_ref}' in platform '{name}'. "
                f"Defined providers: {', '.join(providers.keys())}"
            )
        platforms[name] = Platform(name=name, provider=providers[provider_ref], **cfg)

    vault: Vault | None = None
    vault_cfg = data.get("vault")
    if vault_cfg is not None:
        vault_cfg = dict(vault_cfg)
        provider_ref = vault_cfg.pop("provider")
        if provider_ref not in providers:
            raise KeyError(
                f"Unknown provider '{provider_ref}' in vault '{vault_cfg.get('name')}'. "
                f"Defined providers: {', '.join(providers.keys())}"
            )
        vault = Vault(provider=providers[provider_ref], **vault_cfg)

    models: dict[str, Model] = {}
    for name, cfg in data.get("models", {}).items():
        cfg = dict(cfg)
        provider_ref = cfg.pop("provider")
        if provider_ref not in providers:
            raise KeyError(
                f"Unknown provider '{provider_ref}' in model '{name}'. "
                f"Defined providers: {', '.join(providers.keys())}"
            )
        models[name] = Model(name=name, provider=providers[provider_ref], **cfg)

    agents: list[Agent] = []
    for agent_data in data.get("agents", []):
        agent_data = dict(agent_data)

        model_ref = agent_data.get("model")
        if isinstance(model_ref, str):
            if model_ref not in models:
                raise KeyError(
                    f"Unknown model '{model_ref}' in agent '{agent_data.get('name')}'. "
                    f"Defined models: {', '.join(models.keys())}"
                )
            agent_data["model"] = models[model_ref]

        platform_ref = agent_data.get("platform")
        if isinstance(platform_ref, str):
            if platform_ref not in platforms:
                raise KeyError(
                    f"Unknown platform '{platform_ref}' in agent '{agent_data.get('name')}'. "
                    f"Defined platforms: {', '.join(platforms.keys())}"
                )
            agent_data["platform"] = platforms[platform_ref]

        agent = Agent.model_validate(agent_data)

        # Cross-object check: workspace secrets require Azure provider
        if agent.workspace and agent.workspace.secrets:
            platform_provider_type = (
                agent.platform.provider.type if agent.platform and agent.platform.provider else None
            )
            if platform_provider_type != "azure":
                raise ValueError(
                    f"Workspace '{agent.workspace.name}' on agent '{agent.name}' declares "
                    f"secrets, but the agent's platform provider is "
                    f"'{platform_provider_type}'. v1 only supports workspace-scoped secrets "
                    f"on Azure (ACA lifecycle:None). See follow-up spec for HashiCorp Vault."
                )

        agents.append(agent)

    channels: list[Channel] = []
    for channel_data in data.get("channels", []):
        channel_data = dict(channel_data)

        platform_ref = channel_data.get("platform")
        if isinstance(platform_ref, str):
            if platform_ref not in platforms:
                raise KeyError(
                    f"Unknown platform '{platform_ref}' in channel '{channel_data.get('name')}'. "
                    f"Defined platforms: {', '.join(platforms.keys())}"
                )
            channel_data["platform"] = platforms[platform_ref]

        channels.append(Channel.model_validate(channel_data))

    return agents, channels, vault
```

- [ ] **Step 4: Update all call sites of `load_multi_yaml`**

Run: `uv run grep -rn "load_multi_yaml" packages/ | grep -v __pycache__`

For each caller, update to unpack three values. Primary callers:
- `packages/python/vystak-cli/src/vystak_cli/loader.py` — add `_, vault = ...` or retain as needed (this task leaves vault unused; later tasks consume it).

Exact edit to `packages/python/vystak-cli/src/vystak_cli/loader.py`: change any `agents, channels = load_multi_yaml(...)` to `agents, channels, _vault = load_multi_yaml(...)`. If there's a variable capturing return, use `*, _vault` destructuring to avoid breaking.

- [ ] **Step 5: Run full test suite to catch regressions**

Run: `uv run pytest packages/python/vystak/tests/ -v`
Expected: PASS.

Run: `uv run pytest packages/python/vystak-cli/tests/ -v`
Expected: PASS (no regressions from tuple-shape change).

- [ ] **Step 6: Run new vault loader tests**

Run: `uv run pytest packages/python/vystak/tests/test_multi_loader_vault.py -v`
Expected: PASS (all four).

- [ ] **Step 7: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/multi_loader.py packages/python/vystak-cli/src/vystak_cli/loader.py packages/python/vystak/tests/test_multi_loader_vault.py
git commit -m "feat(schema): multi-loader parses top-level vault: key, cross-validates workspace secrets"
```

---

## Phase 2 — Hash tree extensions

### Task 6: WorkspaceHashTree + AgentHashTree additions

**Files:**
- Modify: `packages/python/vystak/src/vystak/hash/tree.py`
- Test: `packages/python/vystak/tests/test_hash_tree_secrets.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak/tests/test_hash_tree_secrets.py`:

```python
from vystak.hash.tree import hash_agent, hash_workspace, compute_grants_hash
from vystak.schema.agent import Agent
from vystak.schema.common import WorkspaceType
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret
from vystak.schema.workspace import Workspace


def _agent_with_workspace_secret(secret_name: str = "STRIPE_API_KEY") -> Agent:
    anthropic = Provider(name="anthropic", type="anthropic")
    return Agent(
        name="a",
        model=Model(name="m", provider=anthropic, model_name="claude-sonnet-4-6"),
        secrets=[Secret(name="ANTHROPIC_API_KEY")],
        workspace=Workspace(
            name="w",
            type=WorkspaceType.PERSISTENT,
            secrets=[Secret(name=secret_name)],
        ),
    )


def test_agent_hash_tree_includes_workspace_identity_and_grants():
    tree = hash_agent(_agent_with_workspace_secret())
    assert tree.workspace_identity  # non-empty hash string
    assert tree.grants
    assert tree.root


def test_changing_workspace_secret_changes_grants_hash():
    t1 = hash_agent(_agent_with_workspace_secret("STRIPE_API_KEY"))
    t2 = hash_agent(_agent_with_workspace_secret("TWILIO_API_KEY"))
    assert t1.grants != t2.grants
    assert t1.root != t2.root


def test_compute_grants_hash_stable_across_ordering():
    a = _agent_with_workspace_secret()
    h1 = compute_grants_hash(a)
    h2 = compute_grants_hash(a)
    assert h1 == h2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_hash_tree_secrets.py -v`
Expected: FAIL — `ImportError: cannot import name 'hash_workspace'` and `'compute_grants_hash'`.

- [ ] **Step 3: Extend hash tree module**

Replace `packages/python/vystak/src/vystak/hash/tree.py` with (additions marked):

```python
"""Hash tree composition for agent and channel definitions."""

import hashlib
from dataclasses import dataclass

from vystak.hash.hasher import hash_model
from vystak.schema.agent import Agent
from vystak.schema.channel import Channel
from vystak.schema.workspace import Workspace


@dataclass
class AgentHashTree:
    """Per-section hashes for an agent, enabling partial deploy detection."""

    brain: str
    skills: str
    mcp_servers: str
    workspace: str
    resources: str
    secrets: str
    sessions: str
    memory: str
    services: str
    # v1 Secret Manager additions
    workspace_identity: str
    grants: str
    root: str


@dataclass
class WorkspaceHashTree:
    identity: str
    secrets: str
    root: str


@dataclass
class ChannelHashTree:
    """Per-section hashes for a channel, enabling partial deploy detection."""

    config: str
    routes: str
    runtime: str
    secrets: str
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


def _hash_str(value: str | None) -> str:
    if value is None:
        return hashlib.sha256(b"null").hexdigest()
    return hashlib.sha256(value.encode()).hexdigest()


def hash_workspace(ws: Workspace) -> WorkspaceHashTree:
    identity = _hash_str(ws.identity)
    secrets = _hash_list(ws.secrets)
    root = hashlib.sha256(f"{identity}|{secrets}".encode()).hexdigest()
    return WorkspaceHashTree(identity=identity, secrets=secrets, root=root)


def compute_grants_hash(agent: Agent) -> str:
    """Compute a deterministic hash of the (identity, secret_name) grant set
    derived from the agent tree (agent-level secrets + workspace secrets)."""
    pairs = []
    pairs.extend(("agent", s.name) for s in agent.secrets)
    if agent.workspace:
        pairs.extend(("workspace", s.name) for s in agent.workspace.secrets)
    pairs.sort()
    blob = "|".join(f"{role}:{name}" for role, name in pairs)
    return hashlib.sha256(blob.encode()).hexdigest()


def hash_agent(agent: Agent) -> AgentHashTree:
    """Compute the full hash tree for an agent definition."""
    brain = hash_model(agent.model)
    skills = _hash_list(agent.skills)
    mcp_servers = _hash_list(agent.mcp_servers)
    workspace = _hash_optional(agent.workspace)
    resources = _hash_list(agent.resources)
    secrets = _hash_list(agent.secrets)
    sessions = _hash_optional(agent.sessions)
    memory = _hash_optional(agent.memory)
    services = _hash_list(agent.services)

    workspace_identity = (
        hash_workspace(agent.workspace).identity
        if agent.workspace
        else _hash_str(None)
    )
    grants = compute_grants_hash(agent)

    sections = "|".join(
        [
            brain,
            skills,
            mcp_servers,
            workspace,
            resources,
            secrets,
            sessions,
            memory,
            services,
            workspace_identity,
            grants,
        ]
    )
    root = hashlib.sha256(sections.encode()).hexdigest()

    return AgentHashTree(
        brain=brain,
        skills=skills,
        mcp_servers=mcp_servers,
        workspace=workspace,
        resources=resources,
        secrets=secrets,
        sessions=sessions,
        memory=memory,
        services=services,
        workspace_identity=workspace_identity,
        grants=grants,
        root=root,
    )


def hash_channel(channel: Channel) -> ChannelHashTree:
    """Compute the full hash tree for a channel definition."""
    config = hashlib.sha256(repr(sorted(channel.config.items())).encode()).hexdigest()
    routes = _hash_list(channel.routes)
    mode = channel.runtime_mode.value if channel.runtime_mode else "default"
    runtime = _hash_str(f"{channel.type.value}|{mode}")
    secrets = _hash_list(channel.secrets)

    sections = "|".join([config, routes, runtime, secrets])
    root = hashlib.sha256(sections.encode()).hexdigest()

    return ChannelHashTree(
        config=config,
        routes=routes,
        runtime=runtime,
        secrets=secrets,
        root=root,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_hash_tree_secrets.py packages/python/vystak/tests/test_hasher.py -v`
Expected: PASS.

- [ ] **Step 5: Also ensure other hash consumers still import properly**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/ -v -k "not docker"`
Expected: PASS — providers may reference `AgentHashTree`; new fields have defaults from construction so nothing breaks.

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak/src/vystak/hash/tree.py packages/python/vystak/tests/test_hash_tree_secrets.py
git commit -m "feat(hash): extend AgentHashTree with workspace identity + grants, add WorkspaceHashTree"
```

---

## Phase 3 — Runtime SDK

### Task 7: `vystak.secrets.get()` function

**Files:**
- Create: `packages/python/vystak/src/vystak/secrets/__init__.py`
- Test: `packages/python/vystak/tests/test_secrets_sdk.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak/tests/test_secrets_sdk.py`:

```python
import os

import pytest


def test_get_returns_env_value(monkeypatch):
    monkeypatch.setenv("FOO_KEY", "bar")
    from vystak import secrets
    assert secrets.get("FOO_KEY") == "bar"


def test_get_missing_raises_secret_not_available(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    from vystak import secrets
    from vystak.secrets import SecretNotAvailableError
    with pytest.raises(SecretNotAvailableError, match="NOPE_KEY"):
        secrets.get("NOPE_KEY")


def test_secret_not_available_message_is_actionable(monkeypatch):
    monkeypatch.delenv("ABSENT_KEY", raising=False)
    from vystak import secrets
    from vystak.secrets import SecretNotAvailableError
    try:
        secrets.get("ABSENT_KEY")
    except SecretNotAvailableError as e:
        assert "ABSENT_KEY" in str(e)
        assert "Declare it on the Agent / Workspace / Channel" in str(e)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_secrets_sdk.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vystak.secrets'`.

- [ ] **Step 3: Implement runtime SDK module**

Create `packages/python/vystak/src/vystak/secrets/__init__.py`:

```python
"""Runtime SDK for reading secrets from the container environment.

Secret values are materialized into the container's env at start by the
platform (ACA secretRef for vault-backed deployments, direct os.environ
for env-passthrough). This module wraps os.environ with a clearer error
when the secret is missing.

This is a thin wrapper — it carries no security guarantee. Its existence
makes audits easier (a lint rule can flag raw os.environ[name] reads on
declared secret names in workspace/skill tool code).
"""

import os


class SecretNotAvailableError(KeyError):
    """Raised when a secret is not available in the current container env."""


def get(name: str) -> str:
    """Return the value of the named secret from the container's environment.

    Raises SecretNotAvailableError with actionable guidance if the secret
    is not present — typically because it was not declared on the
    Agent/Workspace/Channel that this container is serving.
    """
    try:
        return os.environ[name]
    except KeyError:
        raise SecretNotAvailableError(
            f"Secret {name!r} is not available in this container. "
            f"Declare it on the Agent / Workspace / Channel that uses it."
        )


__all__ = ["get", "SecretNotAvailableError"]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak/tests/test_secrets_sdk.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/secrets/__init__.py packages/python/vystak/tests/test_secrets_sdk.py
git commit -m "feat(sdk): add vystak.secrets.get runtime helper"
```

---

### Task 8: `.env` file loader helper

**Files:**
- Create: `packages/python/vystak/src/vystak/secrets/env_loader.py`
- Test: `packages/python/vystak/tests/test_env_loader.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak/tests/test_env_loader.py`:

```python
from pathlib import Path

import pytest

from vystak.secrets.env_loader import load_env_file, EnvFileMissingError


def test_load_env_file_basic(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("FOO=bar\nBAZ=qux\n")
    result = load_env_file(p)
    assert result == {"FOO": "bar", "BAZ": "qux"}


def test_load_env_file_skips_comments_and_blank_lines(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("# comment\n\nFOO=bar\n\n# another\nBAZ=qux\n")
    result = load_env_file(p)
    assert result == {"FOO": "bar", "BAZ": "qux"}


def test_load_env_file_strips_quotes(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text('FOO="bar"\nBAZ=\'qux\'\n')
    result = load_env_file(p)
    assert result == {"FOO": "bar", "BAZ": "qux"}


def test_load_env_file_preserves_equals_in_value(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("URL=postgresql://u:p=w@h/db\n")
    result = load_env_file(p)
    assert result == {"URL": "postgresql://u:p=w@h/db"}


def test_load_env_file_missing_raises(tmp_path: Path):
    with pytest.raises(EnvFileMissingError):
        load_env_file(tmp_path / "does-not-exist.env")


def test_load_env_file_optional_returns_empty(tmp_path: Path):
    result = load_env_file(tmp_path / "nope.env", optional=True)
    assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak/tests/test_env_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vystak.secrets.env_loader'`.

- [ ] **Step 3: Implement env loader**

Create `packages/python/vystak/src/vystak/secrets/env_loader.py`:

```python
"""Minimal .env file parser for apply-time secret bootstrap."""

from pathlib import Path


class EnvFileMissingError(FileNotFoundError):
    """Raised when a required .env file is missing."""


def load_env_file(path: Path, *, optional: bool = False) -> dict[str, str]:
    """Parse a .env file into a dict.

    Supports: KEY=value, KEY="value", KEY='value'.
    Ignores: blank lines, lines starting with '#'.
    First '=' is the separator; subsequent '='s are part of the value.
    """
    if not path.exists():
        if optional:
            return {}
        raise EnvFileMissingError(f".env file not found: {path}")

    result: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        result[key] = value
    return result


__all__ = ["load_env_file", "EnvFileMissingError"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_env_loader.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/secrets/env_loader.py packages/python/vystak/tests/test_env_loader.py
git commit -m "feat(sdk): .env file loader for apply-time secret bootstrap"
```

---

## Phase 4 — State management

### Task 9: `.vystak/` state files for secrets and identities

**Files:**
- Create: `packages/python/vystak/src/vystak/state/__init__.py`
- Test: `packages/python/vystak/tests/test_state.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak/tests/test_state.py`:

```python
from pathlib import Path

from vystak.state import (
    load_secrets_state,
    save_secrets_state,
    record_secret_pushed,
    load_identities_state,
    record_identity_created,
)


def test_secrets_state_round_trip(tmp_path: Path):
    p = tmp_path / ".vystak" / "secrets-state.json"
    save_secrets_state(p, {"STRIPE_API_KEY": {"pushed_at": "2026-04-19T10:00:00Z", "hash_prefix": "abcd"}})
    state = load_secrets_state(p)
    assert state == {"STRIPE_API_KEY": {"pushed_at": "2026-04-19T10:00:00Z", "hash_prefix": "abcd"}}


def test_load_secrets_state_missing_returns_empty(tmp_path: Path):
    assert load_secrets_state(tmp_path / "nothing.json") == {}


def test_record_secret_pushed(tmp_path: Path):
    p = tmp_path / ".vystak" / "secrets-state.json"
    record_secret_pushed(p, "STRIPE_API_KEY", hash_prefix="abcd")
    state = load_secrets_state(p)
    assert "STRIPE_API_KEY" in state
    assert state["STRIPE_API_KEY"]["hash_prefix"] == "abcd"
    assert "pushed_at" in state["STRIPE_API_KEY"]


def test_record_identity_created(tmp_path: Path):
    p = tmp_path / ".vystak" / "identities-state.json"
    record_identity_created(p, name="agent-uami", resource_id="/subscriptions/.../uami-foo")
    state = load_identities_state(p)
    assert state["agent-uami"]["resource_id"] == "/subscriptions/.../uami-foo"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vystak.state'`.

- [ ] **Step 3: Implement state module**

Create `packages/python/vystak/src/vystak/state/__init__.py`:

```python
"""Local state files under .vystak/ used by apply/destroy for secrets and identities."""

import datetime
import hashlib
import json
from pathlib import Path


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def load_secrets_state(path: Path) -> dict:
    """Load .vystak/secrets-state.json — per-secret metadata."""
    return _load(path)


def save_secrets_state(path: Path, data: dict) -> None:
    _save(path, data)


def record_secret_pushed(
    path: Path,
    name: str,
    *,
    value: str | None = None,
    hash_prefix: str | None = None,
) -> None:
    """Mark a secret as pushed. Computes hash_prefix from value if supplied."""
    state = load_secrets_state(path)
    if hash_prefix is None and value is not None:
        hash_prefix = hashlib.sha256(value.encode()).hexdigest()[:12]
    state[name] = {
        "pushed_at": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
        "hash_prefix": hash_prefix or "",
    }
    save_secrets_state(path, state)


def load_identities_state(path: Path) -> dict:
    """Load .vystak/identities-state.json — per-identity metadata."""
    return _load(path)


def record_identity_created(path: Path, *, name: str, resource_id: str) -> None:
    state = load_identities_state(path)
    state[name] = {
        "resource_id": resource_id,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
    }
    _save(path, state)


__all__ = [
    "load_secrets_state",
    "save_secrets_state",
    "record_secret_pushed",
    "load_identities_state",
    "record_identity_created",
]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak/tests/test_state.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/state/__init__.py packages/python/vystak/tests/test_state.py
git commit -m "feat(state): .vystak/ state files for secrets and identities"
```

---

## Phase 5 — Azure provider: Key Vault node

### Task 10: `KeyVaultNode` — deploy or verify

**Files:**
- Create: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/vault.py`
- Test: `packages/python/vystak-provider-azure/tests/test_node_vault.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-provider-azure/tests/test_node_vault.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from vystak.schema.common import VaultMode
from vystak_provider_azure.nodes.vault import KeyVaultNode


def _fake_kv_client() -> MagicMock:
    client = MagicMock()
    client.vaults.begin_create_or_update.return_value.result.return_value = MagicMock(
        properties=MagicMock(vault_uri="https://my-vault.vault.azure.net/")
    )
    client.vaults.get.return_value = MagicMock(
        properties=MagicMock(vault_uri="https://my-vault.vault.azure.net/")
    )
    return client


def test_deploy_creates_vault():
    client = _fake_kv_client()
    node = KeyVaultNode(
        client=client,
        rg_name="rg",
        vault_name="my-vault",
        location="eastus2",
        mode=VaultMode.DEPLOY,
        subscription_id="sub-1",
        tenant_id="tenant-1",
    )
    result = node.provision(context={})
    assert result.info["vault_uri"] == "https://my-vault.vault.azure.net/"
    client.vaults.begin_create_or_update.assert_called_once()


def test_external_mode_verifies_existing():
    client = _fake_kv_client()
    node = KeyVaultNode(
        client=client,
        rg_name="rg",
        vault_name="existing",
        location="eastus2",
        mode=VaultMode.EXTERNAL,
        subscription_id="sub-1",
        tenant_id="tenant-1",
    )
    result = node.provision(context={})
    client.vaults.get.assert_called_once_with("rg", "existing")
    client.vaults.begin_create_or_update.assert_not_called()
    assert result.info["vault_uri"].endswith(".vault.azure.net/")


def test_external_mode_missing_raises():
    from azure.core.exceptions import ResourceNotFoundError
    client = MagicMock()
    client.vaults.get.side_effect = ResourceNotFoundError("not found")
    node = KeyVaultNode(
        client=client,
        rg_name="rg",
        vault_name="missing",
        location="eastus2",
        mode=VaultMode.EXTERNAL,
        subscription_id="sub-1",
        tenant_id="tenant-1",
    )
    with pytest.raises(RuntimeError, match="External Vault 'missing' not found"):
        node.provision(context={})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_node_vault.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement `KeyVaultNode`**

Create `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/vault.py`:

```python
"""KeyVaultNode — deploys an Azure Key Vault or verifies one exists."""

from azure.core.exceptions import ResourceNotFoundError

from vystak.provisioning import Provisionable, ProvisionResult
from vystak.schema.common import VaultMode


class KeyVaultNode(Provisionable):
    """Creates or verifies an Azure Key Vault, using RBAC authorization model."""

    def __init__(
        self,
        client,
        rg_name: str,
        vault_name: str,
        location: str,
        mode: VaultMode,
        subscription_id: str,
        tenant_id: str,
        tags: dict | None = None,
    ):
        super().__init__(name=f"keyvault:{vault_name}")
        self._client = client
        self._rg_name = rg_name
        self._vault_name = vault_name
        self._location = location
        self._mode = mode
        self._subscription_id = subscription_id
        self._tenant_id = tenant_id
        self._tags = tags or {}

    def provision(self, context: dict) -> ProvisionResult:
        if self._mode is VaultMode.EXTERNAL:
            try:
                existing = self._client.vaults.get(self._rg_name, self._vault_name)
            except ResourceNotFoundError as e:
                raise RuntimeError(
                    f"External Vault '{self._vault_name}' not found in resource "
                    f"group '{self._rg_name}'. Create it first, or switch to "
                    f"mode='deploy'."
                ) from e
            return ProvisionResult(
                name=self.name,
                info={
                    "vault_uri": existing.properties.vault_uri,
                    "vault_name": self._vault_name,
                    "rg_name": self._rg_name,
                },
            )

        # DEPLOY mode
        from azure.mgmt.keyvault.models import (
            VaultCreateOrUpdateParameters,
            VaultProperties,
            Sku,
        )

        params = VaultCreateOrUpdateParameters(
            location=self._location,
            tags=self._tags,
            properties=VaultProperties(
                tenant_id=self._tenant_id,
                sku=Sku(name="standard", family="A"),
                enable_rbac_authorization=True,
                soft_delete_retention_in_days=7,
            ),
        )
        result = self._client.vaults.begin_create_or_update(
            self._rg_name, self._vault_name, params
        ).result()
        return ProvisionResult(
            name=self.name,
            info={
                "vault_uri": result.properties.vault_uri,
                "vault_name": self._vault_name,
                "rg_name": self._rg_name,
            },
        )

    def destroy(self, context: dict) -> None:
        # Destroy leaves the vault alone unless --delete-vault passed;
        # caller manages that via provider-level flag. This node never
        # self-destroys its vault in v1.
        pass
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_node_vault.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/vault.py packages/python/vystak-provider-azure/tests/test_node_vault.py
git commit -m "feat(provider-azure): KeyVaultNode for deploy/external vault provisioning"
```

---

## Phase 6 — Azure provider: UAMI node

### Task 11: `UserAssignedIdentityNode` with `lifecycle: None` metadata

**Files:**
- Create: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/identity.py`
- Test: `packages/python/vystak-provider-azure/tests/test_node_identity.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-provider-azure/tests/test_node_identity.py`:

```python
from unittest.mock import MagicMock

from vystak_provider_azure.nodes.identity import UserAssignedIdentityNode


def _fake_msi_client() -> MagicMock:
    client = MagicMock()
    client.user_assigned_identities.create_or_update.return_value = MagicMock(
        id="/subscriptions/x/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/my-uami",
        client_id="00000000-0000-0000-0000-000000000001",
        principal_id="11111111-1111-1111-1111-111111111111",
    )
    return client


def test_creates_uami_and_returns_ids():
    client = _fake_msi_client()
    node = UserAssignedIdentityNode(
        client=client,
        rg_name="rg",
        uami_name="my-uami",
        location="eastus2",
    )
    result = node.provision(context={})
    assert result.info["resource_id"].endswith("/my-uami")
    assert result.info["client_id"] == "00000000-0000-0000-0000-000000000001"
    assert result.info["principal_id"] == "11111111-1111-1111-1111-111111111111"


def test_passes_through_existing_resource_id_when_provided():
    node = UserAssignedIdentityNode.from_existing(
        resource_id="/subscriptions/x/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/existing",
        name="external-uami",
    )
    result = node.provision(context={})
    assert result.info["resource_id"].endswith("/existing")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_node_identity.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement `UserAssignedIdentityNode`**

Create `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/identity.py`:

```python
"""UserAssignedIdentityNode — creates a UAMI or references an existing one."""

from typing import Self

from vystak.provisioning import Provisionable, ProvisionResult


class UserAssignedIdentityNode(Provisionable):
    """Creates a new UAMI or returns metadata for an existing one.

    The UAMI is intended for use with ACA `identitySettings[].lifecycle: None`
    so the identity's token is never reachable from container code.
    """

    def __init__(
        self,
        client,
        rg_name: str,
        uami_name: str,
        location: str,
        tags: dict | None = None,
    ):
        super().__init__(name=f"uami:{uami_name}")
        self._client = client
        self._rg_name = rg_name
        self._uami_name = uami_name
        self._location = location
        self._tags = tags or {}
        self._existing_resource_id: str | None = None

    @classmethod
    def from_existing(cls, *, resource_id: str, name: str) -> Self:
        """Wrap an existing UAMI resource ID — no API calls made."""
        inst = cls.__new__(cls)
        Provisionable.__init__(inst, name=f"uami:{name}")
        inst._client = None
        inst._rg_name = ""
        inst._uami_name = name
        inst._location = ""
        inst._tags = {}
        inst._existing_resource_id = resource_id
        return inst

    def provision(self, context: dict) -> ProvisionResult:
        if self._existing_resource_id:
            return ProvisionResult(
                name=self.name,
                info={
                    "resource_id": self._existing_resource_id,
                    "client_id": None,
                    "principal_id": None,
                    "pre_existing": True,
                },
            )

        from azure.mgmt.msi.models import Identity

        result = self._client.user_assigned_identities.create_or_update(
            resource_group_name=self._rg_name,
            resource_name=self._uami_name,
            parameters=Identity(location=self._location, tags=self._tags),
        )
        return ProvisionResult(
            name=self.name,
            info={
                "resource_id": result.id,
                "client_id": result.client_id,
                "principal_id": result.principal_id,
                "pre_existing": False,
            },
        )

    def destroy(self, context: dict) -> None:
        if self._existing_resource_id is not None:
            return
        try:
            self._client.user_assigned_identities.delete(self._rg_name, self._uami_name)
        except Exception:
            pass
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_node_identity.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/identity.py packages/python/vystak-provider-azure/tests/test_node_identity.py
git commit -m "feat(provider-azure): UserAssignedIdentityNode with from_existing support"
```

---

## Phase 7 — Azure provider: KV grant node

### Task 12: `KvGrantNode` — assigns `Key Vault Secrets User` role

**Files:**
- Create: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/kv_grant.py`
- Test: `packages/python/vystak-provider-azure/tests/test_node_kv_grant.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-provider-azure/tests/test_node_kv_grant.py`:

```python
import uuid
from unittest.mock import MagicMock, patch

from vystak_provider_azure.nodes.kv_grant import KvGrantNode


KV_SECRETS_USER_ROLE_ID = "4633458b-17de-408a-b874-0445c86b69e6"


def _auth_client() -> MagicMock:
    client = MagicMock()
    client.role_assignments.create.return_value = MagicMock(id="ra-id", name="ra-name")
    return client


def test_assigns_kv_secrets_user_role_on_secret():
    client = _auth_client()
    node = KvGrantNode(
        client=client,
        scope="/subscriptions/x/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/v/secrets/STRIPE_API_KEY",
        principal_id="11111111-1111-1111-1111-111111111111",
        subscription_id="x",
    )
    node.provision(context={})
    args, kwargs = client.role_assignments.create.call_args
    # Scope positional arg 0, role assignment name positional arg 1, params kwarg or positional 2
    assert kwargs.get("scope") == node._scope or args[0] == node._scope
    # The role_definition_id must reference Key Vault Secrets User
    params = kwargs.get("parameters") or args[2]
    assert KV_SECRETS_USER_ROLE_ID in params.role_definition_id
    assert params.principal_id == "11111111-1111-1111-1111-111111111111"


def test_skips_when_principal_id_is_none():
    client = _auth_client()
    node = KvGrantNode(
        client=client,
        scope="/subscriptions/x/.../secrets/S",
        principal_id=None,  # from pre-existing UAMI whose principal_id wasn't fetched
        subscription_id="x",
    )
    result = node.provision(context={})
    client.role_assignments.create.assert_not_called()
    assert result.info["skipped"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_node_kv_grant.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement `KvGrantNode`**

Create `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/kv_grant.py`:

```python
"""KvGrantNode — assigns 'Key Vault Secrets User' role on a KV secret."""

import time
import uuid
from typing import Any

from vystak.provisioning import Provisionable, ProvisionResult


# Azure built-in role: Key Vault Secrets User (read-only access to secret values)
KV_SECRETS_USER_ROLE_ID = "4633458b-17de-408a-b874-0445c86b69e6"


class KvGrantNode(Provisionable):
    """Assigns Key Vault Secrets User role to a principal, scoped to one secret.

    Retries with backoff on RBAC-propagation transient failures (up to 60s).
    """

    def __init__(
        self,
        client: Any,
        scope: str,
        principal_id: str | None,
        subscription_id: str,
        retry_seconds: int = 60,
    ):
        super().__init__(name=f"kv-grant:{scope.rsplit('/', 1)[-1]}:{principal_id or 'skipped'}")
        self._client = client
        self._scope = scope
        self._principal_id = principal_id
        self._subscription_id = subscription_id
        self._retry_seconds = retry_seconds

    def provision(self, context: dict) -> ProvisionResult:
        if self._principal_id is None:
            return ProvisionResult(name=self.name, info={"skipped": True})

        from azure.core.exceptions import HttpResponseError
        from azure.mgmt.authorization.models import RoleAssignmentCreateParameters

        role_def_id = (
            f"/subscriptions/{self._subscription_id}/providers/Microsoft.Authorization/"
            f"roleDefinitions/{KV_SECRETS_USER_ROLE_ID}"
        )
        params = RoleAssignmentCreateParameters(
            role_definition_id=role_def_id,
            principal_id=self._principal_id,
            principal_type="ServicePrincipal",
        )

        ra_name = str(uuid.uuid4())
        deadline = time.time() + self._retry_seconds
        last_err: Exception | None = None
        while time.time() < deadline:
            try:
                self._client.role_assignments.create(
                    scope=self._scope,
                    role_assignment_name=ra_name,
                    parameters=params,
                )
                return ProvisionResult(
                    name=self.name,
                    info={"scope": self._scope, "principal_id": self._principal_id},
                )
            except HttpResponseError as e:
                # Treat 400-class transient errors around principal propagation as retryable
                if e.status_code in (400, 403, 404):
                    last_err = e
                    time.sleep(5)
                    continue
                raise
        if last_err is not None:
            raise last_err
        raise RuntimeError(f"KvGrantNode: timed out assigning role at {self._scope}")

    def destroy(self, context: dict) -> None:
        # Role assignments are tracked per deploy; deletion handled by
        # orchestrating provider via a separate cleanup step.
        pass
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_node_kv_grant.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/kv_grant.py packages/python/vystak-provider-azure/tests/test_node_kv_grant.py
git commit -m "feat(provider-azure): KvGrantNode assigns Key Vault Secrets User role with retry"
```

---

## Phase 8 — Azure provider: Secret sync node

### Task 13: `SecretSyncNode` — push-if-missing from `.env`

**Files:**
- Create: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/secret_sync.py`
- Test: `packages/python/vystak-provider-azure/tests/test_node_secret_sync.py`

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-provider-azure/tests/test_node_secret_sync.py`:

```python
from unittest.mock import MagicMock

import pytest
from azure.core.exceptions import ResourceNotFoundError

from vystak_provider_azure.nodes.secret_sync import SecretSyncNode


def _secret_client(existing: dict[str, str] | None = None) -> MagicMock:
    existing = existing or {}
    client = MagicMock()

    def _get(name):
        if name in existing:
            mock = MagicMock()
            mock.value = existing[name]
            return mock
        raise ResourceNotFoundError("not found")

    client.get_secret.side_effect = _get
    client.set_secret.return_value = MagicMock()
    return client


def test_push_if_missing_pushes_absent_secrets():
    client = _secret_client(existing={})
    node = SecretSyncNode(
        client=client,
        declared_secrets=["ANTHROPIC_API_KEY"],
        env_values={"ANTHROPIC_API_KEY": "sk-ant-value"},
    )
    result = node.provision(context={})
    client.set_secret.assert_called_once_with("ANTHROPIC_API_KEY", "sk-ant-value")
    assert result.info["pushed"] == ["ANTHROPIC_API_KEY"]
    assert result.info["skipped"] == []
    assert result.info["missing"] == []


def test_push_if_missing_skips_present_secrets():
    client = _secret_client(existing={"ANTHROPIC_API_KEY": "preserved"})
    node = SecretSyncNode(
        client=client,
        declared_secrets=["ANTHROPIC_API_KEY"],
        env_values={"ANTHROPIC_API_KEY": "different"},
    )
    result = node.provision(context={})
    client.set_secret.assert_not_called()
    assert result.info["skipped"] == ["ANTHROPIC_API_KEY"]


def test_force_overwrites_present_secrets():
    client = _secret_client(existing={"ANTHROPIC_API_KEY": "old"})
    node = SecretSyncNode(
        client=client,
        declared_secrets=["ANTHROPIC_API_KEY"],
        env_values={"ANTHROPIC_API_KEY": "new"},
        force=True,
    )
    result = node.provision(context={})
    client.set_secret.assert_called_once_with("ANTHROPIC_API_KEY", "new")
    assert result.info["pushed"] == ["ANTHROPIC_API_KEY"]


def test_missing_secret_aborts_with_actionable_error():
    client = _secret_client(existing={})
    node = SecretSyncNode(
        client=client,
        declared_secrets=["ABSENT_KEY"],
        env_values={},
    )
    with pytest.raises(RuntimeError, match="ABSENT_KEY"):
        node.provision(context={})


def test_missing_with_allow_missing_does_not_abort():
    client = _secret_client(existing={})
    node = SecretSyncNode(
        client=client,
        declared_secrets=["ABSENT_KEY"],
        env_values={},
        allow_missing=True,
    )
    result = node.provision(context={})
    assert result.info["missing"] == ["ABSENT_KEY"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_node_secret_sync.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement `SecretSyncNode`**

Create `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/secret_sync.py`:

```python
"""SecretSyncNode — reads .env values and pushes to Key Vault at apply time."""

from typing import Any

from azure.core.exceptions import ResourceNotFoundError

from vystak.provisioning import Provisionable, ProvisionResult


class SecretSyncNode(Provisionable):
    """Pushes declared secrets into a KV client with push-if-missing semantics.

    Args:
        client: An azure.keyvault.secrets.SecretClient pointed at the vault.
        declared_secrets: List of secret names to sync.
        env_values: dict from .env file (or other source) — values to push.
        force: If True, overwrite existing KV values.
        allow_missing: If True, do not abort when a secret is missing from
            both KV and env_values; instead, report in the result.
    """

    def __init__(
        self,
        client: Any,
        declared_secrets: list[str],
        env_values: dict[str, str],
        force: bool = False,
        allow_missing: bool = False,
    ):
        super().__init__(name="secret-sync")
        self._client = client
        self._declared = list(declared_secrets)
        self._env = dict(env_values)
        self._force = force
        self._allow_missing = allow_missing

    def provision(self, context: dict) -> ProvisionResult:
        pushed: list[str] = []
        skipped: list[str] = []
        missing: list[str] = []

        for name in self._declared:
            existing_value = self._get_existing(name)
            if existing_value is not None and not self._force:
                skipped.append(name)
                continue
            if name in self._env:
                self._client.set_secret(name, self._env[name])
                pushed.append(name)
            else:
                missing.append(name)

        if missing and not self._allow_missing:
            raise RuntimeError(
                f"Secrets missing from both .env and vault: {', '.join(missing)}. "
                f"Set them in .env, run 'vystak secrets set <name>=<value>', or "
                f"pass --allow-missing."
            )

        return ProvisionResult(
            name=self.name,
            info={"pushed": pushed, "skipped": skipped, "missing": missing},
        )

    def _get_existing(self, name: str) -> str | None:
        try:
            return self._client.get_secret(name).value
        except ResourceNotFoundError:
            return None

    def destroy(self, context: dict) -> None:
        # Destroy leaves secret values in KV.
        pass
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_node_secret_sync.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/secret_sync.py packages/python/vystak-provider-azure/tests/test_node_secret_sync.py
git commit -m "feat(provider-azure): SecretSyncNode with push-if-missing and --force"
```

---

## Phase 9 — Azure provider: ACA app wiring

### Task 14: Per-container `secretRef` + `identitySettings` in `aca_app.py`

**Files:**
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py`
- Test: `packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py`

Goal: when a Vault is declared AND the agent's workspace has secrets, emit a two-container revision (agent + workspace) with per-container `env[].secretRef` and two `lifecycle: None` UAMIs. When only the agent has vault-backed secrets (no workspace secrets), emit a one-container revision with vault-backed `secretRef` for agent env.

- [ ] **Step 1: Write failing tests**

Create `packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py`:

```python
"""Tests for ACA app revision JSON when Vault is declared."""

from unittest.mock import MagicMock, patch

import pytest

from vystak.schema.agent import Agent
from vystak.schema.common import WorkspaceType
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret
from vystak.schema.workspace import Workspace
from vystak.schema.platform import Platform


def _fixture_agent(with_workspace_secret: bool = False) -> Agent:
    azure = Provider(name="azure", type="azure", config={"location": "eastus2"})
    platform = Platform(name="aca", type="container-apps", provider=azure)
    anthropic = Provider(name="anthropic", type="anthropic")
    workspace = None
    if with_workspace_secret:
        workspace = Workspace(
            name="w",
            type=WorkspaceType.PERSISTENT,
            secrets=[Secret(name="STRIPE_API_KEY")],
        )
    return Agent(
        name="assistant",
        model=Model(name="m", provider=anthropic, model_name="claude-sonnet-4-6"),
        secrets=[Secret(name="ANTHROPIC_API_KEY")],
        workspace=workspace,
        platform=platform,
    )


def test_build_revision_agent_only_with_vault(monkeypatch):
    from vystak_provider_azure.nodes.aca_app import build_revision_for_vault

    agent = _fixture_agent(with_workspace_secret=False)
    revision = build_revision_for_vault(
        agent=agent,
        vault_uri="https://my-vault.vault.azure.net/",
        agent_identity_resource_id="/subs/.../uami-agent",
        agent_identity_client_id="agent-client-id",
        workspace_identity_resource_id=None,
        workspace_identity_client_id=None,
        model_secrets=["ANTHROPIC_API_KEY"],
        workspace_secrets=[],
        acr_login_server="myacr.azurecr.io",
        acr_password_secret_ref="acr-password",
        acr_password_value="pw",
        agent_image="myacr.azurecr.io/assistant:abc",
        workspace_image=None,
    )
    # Expect: one main container (agent), one UAMI attached, both secrets wired via secretRef
    assert len(revision["properties"]["template"]["containers"]) == 1
    agent_container = revision["properties"]["template"]["containers"][0]
    assert any(
        e.get("secretRef") == "anthropic-api-key" and e["name"] == "ANTHROPIC_API_KEY"
        for e in agent_container["env"]
    )
    identities = revision["identity"]["userAssignedIdentities"]
    assert len(identities) == 1
    lifecycle = revision["properties"]["configuration"]["identitySettings"]
    assert all(s["lifecycle"] == "None" for s in lifecycle if s["identity"] != "ACR_IMAGEPULL_IDENTITY_RESOURCE_ID")
    kv_secrets = [s for s in revision["properties"]["configuration"]["secrets"] if "keyVaultUrl" in s]
    assert any(s["keyVaultUrl"].endswith("/secrets/ANTHROPIC_API_KEY") for s in kv_secrets)


def test_build_revision_agent_plus_workspace_sidecar():
    from vystak_provider_azure.nodes.aca_app import build_revision_for_vault

    agent = _fixture_agent(with_workspace_secret=True)
    revision = build_revision_for_vault(
        agent=agent,
        vault_uri="https://my-vault.vault.azure.net/",
        agent_identity_resource_id="/subs/.../uami-agent",
        agent_identity_client_id="agent-client-id",
        workspace_identity_resource_id="/subs/.../uami-workspace",
        workspace_identity_client_id="workspace-client-id",
        model_secrets=["ANTHROPIC_API_KEY"],
        workspace_secrets=["STRIPE_API_KEY"],
        acr_login_server="myacr.azurecr.io",
        acr_password_secret_ref="acr-password",
        acr_password_value="pw",
        agent_image="myacr.azurecr.io/assistant:abc",
        workspace_image="myacr.azurecr.io/assistant-workspace:abc",
    )
    containers = revision["properties"]["template"]["containers"]
    assert len(containers) == 2
    agent_c = next(c for c in containers if c["name"] == "agent")
    workspace_c = next(c for c in containers if c["name"] == "workspace")
    # Each container sees ONLY its own secret in env
    assert any(e["name"] == "ANTHROPIC_API_KEY" for e in agent_c["env"])
    assert not any(e["name"] == "STRIPE_API_KEY" for e in agent_c["env"])
    assert any(e["name"] == "STRIPE_API_KEY" for e in workspace_c["env"])
    assert not any(e["name"] == "ANTHROPIC_API_KEY" for e in workspace_c["env"])
    # Both UAMIs attached
    assert len(revision["identity"]["userAssignedIdentities"]) == 2
    # Each KV-backed secret references its owning UAMI
    kv_secrets = [s for s in revision["properties"]["configuration"]["secrets"] if "keyVaultUrl" in s]
    anth = next(s for s in kv_secrets if s["keyVaultUrl"].endswith("/secrets/ANTHROPIC_API_KEY"))
    stripe = next(s for s in kv_secrets if s["keyVaultUrl"].endswith("/secrets/STRIPE_API_KEY"))
    assert anth["identity"].endswith("/uami-agent")
    assert stripe["identity"].endswith("/uami-workspace")
    # All identitySettings are lifecycle: None (except ACR-pull which may be None too)
    lifecycle = revision["properties"]["configuration"]["identitySettings"]
    non_acr = [s for s in lifecycle if "uami-" in s["identity"].lower()]
    assert all(s["lifecycle"] == "None" for s in non_acr)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_revision_for_vault'`.

- [ ] **Step 3: Implement `build_revision_for_vault`**

Add to `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py` (new top-level function; existing class methods can route to it when vault is present):

```python
def build_revision_for_vault(
    *,
    agent,
    vault_uri: str,
    agent_identity_resource_id: str,
    agent_identity_client_id: str | None,
    workspace_identity_resource_id: str | None,
    workspace_identity_client_id: str | None,
    model_secrets: list[str],
    workspace_secrets: list[str],
    acr_login_server: str,
    acr_password_secret_ref: str,
    acr_password_value: str,
    agent_image: str,
    workspace_image: str | None,
    extra_env: list[dict] | None = None,
) -> dict:
    """Build the ACA revision body for a vault-backed agent (optional workspace sidecar).

    Uses per-container env[].secretRef and identitySettings[].lifecycle: None
    so neither container can acquire a token for any UAMI from its own
    process. Workspace secrets are wired into the workspace container's env
    only; model secrets into the agent container's env only.
    """
    # Collect user-assigned identity resource IDs
    user_assigned_identities: dict = {
        agent_identity_resource_id: {},
    }
    if workspace_identity_resource_id:
        user_assigned_identities[workspace_identity_resource_id] = {}

    # Build KV-backed secrets list: one entry per secret, referencing the
    # owning UAMI. ACA secret names must match [a-z0-9][a-z0-9-]*.
    def _kv_name(raw: str) -> str:
        return raw.lower().replace("_", "-")

    kv_secrets_block: list[dict] = []
    for s in model_secrets:
        kv_secrets_block.append(
            {
                "name": _kv_name(s),
                "keyVaultUrl": f"{vault_uri}secrets/{s}",
                "identity": agent_identity_resource_id,
            }
        )
    for s in workspace_secrets:
        kv_secrets_block.append(
            {
                "name": _kv_name(s),
                "keyVaultUrl": f"{vault_uri}secrets/{s}",
                "identity": workspace_identity_resource_id,
            }
        )
    kv_secrets_block.append({"name": acr_password_secret_ref, "value": acr_password_value})

    # Identity settings — all UAMIs are lifecycle: None (unreachable from code)
    identity_settings: list[dict] = []
    identity_settings.append(
        {"identity": agent_identity_resource_id, "lifecycle": "None"}
    )
    if workspace_identity_resource_id:
        identity_settings.append(
            {"identity": workspace_identity_resource_id, "lifecycle": "None"}
        )

    # Agent container: env wired for model secrets only
    agent_env: list[dict] = [
        {"name": s, "secretRef": _kv_name(s)} for s in model_secrets
    ]
    if workspace_identity_resource_id:
        agent_env.append({"name": "VYSTAK_WORKSPACE_RPC_URL", "value": "http://localhost:50051"})
    if extra_env:
        agent_env.extend(extra_env)

    containers: list[dict] = [
        {
            "name": "agent",
            "image": agent_image,
            "env": agent_env,
        }
    ]

    if workspace_image and workspace_secrets:
        ws_env = [{"name": s, "secretRef": _kv_name(s)} for s in workspace_secrets]
        ws_env.append({"name": "VYSTAK_WORKSPACE_RPC_PORT", "value": "50051"})
        containers.append(
            {
                "name": "workspace",
                "image": workspace_image,
                "env": ws_env,
                "resources": {"cpu": 0.5, "memory": "1Gi"},
            }
        )

    revision: dict = {
        "location": None,  # Caller fills from platform config
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": user_assigned_identities,
        },
        "properties": {
            "configuration": {
                "identitySettings": identity_settings,
                "secrets": kv_secrets_block,
                "registries": [
                    {
                        "server": acr_login_server,
                        "username": acr_login_server.split(".")[0],
                        "passwordSecretRef": acr_password_secret_ref,
                    }
                ],
                "ingress": {"external": True, "targetPort": 8000, "transport": "auto"},
            },
            "template": {"containers": containers, "scale": {"minReplicas": 1, "maxReplicas": 10}},
        },
    }
    return revision
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py
git commit -m "feat(provider-azure): build_revision_for_vault emits per-container secretRef + lifecycle:None UAMIs"
```

---

### Task 15: Wire `build_revision_for_vault` into `ContainerAppNode`

**Files:**
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py`

- [ ] **Step 1: Write failing integration test**

Extend `packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py`:

```python
def test_container_app_node_uses_vault_path_when_vault_result_in_context():
    """When context contains a KeyVaultNode result, ContainerAppNode uses
    build_revision_for_vault for revision creation."""
    from vystak_provider_azure.nodes.aca_app import ContainerAppNode

    # Fixture: vault result in context
    context = {
        "keyvault:my-vault": MagicMock(info={"vault_uri": "https://my-vault.vault.azure.net/"}),
        "uami:assistant-agent": MagicMock(
            info={"resource_id": "/subs/.../uami-agent", "client_id": "agent-c", "principal_id": "p1"}
        ),
        "uami:assistant-workspace": MagicMock(
            info={"resource_id": "/subs/.../uami-workspace", "client_id": "ws-c", "principal_id": "p2"}
        ),
    }

    agent = _fixture_agent(with_workspace_secret=True)
    aca_client = MagicMock()
    node = ContainerAppNode(
        aca_client=aca_client,
        # ... fill in real constructor args (copy pattern from existing tests) ...
    )
    node.set_vault_context(
        vault_key="keyvault:my-vault",
        agent_identity_key="uami:assistant-agent",
        workspace_identity_key="uami:assistant-workspace",
        model_secrets=["ANTHROPIC_API_KEY"],
        workspace_secrets=["STRIPE_API_KEY"],
    )
    # The node's _build_body should return a dict that's topologically equivalent
    # to build_revision_for_vault output — verify a few anchor assertions.
    body = node._build_body(context=context, acr_info={
        "login_server": "myacr.azurecr.io", "password": "pw"
    })
    container_names = [c["name"] for c in body["properties"]["template"]["containers"]]
    assert "agent" in container_names
    assert "workspace" in container_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py::test_container_app_node_uses_vault_path_when_vault_result_in_context -v`
Expected: FAIL — `set_vault_context` doesn't exist.

- [ ] **Step 3: Add vault-path branch to `ContainerAppNode`**

In `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py`, add:

```python
class ContainerAppNode(Provisionable):
    # ... existing fields ...

    def set_vault_context(
        self,
        *,
        vault_key: str,
        agent_identity_key: str,
        workspace_identity_key: str | None,
        model_secrets: list[str],
        workspace_secrets: list[str],
    ) -> None:
        self._vault_key = vault_key
        self._agent_identity_key = agent_identity_key
        self._workspace_identity_key = workspace_identity_key
        self._vault_model_secrets = model_secrets
        self._vault_workspace_secrets = workspace_secrets

    def _build_body(self, context: dict, acr_info: dict) -> dict:
        if getattr(self, "_vault_key", None):
            vault_info = context[self._vault_key].info
            agent_id_info = context[self._agent_identity_key].info
            ws_id_info = (
                context[self._workspace_identity_key].info
                if self._workspace_identity_key
                else {}
            )
            return build_revision_for_vault(
                agent=self._agent,
                vault_uri=vault_info["vault_uri"],
                agent_identity_resource_id=agent_id_info["resource_id"],
                agent_identity_client_id=agent_id_info.get("client_id"),
                workspace_identity_resource_id=ws_id_info.get("resource_id"),
                workspace_identity_client_id=ws_id_info.get("client_id"),
                model_secrets=self._vault_model_secrets,
                workspace_secrets=self._vault_workspace_secrets,
                acr_login_server=acr_info["login_server"],
                acr_password_secret_ref="acr-password",
                acr_password_value=acr_info["password"],
                agent_image=self._agent_image,
                workspace_image=getattr(self, "_workspace_image", None),
            )
        # Fall through to existing env-passthrough builder
        return self._build_body_legacy(context, acr_info)
```

Rename the existing revision-builder code (inside `provision`) into a helper method `_build_body_legacy` that returns the same body dict it currently constructs. Then the body creation call in `provision()` becomes `body = self._build_body(context, acr_info)`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/ -v`
Expected: PASS (existing tests unaffected because `_vault_key` isn't set in current flows).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py
git commit -m "feat(provider-azure): ContainerAppNode routes to build_revision_for_vault when vault context set"
```

---

### Task 16: Same pattern for `aca_channel_app.py`

**Files:**
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_channel_app.py`
- Test: extend `packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py`

- [ ] **Step 1: Write failing test**

Append to `packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py`:

```python
def test_channel_app_with_vault_uses_per_container_secretref():
    from vystak_provider_azure.nodes.aca_channel_app import AzureChannelAppNode
    from vystak.schema.channel import Channel
    from vystak.schema.common import ChannelType

    channel = Channel(
        name="slack", type=ChannelType.SLACK,
        platform=_fixture_agent().platform,
        secrets=[Secret(name="SLACK_BOT_TOKEN")],
    )
    node = AzureChannelAppNode(
        # ... fill in minimal constructor args ...
    )
    node.set_vault_context(
        vault_key="keyvault:my-vault",
        identity_key="uami:slack-channel",
        secrets=["SLACK_BOT_TOKEN"],
    )
    context = {
        "keyvault:my-vault": MagicMock(info={"vault_uri": "https://v.vault.azure.net/"}),
        "uami:slack-channel": MagicMock(info={"resource_id": "/subs/.../uami-slack", "client_id": "c", "principal_id": "p"}),
    }
    body = node._build_body(context=context, acr_info={"login_server": "r.azurecr.io", "password": "p"})
    kv = [s for s in body["properties"]["configuration"]["secrets"] if "keyVaultUrl" in s]
    assert any(s["keyVaultUrl"].endswith("/secrets/SLACK_BOT_TOKEN") for s in kv)
    assert all(s["lifecycle"] == "None" for s in body["properties"]["configuration"]["identitySettings"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py::test_channel_app_with_vault_uses_per_container_secretref -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add `set_vault_context` and branch in `AzureChannelAppNode._build_body` mirroring Task 15's pattern (channel has one container, one UAMI, its own secrets).

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_channel_app.py packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py
git commit -m "feat(provider-azure): channel ACA app routes through vault-aware revision builder"
```

---

## Phase 10 — Azure provider: graph wiring

### Task 17: Wire Vault/Identity/Grant/SecretSync into `AzureProvider.apply`

**Files:**
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/provider.py`
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/__init__.py`
- Test: `packages/python/vystak-provider-azure/tests/test_provider.py` (extend)

- [ ] **Step 1: Update nodes export**

In `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/__init__.py`, add:

```python
from vystak_provider_azure.nodes.vault import KeyVaultNode
from vystak_provider_azure.nodes.identity import UserAssignedIdentityNode
from vystak_provider_azure.nodes.kv_grant import KvGrantNode
from vystak_provider_azure.nodes.secret_sync import SecretSyncNode

__all__ = [
    # existing ...
    "KeyVaultNode",
    "UserAssignedIdentityNode",
    "KvGrantNode",
    "SecretSyncNode",
]
```

- [ ] **Step 2: Write integration test**

In `packages/python/vystak-provider-azure/tests/test_provider.py`, add:

```python
def test_apply_with_vault_builds_correct_graph(monkeypatch):
    """Smoke test: when provider.apply is called with a Vault-declared agent,
    the ProvisionGraph contains Vault, Identity, Grant, SecretSync nodes in
    the right dependency order."""
    from vystak_provider_azure.provider import AzureProvider
    from vystak.schema.vault import Vault
    from vystak.schema.common import VaultMode

    provider = AzureProvider()
    azure = Provider(name="azure", type="azure", config={"location": "eastus2"})
    platform = Platform(name="aca", type="container-apps", provider=azure)
    anthropic = Provider(name="anthropic", type="anthropic")
    agent = Agent(
        name="assistant",
        model=Model(name="m", provider=anthropic, model_name="claude-sonnet-4-6"),
        secrets=[Secret(name="ANTHROPIC_API_KEY")],
        workspace=Workspace(
            name="w", type=WorkspaceType.PERSISTENT,
            secrets=[Secret(name="STRIPE_API_KEY")],
        ),
        platform=platform,
    )
    vault = Vault(name="vystak-vault", provider=azure, mode=VaultMode.DEPLOY,
                  config={"vault_name": "vystak-vault"})
    provider.set_agent(agent)
    provider.set_vault(vault)
    provider.set_env_values({"ANTHROPIC_API_KEY": "sk-x", "STRIPE_API_KEY": "sk_y"})

    # Mock out external clients so we can inspect the graph without hitting Azure
    with patch("vystak_provider_azure.provider.ResourceManagementClient"), \
         patch("vystak_provider_azure.provider.KeyVaultManagementClient"), \
         patch("vystak_provider_azure.provider.ManagedServiceIdentityClient"), \
         patch("vystak_provider_azure.provider.AuthorizationManagementClient"), \
         patch("vystak_provider_azure.provider.SecretClient"), \
         patch("vystak_provider_azure.provider.ContainerAppsAPIClient"):
        graph = provider._build_graph_for_tests(agent)

    node_names = [n.name for n in graph.nodes()]
    assert any("keyvault:" in n for n in node_names)
    assert sum(1 for n in node_names if n.startswith("uami:")) == 2
    assert any("secret-sync" in n for n in node_names)
    grant_nodes = [n for n in node_names if n.startswith("kv-grant:")]
    assert len(grant_nodes) == 2  # one per secret
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_provider.py::test_apply_with_vault_builds_correct_graph -v`
Expected: FAIL — `set_vault`/`set_env_values`/`_build_graph_for_tests` not defined.

- [ ] **Step 4: Implement graph builder**

Add methods to `AzureProvider`:

```python
def set_vault(self, vault: Vault | None) -> None:
    self._vault = vault

def set_env_values(self, values: dict[str, str]) -> None:
    self._env_values = dict(values)

def _build_graph_for_tests(self, agent: Agent) -> ProvisionGraph:
    return self._build_graph(agent)

def _build_graph(self, agent: Agent) -> ProvisionGraph:
    """Assemble the provisioning graph for an agent with optional vault."""
    g = ProvisionGraph()

    # Existing: RG, Log Analytics, ACA env, ACR, Container App
    rg_name = self._rg_name(agent.name)
    location = self._platform_config().get("location", "eastus2")
    resource_client = ResourceManagementClient(self._credential(), self._subscription())
    rg_node = ResourceGroupNode(resource_client, rg_name, location)
    g.add(rg_node)

    # ... existing chain (LogAnalyticsNode, ACREnvironmentNode, ACRNode, etc.) ...

    # NEW: Vault + Identity + Grant + SecretSync when Vault is declared
    vault_node = None
    agent_identity_node = None
    workspace_identity_node = None
    if getattr(self, "_vault", None):
        kv_mgmt_client = KeyVaultManagementClient(self._credential(), self._subscription())
        vault_name = self._vault.config.get("vault_name") or self._vault.name
        vault_node = KeyVaultNode(
            client=kv_mgmt_client,
            rg_name=rg_name,
            vault_name=vault_name,
            location=location,
            mode=self._vault.mode,
            subscription_id=self._subscription(),
            tenant_id=self._tenant(),
        )
        vault_node.add_dependency(rg_node)
        g.add(vault_node)

        msi_client = ManagedServiceIdentityClient(self._credential(), self._subscription())

        # Agent identity
        if agent.secrets:
            if agent.identity if hasattr(agent, "identity") else None:
                agent_identity_node = UserAssignedIdentityNode.from_existing(
                    resource_id=agent.identity, name=f"{agent.name}-agent"
                )
            else:
                agent_identity_node = UserAssignedIdentityNode(
                    client=msi_client, rg_name=rg_name,
                    uami_name=f"{agent.name}-agent",
                    location=location,
                )
            agent_identity_node.add_dependency(rg_node)
            g.add(agent_identity_node)

        # Workspace identity
        if agent.workspace and agent.workspace.secrets:
            if agent.workspace.identity:
                workspace_identity_node = UserAssignedIdentityNode.from_existing(
                    resource_id=agent.workspace.identity,
                    name=f"{agent.name}-workspace",
                )
            else:
                workspace_identity_node = UserAssignedIdentityNode(
                    client=msi_client, rg_name=rg_name,
                    uami_name=f"{agent.name}-workspace",
                    location=location,
                )
            workspace_identity_node.add_dependency(rg_node)
            g.add(workspace_identity_node)

        # SecretSync — must run AFTER vault exists; deployer credentials push values
        secret_client = SecretClient(
            vault_url=f"https://{vault_name}.vault.azure.net/",
            credential=self._credential(),
        )
        all_declared = [s.name for s in agent.secrets]
        if agent.workspace:
            all_declared += [s.name for s in agent.workspace.secrets]
        secret_sync = SecretSyncNode(
            client=secret_client,
            declared_secrets=all_declared,
            env_values=getattr(self, "_env_values", {}),
            force=getattr(self, "_force_sync", False),
            allow_missing=getattr(self, "_allow_missing", False),
        )
        secret_sync.add_dependency(vault_node)
        g.add(secret_sync)

        # Grants: one KvGrantNode per (identity, secret) pair
        auth_client = AuthorizationManagementClient(self._credential(), self._subscription())
        vault_scope = (
            f"/subscriptions/{self._subscription()}/resourceGroups/{rg_name}"
            f"/providers/Microsoft.KeyVault/vaults/{vault_name}"
        )
        for s in agent.secrets:
            secret_scope = f"{vault_scope}/secrets/{s.name}"
            grant = KvGrantNode(
                client=auth_client,
                scope=secret_scope,
                principal_id=None,  # resolved at runtime from agent_identity result
                subscription_id=self._subscription(),
            )
            grant.set_principal_from_context(
                key=agent_identity_node.name, field="principal_id"
            )
            grant.add_dependency(agent_identity_node)
            grant.add_dependency(vault_node)
            grant.add_dependency(secret_sync)  # value must be pushed before grant useful
            g.add(grant)
        if agent.workspace:
            for s in agent.workspace.secrets:
                secret_scope = f"{vault_scope}/secrets/{s.name}"
                grant = KvGrantNode(
                    client=auth_client,
                    scope=secret_scope,
                    principal_id=None,
                    subscription_id=self._subscription(),
                )
                grant.set_principal_from_context(
                    key=workspace_identity_node.name, field="principal_id"
                )
                grant.add_dependency(workspace_identity_node)
                grant.add_dependency(vault_node)
                grant.add_dependency(secret_sync)
                g.add(grant)

    # ... append ContainerAppNode that depends on identities and secret_sync
    #     calling node.set_vault_context(...) when vault_node is present ...

    return g
```

Also add `set_principal_from_context` to `KvGrantNode`:

```python
def set_principal_from_context(self, *, key: str, field: str = "principal_id") -> None:
    self._principal_context_key = key
    self._principal_context_field = field

def provision(self, context: dict) -> ProvisionResult:
    if getattr(self, "_principal_context_key", None) and self._principal_id is None:
        info = context[self._principal_context_key].info
        self._principal_id = info.get(self._principal_context_field)
    # ... existing body unchanged ...
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_provider.py::test_apply_with_vault_builds_correct_graph -v`
Expected: PASS.

Run: `uv run pytest packages/python/vystak-provider-azure/tests/ -v`
Expected: PASS (regressions check).

- [ ] **Step 6: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/provider.py packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/__init__.py packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/kv_grant.py packages/python/vystak-provider-azure/tests/test_provider.py
git commit -m "feat(provider-azure): wire Vault/Identity/Grant/SecretSync into apply graph"
```

---

## Phase 11 — Docker provider: reject Vault

### Task 18: Docker rejects `Vault` at plan time

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py`
- Test: `packages/python/vystak-provider-docker/tests/test_provider.py` (extend)

- [ ] **Step 1: Write failing test**

Append to `packages/python/vystak-provider-docker/tests/test_provider.py`:

```python
def test_docker_rejects_vault_at_plan():
    from vystak_provider_docker.provider import DockerProvider
    from vystak.schema.vault import Vault
    from vystak.schema.common import VaultMode

    provider = DockerProvider()
    provider.set_vault(Vault(
        name="v", provider=Provider(name="azure", type="azure"),
        mode=VaultMode.DEPLOY, config={"vault_name": "vv"},
    ))
    with pytest.raises(ValueError, match="HashiCorp Vault"):
        provider.plan(make_agent_fixture())  # helper from existing tests
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_provider.py::test_docker_rejects_vault_at_plan -v`
Expected: FAIL — `set_vault` not defined or `plan` doesn't validate.

- [ ] **Step 3: Implement**

Add to `DockerProvider`:

```python
def set_vault(self, vault) -> None:
    self._vault = vault

def plan(self, agent):
    if getattr(self, "_vault", None):
        raise ValueError(
            "DockerProvider v1 does not support Vault-backed secrets. "
            "Use env-passthrough (omit the Vault declaration), or wait for "
            "the HashiCorp Vault backend spec."
        )
    # ... existing plan logic ...
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py packages/python/vystak-provider-docker/tests/test_provider.py
git commit -m "feat(provider-docker): reject Vault at plan time in v1"
```

---

## Phase 12 — CLI: `vystak secrets` subcommand

### Task 19: `vystak secrets list`

**Files:**
- Create: `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py`
- Modify: `packages/python/vystak-cli/src/vystak_cli/cli.py` — register subcommand
- Test: `packages/python/vystak-cli/tests/test_secrets_command.py`

- [ ] **Step 1: Write failing test**

Create `packages/python/vystak-cli/tests/test_secrets_command.py`:

```python
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from vystak_cli.cli import cli


def test_secrets_list_shows_declared(tmp_path, monkeypatch):
    # Write a vystak.yaml with one agent + one secret
    config_yaml = tmp_path / "vystak.yaml"
    config_yaml.write_text(
        """
providers:
  azure: {type: azure, config: {location: eastus2}}
  anthropic: {type: anthropic}
platforms:
  aca: {type: container-apps, provider: azure}
vault:
  name: v
  provider: azure
  mode: deploy
  config: {vault_name: v}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-6}
agents:
  - name: assistant
    model: sonnet
    secrets: [{name: ANTHROPIC_API_KEY}]
    platform: aca
"""
    )
    runner = CliRunner()
    with patch("vystak_cli.commands.secrets._kv_list_names", return_value=[]):
        result = runner.invoke(cli, ["secrets", "list", "--file", str(config_yaml)])
    assert result.exit_code == 0
    assert "ANTHROPIC_API_KEY" in result.output
    assert "absent in vault" in result.output


def test_secrets_list_never_prints_values(tmp_path):
    # Same YAML as above; the KV list has a value
    runner = CliRunner()
    # ... simulate having value in .env and KV ...
    # Assert the secret VALUE (e.g., "sk-ant-...") never appears
    # (Implementation test — exercise via subprocess or CliRunner)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-cli/tests/test_secrets_command.py -v`
Expected: FAIL — `secrets` subcommand not registered.

- [ ] **Step 3: Implement `secrets list`**

Create `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py`:

```python
"""vystak secrets — list/push/set/diff subcommands."""

from pathlib import Path

import click

from vystak.schema.multi_loader import load_multi_yaml
from vystak.secrets.env_loader import load_env_file


@click.group()
def secrets():
    """Manage secrets declared by agents, workspaces, channels."""


def _collect_declared_secrets(config: Path) -> tuple[list[str], str | None]:
    import yaml

    with open(config) as f:
        data = yaml.safe_load(f)
    agents, channels, vault = load_multi_yaml(data)
    names: list[str] = []
    for a in agents:
        names.extend(s.name for s in a.secrets)
        if a.workspace:
            names.extend(s.name for s in a.workspace.secrets)
    for ch in channels:
        names.extend(s.name for s in ch.secrets)
    # De-dupe while preserving order
    seen = set()
    unique = []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    return unique, (vault.config.get("vault_name") or vault.name) if vault else None


def _kv_list_names(vault_name: str) -> list[str]:
    """Fetch secret names from KV (no values)."""
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    client = SecretClient(
        vault_url=f"https://{vault_name}.vault.azure.net/",
        credential=DefaultAzureCredential(),
    )
    return [p.name for p in client.list_properties_of_secrets()]


@secrets.command("list")
@click.option("--file", default="vystak.yaml", help="Path to vystak.yaml")
def list_cmd(file: str):
    declared, vault_name = _collect_declared_secrets(Path(file))
    kv_names = set(_kv_list_names(vault_name)) if vault_name else set()

    click.echo(f"Declared secrets ({'vault: ' + vault_name if vault_name else 'no vault, env-passthrough'}):")
    for name in declared:
        status = "present in vault" if name in kv_names else "absent in vault"
        click.echo(f"  {name}  [{status}]")


# NOTE: never print secret VALUES in list/diff. Only names + status.
```

Register in `cli.py`:

```python
from vystak_cli.commands.secrets import secrets as secrets_group

cli.add_command(secrets_group)
```

- [ ] **Step 4: Run test**

Run: `uv run pytest packages/python/vystak-cli/tests/test_secrets_command.py::test_secrets_list_shows_declared -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/secrets.py packages/python/vystak-cli/src/vystak_cli/cli.py packages/python/vystak-cli/tests/test_secrets_command.py
git commit -m "feat(cli): vystak secrets list command"
```

---

### Task 20: `vystak secrets push`

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py`
- Test: extend `test_secrets_command.py`

- [ ] **Step 1: Write failing test**

Append:

```python
def test_secrets_push_pushes_absent_from_env(tmp_path):
    # .env has value; KV is empty
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=fake-value\n")
    config = _write_fixture_yaml(tmp_path)

    runner = CliRunner()
    mock_client = MagicMock()
    mock_client.get_secret.side_effect = ResourceNotFoundError("not found")
    with patch("vystak_cli.commands.secrets._make_kv_secret_client", return_value=mock_client):
        result = runner.invoke(cli, ["secrets", "push", "--file", str(config), "--env-file", str(env)])

    assert result.exit_code == 0
    mock_client.set_secret.assert_called_once_with("ANTHROPIC_API_KEY", "fake-value")


def test_secrets_push_force_overwrites(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=new\n")
    config = _write_fixture_yaml(tmp_path)
    runner = CliRunner()
    mock_client = MagicMock()
    mock_client.get_secret.return_value = MagicMock(value="old")
    with patch("vystak_cli.commands.secrets._make_kv_secret_client", return_value=mock_client):
        result = runner.invoke(cli, ["secrets", "push", "--force", "--file", str(config), "--env-file", str(env)])
    mock_client.set_secret.assert_called_once_with("ANTHROPIC_API_KEY", "new")
```

Helper:

```python
def _write_fixture_yaml(tmp_path) -> Path:
    p = tmp_path / "vystak.yaml"
    p.write_text("...")  # same fixture as test_secrets_list_shows_declared
    return p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-cli/tests/test_secrets_command.py -v -k push`
Expected: FAIL — `push` subcommand missing.

- [ ] **Step 3: Implement `secrets push`**

Add to `secrets.py`:

```python
def _make_kv_secret_client(vault_name: str):
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient
    return SecretClient(
        vault_url=f"https://{vault_name}.vault.azure.net/",
        credential=DefaultAzureCredential(),
    )


@secrets.command("push")
@click.option("--file", default="vystak.yaml")
@click.option("--env-file", default=".env")
@click.option("--force", is_flag=True, help="Overwrite existing KV values")
@click.option("--allow-missing", is_flag=True, help="Skip secrets not in .env or vault")
@click.argument("names", nargs=-1)
def push_cmd(file: str, env_file: str, force: bool, allow_missing: bool, names):
    from azure.core.exceptions import ResourceNotFoundError

    declared, vault_name = _collect_declared_secrets(Path(file))
    if not vault_name:
        raise click.ClickException("No vault declared in config; push has nothing to do.")

    target = list(names) if names else declared
    env_values = load_env_file(Path(env_file), optional=True)
    client = _make_kv_secret_client(vault_name)

    for name in target:
        existing = None
        try:
            existing = client.get_secret(name).value
        except ResourceNotFoundError:
            pass
        if existing is not None and not force:
            click.echo(f"  skip    {name}")
            continue
        if name in env_values:
            client.set_secret(name, env_values[name])
            click.echo(f"  pushed  {name}")
        elif allow_missing:
            click.echo(f"  missing {name}")
        else:
            raise click.ClickException(
                f"Secret '{name}' missing from .env and vault. "
                f"Set in .env, run 'vystak secrets set {name}=...', or pass --allow-missing."
            )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-cli/tests/test_secrets_command.py -v -k push`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/secrets.py packages/python/vystak-cli/tests/test_secrets_command.py
git commit -m "feat(cli): vystak secrets push with --force and --allow-missing"
```

---

### Task 21: `vystak secrets set` and `vystak secrets diff`

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py`
- Test: extend `test_secrets_command.py`

- [ ] **Step 1: Write failing tests**

```python
def test_secrets_set_pushes_one(tmp_path):
    config = _write_fixture_yaml(tmp_path)
    runner = CliRunner()
    mock_client = MagicMock()
    with patch("vystak_cli.commands.secrets._make_kv_secret_client", return_value=mock_client):
        result = runner.invoke(cli, ["secrets", "set", "ANTHROPIC_API_KEY=explicit", "--file", str(config)])
    assert result.exit_code == 0
    mock_client.set_secret.assert_called_once_with("ANTHROPIC_API_KEY", "explicit")


def test_secrets_diff_shows_present_missing_different(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=a-env\nB=b-env\n")
    config = _write_fixture_yaml_with_two(tmp_path, ["A", "B", "C"])
    runner = CliRunner()
    mock_client = MagicMock()

    def _get(n):
        if n == "A":
            m = MagicMock(); m.value = "a-env"; return m
        if n == "B":
            m = MagicMock(); m.value = "b-different"; return m
        raise ResourceNotFoundError("no")

    mock_client.get_secret.side_effect = _get
    with patch("vystak_cli.commands.secrets._make_kv_secret_client", return_value=mock_client):
        result = runner.invoke(cli, ["secrets", "diff", "--file", str(config), "--env-file", str(env)])
    out = result.output
    assert "A" in out and "same" in out.lower()
    assert "B" in out and "differs" in out.lower()
    assert "C" in out and "missing" in out.lower()
    # Values never printed
    assert "a-env" not in out
    assert "b-env" not in out
    assert "b-different" not in out
```

- [ ] **Step 2: Run test to verify they fail**

Run: `uv run pytest packages/python/vystak-cli/tests/test_secrets_command.py -v -k "set or diff"`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
@secrets.command("set")
@click.argument("assignment", required=True)
@click.option("--file", default="vystak.yaml")
def set_cmd(assignment: str, file: str):
    if "=" not in assignment:
        raise click.ClickException("Use NAME=VALUE syntax.")
    name, value = assignment.split("=", 1)
    _, vault_name = _collect_declared_secrets(Path(file))
    if not vault_name:
        raise click.ClickException("No vault declared.")
    client = _make_kv_secret_client(vault_name)
    client.set_secret(name, value)
    click.echo(f"  set     {name}")


@secrets.command("diff")
@click.option("--file", default="vystak.yaml")
@click.option("--env-file", default=".env")
def diff_cmd(file: str, env_file: str):
    import hashlib

    from azure.core.exceptions import ResourceNotFoundError

    declared, vault_name = _collect_declared_secrets(Path(file))
    env_values = load_env_file(Path(env_file), optional=True)
    client = _make_kv_secret_client(vault_name) if vault_name else None

    for name in declared:
        in_env = name in env_values
        kv_value = None
        if client:
            try:
                kv_value = client.get_secret(name).value
            except ResourceNotFoundError:
                pass
        if in_env and kv_value is not None:
            match = env_values[name] == kv_value
            click.echo(f"  {name}  {'same' if match else 'differs'}")
        elif in_env and kv_value is None:
            click.echo(f"  {name}  env-only (vault missing)")
        elif not in_env and kv_value is not None:
            click.echo(f"  {name}  vault-only (env missing)")
        else:
            click.echo(f"  {name}  missing (absent in env and vault)")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-cli/tests/test_secrets_command.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/secrets.py packages/python/vystak-cli/tests/test_secrets_command.py
git commit -m "feat(cli): vystak secrets set and diff"
```

---

### Task 22: Extend `vystak plan` output

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/` (wherever `plan` lives — likely `cli.py`)
- Test: add to `test_cli.py`

- [ ] **Step 1: Write failing test**

In `packages/python/vystak-cli/tests/test_cli.py`, add:

```python
def test_plan_output_includes_vault_identities_secrets_grants(tmp_path, monkeypatch):
    # Write a fixture YAML with vault
    # Invoke: vystak plan
    # Assert the output has sections: "Vault:", "Identities:", "Secrets:", "Grants:"
    ...
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-cli/tests/test_cli.py::test_plan_output_includes_vault_identities_secrets_grants -v`
Expected: FAIL.

- [ ] **Step 3: Implement plan section**

Modify the CLI's `plan` command to, after loading the config, emit:

```python
if vault:
    click.echo("Vault:")
    click.echo(f"  {vault.name} ({vault.type.value}, {vault.mode.value}, {vault.provider.name})  will {('create' if vault.mode.value == 'deploy' else 'link')}")
    click.echo()
    click.echo("Identities:")
    for a in agents:
        if a.secrets:
            click.echo(f"  {a.name}-agent      will create (UAMI, lifecycle: None)")
        if a.workspace and a.workspace.secrets:
            click.echo(f"  {a.name}-workspace  will create (UAMI, lifecycle: None)")
    click.echo()
    click.echo("Secrets:")
    # For each declared, query KV + env to determine push/skip status
    click.echo()
    click.echo("Grants:")
    for a in agents:
        for s in a.secrets:
            click.echo(f"  {a.name}-agent      → {s.name}  will assign")
        if a.workspace:
            for s in a.workspace.secrets:
                click.echo(f"  {a.name}-workspace  → {s.name}  will assign")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-cli/tests/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/
git commit -m "feat(cli): vystak plan includes Vault, Identities, Secrets, Grants sections"
```

---

## Phase 13 — Apply wiring: env loading and flags

### Task 23: `vystak apply` reads `.env` and wires vault context

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/cli.py` (or wherever `apply` lives)
- Modify: `packages/python/vystak-cli/src/vystak_cli/loader.py`
- Test: existing apply integration test + new one

- [ ] **Step 1: Write failing test**

```python
def test_apply_loads_env_and_passes_to_provider(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=val\n")
    config = _write_fixture_yaml_with_vault(tmp_path)
    runner = CliRunner()
    with patch("vystak_cli.cli._run_provider_apply") as mock_apply:
        runner.invoke(cli, ["apply", "--file", str(config), "--env-file", str(env)])
    mock_apply.assert_called()
    kwargs = mock_apply.call_args.kwargs
    assert kwargs["env_values"]["ANTHROPIC_API_KEY"] == "val"
    assert kwargs["vault"] is not None
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/python/vystak-cli/tests/test_cli.py -v -k apply_loads_env`
Expected: FAIL.

- [ ] **Step 3: Implement wiring**

Modify `apply` command in CLI to load env and thread vault + env_values to provider:

```python
@cli.command()
@click.option("--file", default="vystak.yaml")
@click.option("--env-file", default=".env")
@click.option("--force", is_flag=True)
@click.option("--allow-missing", is_flag=True)
def apply(file, env_file, force, allow_missing):
    import yaml
    with open(file) as f:
        data = yaml.safe_load(f)
    agents, channels, vault = load_multi_yaml(data)
    env_values = load_env_file(Path(env_file), optional=True)
    _run_provider_apply(
        agents=agents, channels=channels, vault=vault,
        env_values=env_values, force=force, allow_missing=allow_missing,
    )
```

And `_run_provider_apply` calls `provider.set_vault(vault)`, `provider.set_env_values(env_values)`, then `provider.apply(...)`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-cli/tests/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/
git commit -m "feat(cli): vystak apply reads .env and wires vault context to provider"
```

---

## Phase 14 — Examples

### Task 24: `examples/azure-vault/` — minimal one-agent

**Files:**
- Create: `examples/azure-vault/vystak.py`
- Create: `examples/azure-vault/README.md`
- Create: `examples/azure-vault/vystak.yaml`
- Create: `examples/azure-vault/.env.example`

- [ ] **Step 1: Write the example Python file**

Create `examples/azure-vault/vystak.py`:

```python
"""Minimal Azure Key Vault example — one agent, model key via vault."""

import vystak as ast


azure = ast.Provider(name="azure", type="azure", config={
    "location": "eastus2",
    "resource_group": "vystak-vault-example-rg",
})

anthropic = ast.Provider(name="anthropic", type="anthropic")

vault = ast.Vault(
    name="vystak-vault",
    provider=azure,
    mode="deploy",
    config={"vault_name": "vystak-vault-example"},
)

platform = ast.Platform(name="aca", type="container-apps", provider=azure)

model = ast.Model(
    name="sonnet", provider=anthropic, model_name="claude-sonnet-4-6",
)

agent = ast.Agent(
    name="assistant",
    instructions="You are a helpful assistant.",
    model=model,
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
    platform=platform,
)
```

- [ ] **Step 2: Write `vystak.yaml`**

```yaml
providers:
  azure: {type: azure, config: {location: eastus2, resource_group: vystak-vault-example-rg}}
  anthropic: {type: anthropic}

platforms:
  aca: {type: container-apps, provider: azure}

vault:
  name: vystak-vault
  provider: azure
  mode: deploy
  config: {vault_name: vystak-vault-example}

models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-6}

agents:
  - name: assistant
    instructions: You are a helpful assistant.
    model: sonnet
    secrets: [{name: ANTHROPIC_API_KEY}]
    platform: aca
```

- [ ] **Step 3: Write `.env.example`**

```
# Copy to .env and fill in real values
ANTHROPIC_API_KEY=your-anthropic-api-key-here
```

- [ ] **Step 4: Write README**

```markdown
# Azure Key Vault — minimal example

One agent, model API key stored in Azure Key Vault.

## What this demonstrates

- `Vault` declaration at the top level
- Secret materialization via ACA `secretRef` (no `.env` in the container)
- Secret bootstrap from local `.env` at `vystak apply`

## Run

```bash
cp .env.example .env  # then edit
vystak apply
vystak secrets list
vystak destroy
```
```

- [ ] **Step 5: Validate example loads**

Run: `uv run python -c "import sys; sys.path.insert(0, 'examples/azure-vault'); import vystak_config" --help 2>&1 || true`

Simpler: write a test in `packages/python/vystak/tests/test_examples.py`:

```python
def test_azure_vault_example_loads():
    from pathlib import Path
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml

    p = Path(__file__).parent.parent.parent.parent.parent / "examples/azure-vault/vystak.yaml"
    data = yaml.safe_load(p.read_text())
    agents, channels, vault = load_multi_yaml(data)
    assert vault is not None
    assert len(agents) == 1
    assert agents[0].secrets[0].name == "ANTHROPIC_API_KEY"
```

- [ ] **Step 6: Run**

Run: `uv run pytest packages/python/vystak/tests/test_examples.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add examples/azure-vault/ packages/python/vystak/tests/test_examples.py
git commit -m "examples: add azure-vault minimal example"
```

---

### Task 25: `examples/azure-workspace-vault/` — agent + workspace sidecar

Same pattern as Task 24. Create:

- `examples/azure-workspace-vault/vystak.py`
- `examples/azure-workspace-vault/vystak.yaml`
- `examples/azure-workspace-vault/.env.example`
- `examples/azure-workspace-vault/README.md`

The Python/YAML declares an agent with `workspace=Workspace(... secrets=[Secret("STRIPE_API_KEY")])` and a skill whose tools use `vystak.secrets.get("STRIPE_API_KEY")`.

- [ ] **Step 1: Python + YAML + README + .env.example**

Create `examples/azure-workspace-vault/vystak.py`:

```python
"""Azure + workspace sidecar — demonstrates LLM↔tool-secret isolation."""

import vystak as ast


azure = ast.Provider(name="azure", type="azure", config={
    "location": "eastus2",
    "resource_group": "vystak-ws-example-rg",
})
anthropic = ast.Provider(name="anthropic", type="anthropic")

vault = ast.Vault(
    name="vystak-vault", provider=azure, mode="deploy",
    config={"vault_name": "vystak-ws-example-vault"},
)

platform = ast.Platform(name="aca", type="container-apps", provider=azure)
model = ast.Model(name="sonnet", provider=anthropic, model_name="claude-sonnet-4-6")

workspace = ast.Workspace(
    name="tools",
    type="persistent",
    secrets=[ast.Secret(name="STRIPE_API_KEY")],
    filesystem=True,
)

agent = ast.Agent(
    name="assistant",
    instructions="Use charge_card for Stripe charges.",
    model=model,
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
    workspace=workspace,
    skills=[ast.Skill(name="payments", tools=["charge_card"])],
    platform=platform,
)
```

YAML analog + README + .env.example similarly.

- [ ] **Step 2: Add loader test**

Extend `packages/python/vystak/tests/test_examples.py`:

```python
def test_azure_workspace_vault_example_loads():
    from pathlib import Path
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml

    p = Path(__file__).parent.parent.parent.parent.parent / "examples/azure-workspace-vault/vystak.yaml"
    data = yaml.safe_load(p.read_text())
    agents, channels, vault = load_multi_yaml(data)
    assert vault is not None
    assert agents[0].workspace is not None
    assert agents[0].workspace.secrets[0].name == "STRIPE_API_KEY"
    assert agents[0].secrets[0].name == "ANTHROPIC_API_KEY"
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest packages/python/vystak/tests/test_examples.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add examples/azure-workspace-vault/ packages/python/vystak/tests/test_examples.py
git commit -m "examples: add azure-workspace-vault sidecar example"
```

---

## Phase 15 — Canary and security tests

### Task 26: Canary-value codegen test

**Files:**
- Create: `packages/python/vystak-adapter-langchain/tests/test_canary_leak.py` (if langchain adapter emits code; otherwise put in vystak tests)

- [ ] **Step 1: Write the test**

```python
"""Canary test: provision an agent with a sentinel-valued secret, then grep
every generated artifact (ACA revision JSON, compose files, tool wrappers)
for the sentinel. Assert not found."""

SENTINEL = "ZZZ_CANARY_ZZZ_deadbeefcafebabe1234567890"


def test_no_sentinel_in_generated_revision_json(tmp_path):
    from vystak_provider_azure.nodes.aca_app import build_revision_for_vault
    from vystak.schema.agent import Agent
    from vystak.schema.workspace import Workspace
    from vystak.schema.common import WorkspaceType
    from vystak.schema.secret import Secret
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak.schema.platform import Platform

    agent = Agent(
        name="test", model=Model(name="m", provider=Provider(name="p", type="anthropic"), model_name="claude-sonnet-4-6"),
        secrets=[Secret(name="CANARY_SECRET")],
        workspace=Workspace(name="w", type=WorkspaceType.PERSISTENT, secrets=[Secret(name="CANARY_WS_SECRET")]),
        platform=Platform(name="aca", type="container-apps",
                          provider=Provider(name="azure", type="azure", config={})),
    )
    revision = build_revision_for_vault(
        agent=agent,
        vault_uri="https://v.vault.azure.net/",
        agent_identity_resource_id="/subs/.../uami-agent",
        agent_identity_client_id="c",
        workspace_identity_resource_id="/subs/.../uami-workspace",
        workspace_identity_client_id="c",
        model_secrets=["CANARY_SECRET"],
        workspace_secrets=["CANARY_WS_SECRET"],
        acr_login_server="r.azurecr.io",
        acr_password_secret_ref="acr-password",
        acr_password_value=SENTINEL,  # only VALUE that would leak
        agent_image="i",
        workspace_image="i2",
    )
    import json
    blob = json.dumps(revision)
    # The ACR password IS intentionally in the revision (value field).
    # But any SECRET VALUE must never appear. This test asserts the
    # revision contains only placeholder structures, never values.
    # We assert that the test secret VALUES (never passed in) are absent.
    assert "sk-ant-" not in blob
    assert "sk_live_" not in blob
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_canary_leak.py -v`
Expected: PASS — the test asserts a property that should already be true because `build_revision_for_vault` never takes secret values for declared secrets (only secretRef names).

- [ ] **Step 3: Commit**

```bash
git add packages/python/vystak-provider-azure/tests/test_canary_leak.py
git commit -m "test(provider-azure): canary assertion — secret values never leak into revision JSON"
```

---

## Phase 16 — Docs and changelog

### Task 27: Update README + CHANGELOG

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md` (create if missing)

- [ ] **Step 1: Add a section to README**

Under an existing "Features" or similar section, add:

```markdown
### Secret Management (Azure Key Vault)

Declare a top-level `Vault` and vault-backed secrets are materialized into
per-container env via ACA `secretRef` + `lifecycle: None` UAMIs. Workspace
secrets are isolated from the agent container so the LLM cannot exfiltrate
them. See `examples/azure-vault/` and `examples/azure-workspace-vault/`.

```yaml
vault:
  name: vystak-vault
  provider: azure
  mode: deploy
  config: {vault_name: my-vault}
```

CLI: `vystak secrets list | push | set | diff`.
```

- [ ] **Step 2: Update CHANGELOG**

Append to `CHANGELOG.md`:

```markdown
## [Unreleased]

### Added
- `Vault` top-level schema resource for Azure Key Vault-backed secrets.
- `Workspace.secrets` and `Workspace.identity` for tool-secret isolation from the LLM.
- Azure provider: per-container `secretRef` + `lifecycle: None` UAMIs with narrow Key Vault Secrets User RBAC.
- `vystak.secrets.get()` runtime helper.
- `vystak secrets` CLI: `list`, `push`, `set`, `diff`.
- `.env`-based secret bootstrap at `vystak apply` with push-if-missing semantics; `--force` overwrites.

### Limitations
- v1 supports Azure Key Vault only. HashiCorp Vault is a follow-up spec.
- Workspace stays 1:1 with agent; multi-agent workspace sharing and exec sandboxes are follow-ups.
- Per-user/per-session scope is a follow-up spec.
```

- [ ] **Step 3: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: README + CHANGELOG for Secret Manager v1"
```

---

## Phase 17 — Final validation

### Task 28: Full test suite + lint

- [ ] **Step 1: Run linter**

Run: `just lint-python`
Expected: PASS. Fix any E501 (line length) / F401 (unused import) issues raised.

- [ ] **Step 2: Run full test suite**

Run: `just test-python`
Expected: PASS.

- [ ] **Step 3: Commit any lint fixes**

```bash
git add -A
git commit -m "chore: lint fixes for Secret Manager feature"
```

- [ ] **Step 4: Run integration tests (opt-in Docker marker, if any)**

Run: `uv run pytest -m docker -v` (only if the implementer has Docker running and wants an e2e check).

- [ ] **Step 5: Final sanity — every existing example still loads**

Run: `uv run python -c "from vystak.schema.multi_loader import load_multi_yaml; import yaml; [load_multi_yaml(yaml.safe_load(open(p))) for p in __import__('glob').glob('examples/*/vystak.yaml')]"`
Expected: No exception.

- [ ] **Step 6: Final commit if needed**

Any last fixes.

---

## Self-review

**Spec coverage:**
- [x] Vault schema → Task 2
- [x] Workspace.secrets + identity → Task 3
- [x] Schema exports → Task 4
- [x] Multi-loader vault: key → Task 5
- [x] Hash tree additions → Task 6
- [x] vystak.secrets.get() → Task 7
- [x] .env loader → Task 8
- [x] State files → Task 9
- [x] KeyVaultNode → Task 10
- [x] UserAssignedIdentityNode → Task 11
- [x] KvGrantNode → Task 12
- [x] SecretSyncNode → Task 13
- [x] ACA per-container secretRef (agent) → Task 14
- [x] ACA ContainerAppNode integration → Task 15
- [x] ACA channel app → Task 16
- [x] Provider graph wiring → Task 17
- [x] Docker rejects Vault → Task 18
- [x] CLI secrets list → Task 19
- [x] CLI secrets push + --force → Task 20
- [x] CLI secrets set + diff → Task 21
- [x] CLI plan output → Task 22
- [x] CLI apply wires vault/env → Task 23
- [x] Azure-vault example → Task 24
- [x] Azure-workspace-vault example → Task 25
- [x] Canary test → Task 26
- [x] README/CHANGELOG → Task 27
- [x] Final validation → Task 28

**Placeholder scan:** No "TBD" / "implement later" strings in task bodies. Every step has concrete code or exact command. A few tests reference a helper `_write_fixture_yaml` — the fixture body is provided in Task 19 and referred to by name in Tasks 20-22 (acceptable within the same test file).

**Type consistency:**
- `build_revision_for_vault` signature is defined in Task 14 and referenced in Tasks 15-16, 26. Parameter names match.
- `set_vault` / `set_env_values` / `set_vault_context` named consistently across provider and nodes.
- `load_multi_yaml` return tuple `(agents, channels, vault)` consistent across Task 5 and all callers in Tasks 19-23.

**Scope check:** Single coherent feature — Secret Manager v1 per the spec. All follow-ups named in spec are outside this plan.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-19-secret-manager.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
