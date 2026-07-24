# Workspace Volumes — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** First-class named `Volume` objects for workspace persistence, mapped to Docker volumes and Azure Files (SMB + NFS premium), with sharing, retention, and full back-compat for the `persistence:` string.

**Architecture:** New `Volume(NamedModel)` in `vystak.schema`; `Workspace` gains a `volume` reference and an `effective_volume` property that normalizes both new and legacy config, so providers consume exactly one shape. The multi-loader parses a top-level `volumes:` mapping and resolves string refs. Providers map volume intent to backends; retention is recorded in Docker labels so destroy can honor it without the schema object.

**Tech Stack:** Python 3.11+, Pydantic v2, docker SDK, azure-mgmt-storage / azure-mgmt-appcontainers, pytest.

**Spec:** `docs/superpowers/specs/2026-07-23-workspace-volume-design.md` (this plan covers Phase 1 only; Phase 2 — snapshot/restore/clone — gets its own plan after Phase 1 lands).

## Global Constraints

- Run all commands from the repo root. Python tests: `uv run pytest <path> -v`.
- Lint gate before each commit: `just lint-python` (ruff). Do NOT run `just typecheck-python` as a gate — it has ~370 pre-existing failures.
- Named volume resources: Docker volume / Azure Files share `vystak-volume-<name>`. Implicit (legacy) volumes keep `vystak-<agent>-workspace-data`.
- `Volume.retention` must NOT affect the deploy hash.
- `volumes:` in YAML is a mapping keyed by name (like `providers`/`platforms`/`models`), not a list.
- This is a public repo: examples use placeholder values only (`YOUR_SUBSCRIPTION_ID`, `<your-api-key>`).

---

### Task 1: `Volume` schema model

**Files:**
- Create: `packages/python/vystak/src/vystak/schema/volume.py`
- Modify: `packages/python/vystak/src/vystak/schema/__init__.py` (import at line 64 area, `__all__` at line 110 area)
- Test: `packages/python/vystak/tests/test_volume_schema.py`

**Interfaces:**
- Produces: `class Volume(NamedModel)` with fields `mode: Literal["persistent","ephemeral","bind"] = "persistent"`, `performance: Literal["standard","premium"] = "standard"`, `retention: Literal["retain","delete"] = "retain"`, `path: str | None = None`. Exported from `vystak.schema`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/python/vystak/tests/test_volume_schema.py
"""Tests for the Volume model (workspace persistence, Phase 1)."""

import pytest
from pydantic import ValidationError as PydanticValidationError
from vystak.schema.volume import Volume


def test_volume_defaults():
    vol = Volume(name="team-code")
    assert vol.mode == "persistent"
    assert vol.performance == "standard"
    assert vol.retention == "retain"
    assert vol.path is None


def test_volume_bind_requires_path():
    with pytest.raises(PydanticValidationError, match="mode='bind' requires path"):
        Volume(name="local-src", mode="bind")


def test_volume_bind_with_path_valid():
    vol = Volume(name="local-src", mode="bind", path="~/code")
    assert vol.path == "~/code"


def test_volume_non_bind_rejects_path():
    with pytest.raises(PydanticValidationError, match="path= is only valid"):
        Volume(name="team-code", mode="persistent", path="~/code")


def test_volume_invalid_mode_rejected():
    with pytest.raises(PydanticValidationError):
        Volume(name="x", mode="shared")


def test_volume_name_must_be_resource_safe():
    # Azure Files share names: lowercase alphanumerics + hyphens.
    with pytest.raises(PydanticValidationError, match="lowercase alphanumerics"):
        Volume(name="Team_Code")


def test_volume_importable_from_schema_package():
    from vystak.schema import Volume as V

    assert V is Volume
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_volume_schema.py -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'vystak.schema.volume'`

- [ ] **Step 3: Write the model**

```python
# packages/python/vystak/src/vystak/schema/volume.py
"""Volume model — named workspace persistence (Phase 1).

See docs/superpowers/specs/2026-07-23-workspace-volume-design.md.
The volume declares intent; providers map it to a backend:
Docker named volume / Azure Files SMB (standard) / Azure Files NFS (premium).
"""

import re
from typing import Literal, Self

from pydantic import model_validator

from vystak.schema.common import NamedModel

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class Volume(NamedModel):
    """Named persistence for workspaces. Referenced by Workspace.volume."""

    mode: Literal["persistent", "ephemeral", "bind"] = "persistent"
    performance: Literal["standard", "premium"] = "standard"
    retention: Literal["retain", "delete"] = "retain"
    path: str | None = None  # bind mode only

    @model_validator(mode="after")
    def _validate_name(self) -> Self:
        if not _NAME_RE.match(self.name):
            raise ValueError(
                f"Volume name '{self.name}' must be lowercase alphanumerics "
                f"and hyphens (it becomes a Docker volume / Azure Files "
                f"share name)."
            )
        return self

    @model_validator(mode="after")
    def _validate_path(self) -> Self:
        if self.mode == "bind" and not self.path:
            raise ValueError(
                f"Volume '{self.name}' has mode='bind' requires path= "
                f"to specify the host directory to mount."
            )
        if self.mode != "bind" and self.path:
            raise ValueError(
                f"Volume '{self.name}': path= is only valid with mode='bind'."
            )
        return self
```

Then in `packages/python/vystak/src/vystak/schema/__init__.py`, next to the existing workspace import/export (lines 64 and 110):

```python
from vystak.schema.volume import Volume
```

and add `"Volume",` to `__all__` (alphabetical, near `"Vault",`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak/tests/test_volume_schema.py -v`
Expected: 7 passed

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak/src/vystak/schema/volume.py \
        packages/python/vystak/src/vystak/schema/__init__.py \
        packages/python/vystak/tests/test_volume_schema.py
git commit -m "feat(schema): Volume model for named workspace persistence"
```

---

### Task 2: `Workspace.volume` field + `effective_volume` normalization

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/workspace.py`
- Test: `packages/python/vystak/tests/test_workspace_schema.py` (append)

**Interfaces:**
- Consumes: `Volume` from Task 1.
- Produces: `Workspace.volume: Volume | str | None = None` (str = unresolved named reference, resolved by the multi-loader in Task 3). `Workspace.effective_volume -> Volume` property — the ONLY shape providers consume from Task 5 on. For legacy config it maps `persistence: volume/bind/ephemeral` → `mode: persistent/bind/ephemeral` and carries `path` through. Explicit-vs-implicit detection for providers: `ws.volume is not None` → explicit named volume.

- [ ] **Step 1: Write the failing tests** (append to `test_workspace_schema.py`)

```python
# --- Volume reference (Phase 1) -------------------------------------------

def test_workspace_volume_and_persistence_mutually_exclusive():
    from vystak.schema.volume import Volume

    with pytest.raises(PydanticValidationError, match="mutually exclusive"):
        Workspace(
            name="dev",
            image="python:3.12-slim",
            persistence="ephemeral",
            volume=Volume(name="team-code"),
        )


def test_effective_volume_from_explicit_volume():
    from vystak.schema.volume import Volume

    ws = Workspace(
        name="dev", image="python:3.12-slim", volume=Volume(name="team-code")
    )
    vol = ws.effective_volume
    assert vol.name == "team-code"
    assert vol.mode == "persistent"


def test_effective_volume_implicit_from_persistence_default():
    ws = Workspace(name="dev", image="python:3.12-slim")
    vol = ws.effective_volume
    assert vol.mode == "persistent"
    assert vol.retention == "retain"
    assert ws.volume is None  # implicit — providers use legacy naming


def test_effective_volume_implicit_bind_carries_path():
    ws = Workspace(
        name="dev", image="python:3.12-slim", persistence="bind", path="/tmp/proj"
    )
    vol = ws.effective_volume
    assert vol.mode == "bind"
    assert vol.path == "/tmp/proj"


def test_effective_volume_implicit_ephemeral():
    ws = Workspace(name="dev", image="python:3.12-slim", persistence="ephemeral")
    assert ws.effective_volume.mode == "ephemeral"


def test_effective_volume_unresolved_string_reference_raises():
    ws = Workspace(name="dev", image="python:3.12-slim", volume="team-code")
    with pytest.raises(ValueError, match="never resolved"):
        _ = ws.effective_volume
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_workspace_schema.py -v -k "volume or effective"`
Expected: FAIL — `Workspace` has no field `volume` (Pydantic "Extra inputs are not permitted" or attribute error)

- [ ] **Step 3: Implement**

In `workspace.py`, add the import at the top:

```python
from vystak.schema.volume import Volume
```

Add the field in the "Filesystem / persistence" section (after `path`, line 29):

```python
    # Named volume reference (Phase 1 — see
    # docs/superpowers/specs/2026-07-23-workspace-volume-design.md).
    # str = unresolved name reference; the multi-loader resolves it to a
    # Volume. persistence=/path= remain as the legacy implicit form.
    volume: Volume | str | None = None
```

Add after the existing validators (module-level mapping above the class or inside the file near the validators):

```python
_PERSISTENCE_TO_MODE = {
    "volume": "persistent",
    "bind": "bind",
    "ephemeral": "ephemeral",
}
```

and on the class:

```python
    @model_validator(mode="after")
    def _validate_volume_exclusivity(self) -> Self:
        if self.volume is not None and (
            "persistence" in self.model_fields_set or "path" in self.model_fields_set
        ):
            raise ValueError(
                f"Workspace '{self.name}': volume= is mutually exclusive with "
                f"the legacy persistence=/path= fields. Declare persistence "
                f"on the named volume instead."
            )
        return self

    @property
    def effective_volume(self) -> Volume:
        """Normalized persistence config. The only shape providers consume.

        Explicit named volume → returned as-is. Legacy persistence string →
        an implicit per-agent Volume (providers keep legacy resource naming
        for it, detected via ``ws.volume is None``).
        """
        if isinstance(self.volume, Volume):
            return self.volume
        if isinstance(self.volume, str):
            raise ValueError(
                f"Workspace '{self.name}': volume reference "
                f"'{self.volume}' was never resolved. Named volumes require "
                f"the multi-doc layout (top-level volumes: section) loaded "
                f"via load_multi_yaml."
            )
        return Volume(
            name=f"{self.name}-implicit",
            mode=_PERSISTENCE_TO_MODE.get(self.persistence, "persistent"),
            path=self.path,
        )
```

Note: `_validate_bind_path` (existing) still guards the legacy form; `Volume._validate_path` guards the new form. `effective_volume` constructs the implicit Volume with `path` only when bind (non-bind + path is already rejected by `_validate_bind_path` semantics — but legacy allowed `path` with non-bind persistence silently; to stay compatible, pass `path=self.path if _PERSISTENCE_TO_MODE.get(self.persistence) == "bind" else None`). Use that exact guard in the return statement:

```python
        mode = _PERSISTENCE_TO_MODE.get(self.persistence, "persistent")
        return Volume(
            name=f"{self.name}-implicit",
            mode=mode,
            path=self.path if mode == "bind" else None,
        )
```

Implicit-name note: `NamedModel.name` is required and the implicit name never becomes a resource name (providers use legacy naming when `ws.volume is None`), but it must satisfy the `Volume` name regex — `Workspace.name` values in this repo are lowercase (`dev`, `ws`); if a workspace name has uppercase, lowercase it: `name=f"{self.name.lower()}-implicit"`. Use the `.lower()` form.

- [ ] **Step 4: Run the full workspace + volume schema tests**

Run: `uv run pytest packages/python/vystak/tests/test_workspace_schema.py packages/python/vystak/tests/test_volume_schema.py -v`
Expected: all pass (pre-existing + new)

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak/src/vystak/schema/workspace.py \
        packages/python/vystak/tests/test_workspace_schema.py
git commit -m "feat(schema): Workspace.volume reference + effective_volume normalization"
```

---

### Task 3: multi-loader `volumes:` section + platform validation

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/multi_loader.py`
- Test: `packages/python/vystak/tests/test_multi_loader_workspace.py` (append)

**Interfaces:**
- Consumes: `Volume`, `Workspace.effective_volume`.
- Produces: `load_multi_yaml` parses top-level `volumes: {name: cfg}`, resolves `agents[*].workspace.volume` string refs to shared `Volume` objects, and validates platform compatibility via `_validate_workspace_platform_volume(agent)` (replaces `_validate_workspace_platform_persistence`). Return signature unchanged: `(agents, channels, vault)`.

- [ ] **Step 1: Write the failing tests** (append to `test_multi_loader_workspace.py`)

```python
# --- volumes: section (Phase 1) -------------------------------------------

def test_named_volume_resolves_onto_workspace():
    data = copy.deepcopy(BASE_CONFIG)
    data["volumes"] = {"team-code": {"mode": "persistent"}}
    data["agents"][0]["workspace"] = {
        "name": "dev",
        "image": "python:3.12-slim",
        "volume": "team-code",
    }
    agents, _channels, _vault = load_multi_yaml(data)
    ws = agents[0].workspace
    assert ws is not None
    from vystak.schema.volume import Volume

    assert isinstance(ws.volume, Volume)
    assert ws.effective_volume.name == "team-code"


def test_unknown_volume_reference_raises():
    import pytest

    data = copy.deepcopy(BASE_CONFIG)
    data["volumes"] = {"team-code": {}}
    data["agents"][0]["workspace"] = {
        "name": "dev",
        "image": "python:3.12-slim",
        "volume": "does-not-exist",
    }
    with pytest.raises(KeyError, match="Unknown volume 'does-not-exist'"):
        load_multi_yaml(data)


def test_two_agents_share_one_volume():
    data = copy.deepcopy(BASE_CONFIG)
    data["volumes"] = {"team-code": {}}
    second = copy.deepcopy(data["agents"][0])
    second["name"] = "reviewer"
    data["agents"].append(second)
    for agent_data in data["agents"]:
        agent_data["workspace"] = {
            "name": "dev",
            "image": "python:3.12-slim",
            "volume": "team-code",
        }
    agents, _channels, _vault = load_multi_yaml(data)
    assert agents[0].workspace.effective_volume.name == "team-code"
    assert agents[1].workspace.effective_volume.name == "team-code"


def test_bind_volume_rejected_on_container_apps():
    import pytest

    data = copy.deepcopy(BASE_CONFIG)
    data["providers"]["azure"] = {"type": "azure"}
    data["platforms"]["aca"] = {"type": "container-apps", "provider": "azure"}
    data["volumes"] = {"local-src": {"mode": "bind", "path": "~/code"}}
    data["agents"][0]["platform"] = "aca"
    data["agents"][0]["workspace"] = {
        "name": "dev",
        "image": "python:3.12-slim",
        "volume": "local-src",
    }
    with pytest.raises(ValueError, match="mode='bind'.*Container Apps"):
        load_multi_yaml(data)


def test_legacy_bind_persistence_still_rejected_on_container_apps():
    import pytest

    data = copy.deepcopy(BASE_CONFIG)
    data["providers"]["azure"] = {"type": "azure"}
    data["platforms"]["aca"] = {"type": "container-apps", "provider": "azure"}
    data["agents"][0]["platform"] = "aca"
    data["agents"][0]["workspace"] = {
        "name": "dev",
        "image": "python:3.12-slim",
        "persistence": "bind",
        "path": "/tmp/src",
    }
    with pytest.raises(ValueError, match="mode='bind'.*Container Apps"):
        load_multi_yaml(data)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_multi_loader_workspace.py -v`
Expected: the 5 new tests FAIL (volume ref stays a string / no KeyError raised); pre-existing tests still pass.

- [ ] **Step 3: Implement**

In `multi_loader.py`:

Add import:

```python
from vystak.schema.volume import Volume
```

Replace `_validate_workspace_platform_persistence` (lines 61–76) entirely with:

```python
def _validate_workspace_platform_volume(agent: Agent) -> None:
    """Reject volume modes unsupported by the target platform.

    ACA (container-apps) has no host filesystem — mode='bind' is
    fundamentally unserviceable. Catch it at load time with an actionable
    message so users aren't debugging a failed deploy later.
    """
    ws = agent.workspace
    if ws is None:
        return
    vol = ws.effective_volume
    if vol.mode == "bind" and agent.platform.type == "container-apps":
        raise ValueError(
            f"Agent '{agent.name}': workspace volume '{vol.name}' has "
            f"mode='bind', which is not supported on Azure Container Apps "
            f"(no host filesystem). Use mode='persistent' (Azure Files) "
            f"or 'ephemeral'."
        )
```

In `load_multi_yaml`, after the `models` block (line 199) add:

```python
    volumes: dict[str, Volume] = {}
    for name, cfg in data.get("volumes", {}).items():
        volumes[name] = Volume(name=name, **cfg)
```

Inside the agent loop (after the `models` pool resolution, before the subagents stash around line 242) add:

```python
        ws_data = agent_data.get("workspace")
        if isinstance(ws_data, dict) and isinstance(ws_data.get("volume"), str):
            vol_ref = ws_data["volume"]
            if vol_ref not in volumes:
                raise KeyError(
                    f"Unknown volume '{vol_ref}' in agent "
                    f"'{agent_data.get('name')}' workspace. "
                    f"Defined volumes: {', '.join(sorted(volumes))}"
                )
            ws_data = dict(ws_data)
            ws_data["volume"] = volumes[vol_ref]
            agent_data["workspace"] = ws_data
```

Update the call site (line 249): `_validate_workspace_platform_persistence(agent)` → `_validate_workspace_platform_volume(agent)`.

Search for other references to the old function/message: `grep -rn "_validate_workspace_platform_persistence\|persistence='bind' is not" packages/python/` — update any test asserting the old message text to the new `mode='bind'` message.

- [ ] **Step 4: Run the loader test suites**

Run: `uv run pytest packages/python/vystak/tests/ -v -k "multi_loader"`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak/src/vystak/schema/multi_loader.py \
        packages/python/vystak/tests/test_multi_loader_workspace.py
git commit -m "feat(loader): top-level volumes: section with named workspace references"
```

---

### Task 4: hash tree — volume affects deploy identity, retention doesn't

**Files:**
- Modify: `packages/python/vystak/src/vystak/hash/tree.py`
- Test: `packages/python/vystak/tests/hash/test_workspace_volume_hash.py` (create; if `tests/hash/` has no `__init__.py` convention, follow whatever the existing files in `packages/python/vystak/tests/hash/` do)

**Interfaces:**
- Consumes: `Workspace.volume` (Task 2), existing `hash_agent`, `hash_dict` from `vystak.hash.hasher`.
- Produces: `hash_agent(...).workspace` (and therefore `.root`) changes when `volume.mode`/`performance`/`name` change, but NOT when `volume.retention` changes. Internal helper `_hash_workspace_deploy(ws)` replaces `_hash_optional(agent.workspace)` at the `workspace =` assignment (line 222).

- [ ] **Step 1: Write the failing tests**

The `_agent` helper mirrors `packages/python/vystak/tests/hash/test_heartbeat_hash.py`'s `_model()`/`_platform()` construction — same required fields, same values.

```python
# packages/python/vystak/tests/hash/test_workspace_volume_hash.py
"""Volume fields join the workspace hash — except retention."""

from vystak.hash.tree import hash_agent
from vystak.schema import Agent, Model, Platform, Provider
from vystak.schema.volume import Volume
from vystak.schema.workspace import Workspace


def _agent(volume: Volume) -> Agent:
    return Agent(
        name="bot",
        framework="langchain-python",
        default_model=Model(
            name="claude",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-6",
        ),
        platform=Platform(
            name="local",
            type="docker",
            provider=Provider(name="docker", type="docker"),
            namespace="dev",
        ),
        workspace=Workspace(name="dev", image="python:3.12-slim", volume=volume),
    )


def test_volume_mode_changes_workspace_hash():
    a1 = _agent(Volume(name="team-code", mode="persistent"))
    a2 = _agent(Volume(name="team-code", mode="ephemeral"))
    assert hash_agent(a1).workspace != hash_agent(a2).workspace


def test_volume_performance_changes_workspace_hash():
    a1 = _agent(Volume(name="team-code", performance="standard"))
    a2 = _agent(Volume(name="team-code", performance="premium"))
    assert hash_agent(a1).workspace != hash_agent(a2).workspace


def test_volume_retention_does_not_change_hash():
    a1 = _agent(Volume(name="team-code", retention="retain"))
    a2 = _agent(Volume(name="team-code", retention="delete"))
    assert hash_agent(a1).root == hash_agent(a2).root
```

- [ ] **Step 2: Run tests to verify the retention test fails**

Run: `uv run pytest packages/python/vystak/tests/hash/test_workspace_volume_hash.py -v`
Expected: the two "changes hash" tests already PASS (whole-model hashing picks the fields up); `test_volume_retention_does_not_change_hash` FAILS — that failure is the point of this task.

- [ ] **Step 3: Implement**

In `tree.py`, ensure `hash_dict` is imported from `vystak.hash.hasher` (alongside the existing `hash_model` import). Add near the other `_hash_*` helpers (after `_hash_str`, line 89):

```python
def _hash_workspace_deploy(ws) -> str:
    """Hash the workspace minus fields that don't affect deploy identity.

    Volume.retention only governs destroy-time behavior.
    """
    if ws is None:
        return hashlib.sha256(b"null").hexdigest()
    data = ws.model_dump(mode="python")
    vol = data.get("volume")
    if isinstance(vol, dict):
        vol.pop("retention", None)
    return hash_dict(data)
```

Replace line 222 `workspace = _hash_optional(agent.workspace)` with:

```python
    workspace = _hash_workspace_deploy(agent.workspace)
```

- [ ] **Step 4: Run the hash suites**

Run: `uv run pytest packages/python/vystak/tests/hash/ packages/python/vystak/tests/test_hasher.py packages/python/vystak/tests/test_hash_tree_secrets.py -v`
Expected: all pass. (For agents without a workspace both old and new paths hash `b"null"` — no existing hash changes.)

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak/src/vystak/hash/tree.py \
        packages/python/vystak/tests/hash/test_workspace_volume_hash.py
git commit -m "feat(hash): volume config joins workspace hash, retention excluded"
```

---

### Task 5: Docker provider — mount by `effective_volume`, named-volume naming

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace.py`
- Test: `packages/python/vystak-provider-docker/tests/test_node_workspace_volume.py` (create; mirror the mock-client patterns of `tests/test_node_workspace.py`)

**Interfaces:**
- Consumes: `Workspace.effective_volume`, `ws.volume is not None` explicit-detection.
- Produces: `DockerWorkspaceNode.data_volume_name` → `vystak-volume-<name>` for explicit volumes, legacy `vystak-<agent>-workspace-data` for implicit. Container labels gain `"vystak.volume.name"` (the resource name, empty when not persistent) and `"vystak.volume.retention"`; the existing `"vystak.workspace.persistence"` label keeps its legacy vocabulary (`volume`/`bind`/`ephemeral`). Task 6's destroy path reads these labels.

- [ ] **Step 1: Write the failing tests**

Same mocking pattern as `tests/test_node_workspace.py` (real `docker.errors.NotFound`, MagicMock client, chdir into tmp_path):

```python
# packages/python/vystak-provider-docker/tests/test_node_workspace_volume.py
"""DockerWorkspaceNode volume mapping (Phase 1 named volumes)."""

from unittest.mock import MagicMock

from vystak.schema.volume import Volume
from vystak.schema.workspace import Workspace
from vystak_provider_docker.nodes.workspace import DockerWorkspaceNode


def _workspace(**kwargs):
    defaults = {"name": "dev", "image": "python:3.12-slim", "provision": []}
    defaults.update(kwargs)
    return Workspace(**defaults)


def _provisioned_node(tmp_path, monkeypatch, workspace):
    """Build a node with a fresh MagicMock client and run provision()."""
    monkeypatch.chdir(tmp_path)
    docker_client = MagicMock()
    import docker.errors

    docker_client.containers.get.side_effect = docker.errors.NotFound("nope")
    (tmp_path / "tools").mkdir(exist_ok=True)
    node = DockerWorkspaceNode(
        client=docker_client,
        agent_name="assistant",
        workspace=workspace,
        tools_dir=tmp_path / "tools",
    )
    context = {"network": MagicMock(info={"network": MagicMock(name="vystak-net")})}
    node.provision(context=context)
    return docker_client


def test_named_volume_resource_name():
    node = DockerWorkspaceNode(
        client=MagicMock(),
        agent_name="assistant",
        workspace=_workspace(volume=Volume(name="team-code")),
        tools_dir="tools",
    )
    assert node.data_volume_name == "vystak-volume-team-code"


def test_implicit_volume_keeps_legacy_name():
    node = DockerWorkspaceNode(
        client=MagicMock(),
        agent_name="assistant",
        workspace=_workspace(),
        tools_dir="tools",
    )
    assert node.data_volume_name == "vystak-assistant-workspace-data"


def test_provision_mounts_named_volume_and_labels(tmp_path, monkeypatch):
    client = _provisioned_node(
        tmp_path, monkeypatch,
        _workspace(volume=Volume(name="team-code", retention="delete")),
    )
    run_kwargs = client.containers.run.call_args.kwargs
    assert run_kwargs["volumes"]["vystak-volume-team-code"] == {
        "bind": "/workspace", "mode": "rw",
    }
    assert run_kwargs["labels"]["vystak.volume.name"] == "vystak-volume-team-code"
    assert run_kwargs["labels"]["vystak.volume.retention"] == "delete"
    assert run_kwargs["labels"]["vystak.workspace.persistence"] == "volume"


def test_provision_ephemeral_volume_uses_tmpfs(tmp_path, monkeypatch):
    client = _provisioned_node(
        tmp_path, monkeypatch,
        _workspace(volume=Volume(name="scratch", mode="ephemeral")),
    )
    run_kwargs = client.containers.run.call_args.kwargs
    assert run_kwargs["tmpfs"] == {"/workspace": "rw,size=512m"}
    assert run_kwargs["labels"]["vystak.volume.name"] == ""
```

Note: `docker.errors.NotFound` on the volume lookup — for the named-volume provision test, the default MagicMock `volumes.get` succeeds (volume "exists"), which is fine; the mount assertion is what matters.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_workspace_volume.py -v`
Expected: FAIL — `data_volume_name` returns legacy name for named volume; labels missing.

- [ ] **Step 3: Implement**

In `nodes/workspace.py`:

Replace the `data_volume_name` property (lines 35–37):

```python
    @property
    def data_volume_name(self) -> str:
        if self._workspace.volume is not None:
            return f"vystak-volume-{self._workspace.effective_volume.name}"
        return f"vystak-{self._agent_name}-workspace-data"
```

In `provision()`, replace the persistence block (lines 167–179):

```python
        vol = ws.effective_volume
        tmpfs: dict = {}
        if vol.mode == "persistent":
            # Ensure data volume exists
            try:
                self._client.volumes.get(self.data_volume_name)
            except docker.errors.NotFound:
                self._client.volumes.create(name=self.data_volume_name)
            volumes[self.data_volume_name] = {"bind": "/workspace", "mode": "rw"}
        elif vol.mode == "bind":
            host_path = str(Path(vol.path).expanduser().resolve())
            volumes[host_path] = {"bind": "/workspace", "mode": "rw"}
        elif vol.mode == "ephemeral":
            tmpfs["/workspace"] = "rw,size=512m"
```

Replace the labels dict (lines 195–198) — keep the legacy vocabulary in the old label, add the two new ones:

```python
            labels={
                "vystak.workspace": self._agent_name,
                "vystak.workspace.persistence": {
                    "persistent": "volume"
                }.get(vol.mode, vol.mode),
                "vystak.volume.name": (
                    self.data_volume_name if vol.mode == "persistent" else ""
                ),
                "vystak.volume.retention": vol.retention,
            },
```

Update the `info` dict (lines 208–210):

```python
            "data_volume_name": (
                self.data_volume_name if vol.mode == "persistent" else None
            ),
```

- [ ] **Step 4: Run the Docker workspace test files**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/ -v -k "workspace"`
Expected: all pass (old `test_node_workspace.py` behavior unchanged — legacy configs produce identical mounts/names).

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace.py \
        packages/python/vystak-provider-docker/tests/test_node_workspace_volume.py
git commit -m "feat(docker): workspace mounts driven by effective_volume, named-volume resources"
```

---

### Task 6: Docker destroy — retention + shared-volume protection

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py` (`_destroy_workspace_resources`, lines 902–926)
- Modify + Test: `packages/python/vystak-provider-docker/tests/test_provider.py` (extend the `mock_docker_client` fixture, append a test class)

**Interfaces:**
- Consumes: labels written in Task 5 (`vystak.volume.name`, `vystak.volume.retention`).
- Produces: destroy deletes the data volume when `delete_workspace_data=True` OR the label says `retention == "delete"`; a volume still attached to another container (docker `APIError` on remove) is skipped with an informational message, never an error.

- [ ] **Step 1: Write the failing tests**

`tests/test_provider.py` already patches `vystak_provider_docker.provider.docker` and fabricates `NotFound`/`DockerException` error types in its `mock_docker_client` fixture (lines 12–19). First extend that fixture with one line next to the other two fabricated errors:

```python
        mock_docker.errors.APIError = type("APIError", (Exception,), {})
```

Then append to the file:

```python
class TestDestroyWorkspaceVolume:
    def _ws_container(self, client, not_found_error, labels):
        ws_container = MagicMock()
        ws_container.labels = labels

        def _get(name):
            if name == "vystak-assistant-workspace":
                return ws_container
            raise not_found_error("not found")

        client.containers.get.side_effect = _get
        return ws_container

    def test_retention_delete_label_removes_volume_without_flag(
        self, provider, mock_docker_client, not_found_error
    ):
        client, _ = mock_docker_client
        self._ws_container(client, not_found_error, {
            "vystak.volume.name": "vystak-volume-team-code",
            "vystak.volume.retention": "delete",
        })
        provider._destroy_workspace_resources(
            agent_name="assistant", delete_workspace_data=False
        )
        client.volumes.get.assert_called_once_with("vystak-volume-team-code")
        client.volumes.get.return_value.remove.assert_called_once()

    def test_default_retains_volume(
        self, provider, mock_docker_client, not_found_error
    ):
        client, _ = mock_docker_client
        self._ws_container(client, not_found_error, {
            "vystak.volume.name": "vystak-volume-team-code",
            "vystak.volume.retention": "retain",
        })
        provider._destroy_workspace_resources(
            agent_name="assistant", delete_workspace_data=False
        )
        client.volumes.get.return_value.remove.assert_not_called()

    def test_volume_still_in_use_is_skipped(
        self, provider, mock_docker_client, not_found_error, capsys
    ):
        client, errors = mock_docker_client
        self._ws_container(client, not_found_error, {
            "vystak.volume.name": "vystak-volume-team-code",
            "vystak.volume.retention": "retain",
        })
        client.volumes.get.return_value.remove.side_effect = errors.APIError(
            "volume is in use"
        )
        # must not raise
        provider._destroy_workspace_resources(
            agent_name="assistant", delete_workspace_data=True
        )
        assert "still in use" in capsys.readouterr().out

    def test_legacy_container_without_volume_labels(
        self, provider, mock_docker_client, not_found_error
    ):
        """Pre-Phase-1 containers have no vystak.volume.* labels."""
        client, _ = mock_docker_client
        self._ws_container(client, not_found_error, {"vystak.workspace": "assistant"})
        provider._destroy_workspace_resources(
            agent_name="assistant", delete_workspace_data=True
        )
        client.volumes.get.assert_called_once_with(
            "vystak-assistant-workspace-data"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/ -v -k "destroy and volume or retention"`
Expected: FAIL — current code always targets the legacy name and never reads labels.

- [ ] **Step 3: Implement**

Replace `_destroy_workspace_resources` (provider.py lines 902–926):

```python
    def _destroy_workspace_resources(
        self, *, agent_name: str, delete_workspace_data: bool
    ) -> None:
        """Stop and remove the per-agent workspace container.

        The data volume is deleted when ``delete_workspace_data=True`` or
        the container's ``vystak.volume.retention`` label is ``delete``.
        A volume still mounted by another agent's workspace is skipped —
        a named volume is only removable once its last referent is gone.
        """
        volume_name = f"vystak-{agent_name}-workspace-data"
        retention = "retain"
        try:
            ws = self._client.containers.get(f"vystak-{agent_name}-workspace")
            labels = ws.labels or {}
            volume_name = labels.get("vystak.volume.name") or volume_name
            retention = labels.get("vystak.volume.retention", "retain")
            ws.stop()
            ws.remove()
        except docker.errors.NotFound:
            pass

        if delete_workspace_data or retention == "delete":
            try:
                vol = self._client.volumes.get(volume_name)
                vol.remove()
            except docker.errors.NotFound:
                pass
            except docker.errors.APIError:
                print(
                    f"Volume '{volume_name}' is still in use by another "
                    f"agent's workspace; skipping delete."
                )
```

- [ ] **Step 4: Run the provider test suite**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/ -v`
Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py \
        packages/python/vystak-provider-docker/tests/
git commit -m "feat(docker): destroy honors volume retention and shared-volume protection"
```

---

### Task 7: Azure provider — named shares (SMB) + friendly storage-account error

**Files:**
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/provider.py` (`_add_workspace_nodes`, lines 456–563)
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/files_share.py`
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_workspace_app.py` (lines 205–227)
- Test: `packages/python/vystak-provider-azure/tests/test_files_share.py` (append), `packages/python/vystak-provider-azure/tests/test_provider_workspace_graph.py` (append)

**Interfaces:**
- Consumes: `effective_volume`; `ws.volume is not None` detection.
- Produces: share name `vystak-volume-<name>` for explicit volumes (legacy `vystak-<agent>-workspace-data` for implicit); `AzureFilesShareNode(..., enabled_protocols="SMB")` new keyword (default `"SMB"`, Task 8 passes `"NFS"`); missing storage account now raises `ValueError` with an actionable message before any create call; `aca_workspace_app` derives its `persistence_mode` from `effective_volume` instead of `ws.persistence`.

- [ ] **Step 1: Write the failing tests**

Append to `test_files_share.py` (that file constructs `MagicMock()` storage clients inline — no fixtures; add `import pytest` to its imports):

```python
def test_missing_storage_account_raises_actionable_error():
    storage_client = MagicMock()
    storage_client.storage_accounts.get_properties.side_effect = (
        ResourceNotFoundError("no account")
    )
    node = AzureFilesShareNode(
        client=storage_client,
        rg_name="rg",
        storage_account="missing",
        share_name="vystak-volume-team-code",
    )
    with pytest.raises(ValueError, match="Storage account 'missing' not found"):
        node.provision({})


def test_share_created_with_smb_by_default():
    storage_client = MagicMock()
    storage_client.file_shares.get.side_effect = ResourceNotFoundError("x")
    node = AzureFilesShareNode(
        client=storage_client,
        rg_name="rg",
        storage_account="acct",
        share_name="vystak-volume-team-code",
    )
    node.provision({})
    body = storage_client.file_shares.create.call_args.args[3]
    assert body == {}


def test_nfs_share_created_with_protocol():
    storage_client = MagicMock()
    storage_client.file_shares.get.side_effect = ResourceNotFoundError("x")
    node = AzureFilesShareNode(
        client=storage_client,
        rg_name="rg",
        storage_account="acct",
        share_name="vystak-volume-fast",
        enabled_protocols="NFS",
    )
    node.provision({})
    body = storage_client.file_shares.create.call_args.args[3]
    assert body == {"enabled_protocols": "NFS"}
```

(The existing tests in that file keep passing: a default `MagicMock` returns successfully from the new `storage_accounts.get_properties` precheck.)

Append to `test_provider_workspace_graph.py`. That file's `_agent_with_workspace(persistence)` helper builds a full Agent with a `container-apps` platform (config includes `storage_account="mystorage"`) and calls `provider._add_workspace_nodes(graph=MagicMock(), ...)` with mocked clients; nodes are real objects added to the mock graph, so assert via each node's `.name` property (`files-share-<share_name>`). Add a volume-flavored helper + tests:

```python
def _agent_with_volume(volume):
    """Like _agent_with_workspace but referencing a named Volume."""
    from vystak.schema import Agent, Model, Platform, Provider, Workspace

    return Agent(
        name="assistant",
        framework="langchain-python",
        default_model=Model(
            name="claude",
            model_name="claude-3",
            provider=Provider(name="anthropic", type="anthropic"),
        ),
        platform=Platform(
            name="aca",
            type="container-apps",
            provider=Provider(name="azure", type="azure"),
            config={
                "subscription_id": "sub-test",
                "resource_group": "rg-test",
                "location": "eastus",
                "storage_account": "mystorage",
            },
        ),
        workspace=Workspace(name="dev", volume=volume),
    )


def _run_add_workspace_nodes(provider, graph, **client_overrides):
    clients = {
        "aca_client": MagicMock(),
        "docker_client": MagicMock(),
        "secret_client": MagicMock(),
        "storage_client": MagicMock(),
    }
    clients.update(client_overrides)
    return provider._add_workspace_nodes(
        graph=graph,
        agent=provider._agent,
        rg_name="rg-test",
        env_name="env-test",
        acr_name="acrtest",
        vault_node_name="vault-test",
        workspace_identity_key="ws-id",
        location="eastus",
        cfg=provider._agent.platform.config,
        **clients,
    )


def _added_node_names(graph):
    return [call.args[0].name for call in graph.add.call_args_list]


def test_named_volume_share_name():
    from vystak.schema.volume import Volume

    provider = _make_provider_for(_agent_with_volume(Volume(name="team-code")))
    graph = MagicMock()
    _run_add_workspace_nodes(provider, graph)
    assert "files-share-vystak-volume-team-code" in _added_node_names(graph)


def test_implicit_volume_keeps_legacy_share_name():
    provider = _make_provider_for(_agent_with_workspace("volume"))
    graph = MagicMock()
    _run_add_workspace_nodes(provider, graph)
    assert "files-share-vystak-assistant-workspace-data" in _added_node_names(graph)
```

(If the file's existing tests already build the client-kwargs dict inline, factor `_run_add_workspace_nodes` at the top and optionally reuse it — don't churn existing tests otherwise.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_files_share.py packages/python/vystak-provider-azure/tests/test_provider_workspace_graph.py -v`
Expected: new tests FAIL (no `get_properties` precheck; legacy-only share naming).

- [ ] **Step 3: Implement**

`files_share.py` — new keyword + precheck (replace the class body's `__init__` and `provision`):

```python
    def __init__(
        self,
        *,
        client,
        rg_name: str,
        storage_account: str,
        share_name: str,
        enabled_protocols: str = "SMB",
    ) -> None:
        self._client = client
        self._rg_name = rg_name
        self._storage_account = storage_account
        self._share_name = share_name
        self._enabled_protocols = enabled_protocols
```

At the top of `provision`, before the existing `file_shares.get` try:

```python
        try:
            self._client.storage_accounts.get_properties(
                self._rg_name, self._storage_account
            )
        except ResourceNotFoundError:
            raise ValueError(
                f"Storage account '{self._storage_account}' not found in "
                f"resource group '{self._rg_name}'. Workspace volumes on "
                f"Azure require an existing storage account named in "
                f"platform.config.storage_account. Create it first:\n"
                f"  az storage account create -n {self._storage_account} "
                f"-g {self._rg_name} --sku Standard_LRS"
            ) from None
```

And in the create branch, build the body from the protocol:

```python
            body = (
                {"enabled_protocols": "NFS"}
                if self._enabled_protocols == "NFS"
                else {}
            )
            self._client.file_shares.create(
                self._rg_name,
                self._storage_account,
                self._share_name,
                body,
            )
```

Update the class docstring — the "not a friendly message, but fail-fast" caveat is now false; replace that paragraph with a sentence saying the account is pre-checked with an actionable error.

`provider.py` `_add_workspace_nodes` — replace the persistence-derived pieces:

```python
        ws = agent.workspace
        vol = ws.effective_volume
```

- Replace both `if ws.persistence == "volume":` checks (lines ~496 and ~519) with `if vol.mode == "persistent":`.
- Replace `share_name = f"vystak-{agent.name}-workspace-data"` with:

```python
            if ws.volume is not None:
                share_name = f"vystak-volume-{vol.name}"
            else:
                share_name = f"vystak-{agent.name}-workspace-data"
```

- Keep `storage_logical_name = f"vystak-{agent.name}-workspace"` as-is for the implicit case, but for named volumes make the env-storage entry shareable across agents: `storage_logical_name = f"vystak-volume-{vol.name}" if ws.volume is not None else f"vystak-{agent.name}-workspace"`. (`ACAEnvStorageNode` is already idempotent via its `get` check, so two agents registering the same storage name is safe.)
- Pass `enabled_protocols="SMB"` explicitly to `AzureFilesShareNode` (Task 8 switches it on performance).

`aca_workspace_app.py` lines 205–227 — replace the three `self._agent.workspace.persistence` reads with the normalized form:

```python
        vol = self._agent.workspace.effective_volume
        mode = "volume" if vol.mode == "persistent" else "ephemeral"
```

then use `mode` where `self._agent.workspace.persistence` was compared/passed (`storage_name` guard, `share_subpath = "/workspace" if mode == "volume" else None`, `persistence_mode=mode`).

- [ ] **Step 4: Run the Azure provider suite**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/ -v`
Expected: all pass (existing tests may need their mock storage clients to return successfully from `storage_accounts.get_properties` — configure the mocks rather than weakening the precheck).

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-provider-azure/
git commit -m "feat(azure): named volume shares, friendly storage-account error"
```

---

### Task 8: Azure premium tier — NFS shares + preconditions

**Files:**
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/provider.py` (`_add_workspace_nodes`)
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_env_storage.py`
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_workspace_app.py`
- Test: `packages/python/vystak-provider-azure/tests/test_provider_workspace_graph.py`, `packages/python/vystak-provider-azure/tests/test_aca_workspace_app.py` (append)

**Interfaces:**
- Consumes: `Volume.performance`, Task 7's `enabled_protocols` keyword.
- Produces: `performance: premium` → `AzureFilesShareNode(enabled_protocols="NFS")`, `ACAEnvStorageNode(protocol="NFS")` (new keyword, default `"SMB"`), workspace app volume `storageType: "NfsAzureFile"` (new `nfs: bool = False` parameter on `build_workspace_revision`). Plan-time `ValueError`s when the storage account kind isn't `FileStorage` or the ACA environment isn't VNet-injected.

- [ ] **Step 1: Write the failing tests**

Append to `test_provider_workspace_graph.py` (uses Task 7's `_agent_with_volume` / `_run_add_workspace_nodes` / `_added_node_names` helpers):

```python
def _premium_clients(kind="FileStorage", subnet="subnet-id"):
    storage_client = MagicMock()
    storage_client.storage_accounts.get_properties.return_value = MagicMock(
        kind=kind
    )
    aca_client = MagicMock()
    aca_client.managed_environments.get.return_value = MagicMock(
        vnet_configuration=(
            MagicMock(infrastructure_subnet_id=subnet) if subnet else None
        )
    )
    return storage_client, aca_client


def test_premium_volume_requires_filestorage_account():
    from vystak.schema.volume import Volume

    provider = _make_provider_for(
        _agent_with_volume(Volume(name="fast", performance="premium"))
    )
    storage_client, aca_client = _premium_clients(kind="StorageV2")
    with pytest.raises(ValueError, match="kind='FileStorage'"):
        _run_add_workspace_nodes(
            provider, MagicMock(),
            storage_client=storage_client, aca_client=aca_client,
        )


def test_premium_volume_requires_vnet_injected_environment():
    from vystak.schema.volume import Volume

    provider = _make_provider_for(
        _agent_with_volume(Volume(name="fast", performance="premium"))
    )
    storage_client, aca_client = _premium_clients(subnet=None)
    with pytest.raises(ValueError, match="VNet"):
        _run_add_workspace_nodes(
            provider, MagicMock(),
            storage_client=storage_client, aca_client=aca_client,
        )


def test_premium_volume_wires_nfs_protocol():
    from vystak.schema.volume import Volume
    from vystak_provider_azure.nodes.aca_env_storage import ACAEnvStorageNode
    from vystak_provider_azure.nodes.files_share import AzureFilesShareNode

    provider = _make_provider_for(
        _agent_with_volume(Volume(name="fast", performance="premium"))
    )
    storage_client, aca_client = _premium_clients()
    graph = MagicMock()
    _run_add_workspace_nodes(
        provider, graph,
        storage_client=storage_client, aca_client=aca_client,
    )
    added = [call.args[0] for call in graph.add.call_args_list]
    share = next(n for n in added if isinstance(n, AzureFilesShareNode))
    env_storage = next(n for n in added if isinstance(n, ACAEnvStorageNode))
    assert share._enabled_protocols == "NFS"
    assert env_storage._protocol == "NFS"
```

Append to `test_aca_workspace_app.py` — full argument list copied from that file's `test_build_workspace_revision_mounts_volume_at_workspace`:

```python
def test_nfs_volume_uses_nfs_storage_type():
    body = build_workspace_revision(
        agent_name="assistant",
        location="eastus",
        workspace_image="acr/img:tag",
        workspace_identity_resource_id="x",
        vault_uri="https://kv.vault.azure.net/",
        ssh_kv_secrets=[],
        user_secrets=[],
        acr_login_server="acr.azurecr.io",
        acr_password_secret_ref="acr-pwd",
        acr_password_value="REDACTED",
        storage_name="vystak-volume-team-code",
        share_subpath="/workspace",
        persistence_mode="volume",
        nfs=True,
    )
    vol = body["properties"]["template"]["volumes"][0]
    assert vol["storageType"] == "NfsAzureFile"
    assert vol["storageName"] == "vystak-volume-team-code"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/ -v -k "nfs or premium"`
Expected: FAIL — `nfs`/`protocol` keywords don't exist yet.

- [ ] **Step 3: Implement**

`provider.py` `_add_workspace_nodes`, inside the `vol.mode == "persistent"` block after `storage_account` is validated:

```python
            nfs = vol.performance == "premium"
            if nfs:
                props = storage_client.storage_accounts.get_properties(
                    rg_name, storage_account
                )
                if getattr(props, "kind", None) != "FileStorage":
                    raise ValueError(
                        f"Agent '{agent.name}': volume '{vol.name}' has "
                        f"performance='premium', which uses Azure Files NFS "
                        f"and requires a premium storage account with "
                        f"kind='FileStorage'. Account '{storage_account}' "
                        f"has kind='{getattr(props, 'kind', None)}'. Create "
                        f"one with:\n  az storage account create -n <name> "
                        f"-g {rg_name} --kind FileStorage --sku Premium_LRS"
                    )
                env = aca_client.managed_environments.get(rg_name, env_name)
                vnet = getattr(env, "vnet_configuration", None)
                if vnet is None or not getattr(
                    vnet, "infrastructure_subnet_id", None
                ):
                    raise ValueError(
                        f"Agent '{agent.name}': volume '{vol.name}' with "
                        f"performance='premium' mounts over NFS, which "
                        f"requires a VNet-injected Container Apps "
                        f"environment. Environment '{env_name}' has no "
                        f"vnetConfiguration. Recreate it with "
                        f"--infrastructure-subnet-resource-id, or use "
                        f"performance='standard' (SMB)."
                    )
```

then pass the protocol through: `AzureFilesShareNode(..., enabled_protocols="NFS" if nfs else "SMB")` and `ACAEnvStorageNode(..., protocol="NFS" if nfs else "SMB")`, and hand `nfs` into `ACAWorkspaceAppNode` (add an `nfs: bool = False` constructor arg it forwards to `build_workspace_revision`).

`aca_env_storage.py` — add `protocol: str = "SMB"` to `__init__` (store as `self._protocol`), and in the create branch choose the envelope:

```python
            if self._protocol == "NFS":
                envelope = {
                    "properties": {
                        "nfsAzureFile": {
                            "server": (
                                f"{self._storage_account}.file.core.windows.net"
                            ),
                            "shareName": (
                                f"/{self._storage_account}/{self._share_name}"
                            ),
                            "accessMode": "ReadWrite",
                        }
                    }
                }
            else:
                keys = self._storage.storage_accounts.list_keys(
                    self._rg_name, self._storage_account
                )
                account_key = keys.keys[0].value
                envelope = {
                    "properties": {
                        "azureFile": {
                            "accountName": self._storage_account,
                            "accountKey": account_key,
                            "shareName": self._share_name,
                            "accessMode": "ReadWrite",
                        }
                    }
                }
```

(NFS mounts don't use account keys — access is network-scoped via the VNet.)

`aca_workspace_app.py` — add `nfs: bool = False` to `build_workspace_revision`'s signature and switch the volume block:

```python
        template["volumes"] = [
            {
                "name": "workspace-data",
                "storageType": "NfsAzureFile" if nfs else "AzureFile",
                "storageName": storage_name,
            }
        ]
```

and thread `nfs=self._nfs` from `ACAWorkspaceAppNode.provision`'s call site (lines 205–227 region touched in Task 7).

- [ ] **Step 4: Run the Azure suite**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/ -v`
Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-provider-azure/
git commit -m "feat(azure): NFS premium volumes with plan-time precondition checks"
```

---

### Task 9: Examples + spec status

**Files:**
- Create: `examples/docker-shared-volume/vystak.yaml`, `examples/docker-shared-volume/README.md`
- Create: `examples/azure-workspace-premium/vystak.yaml`, `examples/azure-workspace-premium/README.md`
- Modify: `docs/superpowers/specs/2026-07-23-workspace-volume-design.md` (status line)

**Interfaces:**
- Consumes: everything above; these files are user-deployable exercises of the new surface (repo rule: examples are part of definition-of-done).

- [ ] **Step 1: Write the Docker shared-volume example**

Look at `examples/docker-workspace-compute/vystak.yaml` first and keep its structure/models; the content below is the shape to produce (adjust model/provider names to match what that example actually uses):

```yaml
# examples/docker-shared-volume/vystak.yaml
# Two agents sharing one named workspace volume.
providers:
  docker:
    type: docker
  anthropic:
    type: anthropic

platforms:
  local:
    type: docker
    provider: docker

models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-5

volumes:
  team-code:
    mode: persistent
    retention: retain

agents:
  - name: coder
    framework: langchain-python
    default_model: sonnet
    platform: local
    workspace:
      name: coder-ws
      image: python:3.12-slim
      volume: team-code

  - name: reviewer
    framework: langchain-python
    default_model: sonnet
    platform: local
    workspace:
      name: reviewer-ws
      image: python:3.12-slim
      volume: team-code
```

README.md: what it shows (one named volume `team-code` mounted at `/workspace` in both agents' workspaces, data survives `vystak destroy`, `--delete-workspace-data` removal only succeeds after both agents are destroyed), plus the standard run steps copied from the neighboring workspace example's README.

- [ ] **Step 2: Write the Azure premium example**

Base it on `examples/azure-workspace-vault/` (copy its provider/platform/vault blocks verbatim with placeholder values like `YOUR_SUBSCRIPTION_ID`), then:

```yaml
volumes:
  fast-scratch:
    mode: persistent
    performance: premium   # Azure Files NFS — requires FileStorage account + VNet-injected ACA env
```

with the agent's workspace referencing `volume: fast-scratch`. README must state the two prerequisites verbatim from the error messages: a `--kind FileStorage --sku Premium_LRS` storage account and a VNet-injected ACA environment.

- [ ] **Step 3: Validate the Docker example loads**

Run: `uv run python -c "import yaml; from vystak.schema.multi_loader import load_multi_yaml; agents,_,_ = load_multi_yaml(yaml.safe_load(open('examples/docker-shared-volume/vystak.yaml'))); print([a.workspace.effective_volume.name for a in agents])"`
Expected: `['team-code', 'team-code']`

Run the same one-liner against `examples/azure-workspace-premium/vystak.yaml`; expected: `['fast-scratch']`.

Also check whether `packages/python/vystak/tests/test_examples.py` sweeps `examples/` — if it does, run it: `uv run pytest packages/python/vystak/tests/test_examples.py -v`.

- [ ] **Step 4: Update spec status and run the full Python gate**

In the spec header change `**Status:** Approved design, pending implementation plan` → `**Status:** Phase 1 implemented (this plan); Phase 2 pending`.

Run: `just test-python && just lint-python`
Expected: both green.

- [ ] **Step 5: Commit**

```bash
git add examples/docker-shared-volume/ examples/azure-workspace-premium/ \
        docs/superpowers/specs/2026-07-23-workspace-volume-design.md
git commit -m "feat(examples): shared-volume and Azure premium workspace examples"
```

---

## Deviations from the spec (recorded, agreed)

- **Azure share deletion on destroy** stays out of Phase 1: the Azure provider's `destroy()` is RG-scoped and currently never touches Files shares (they live in the user's storage account). Named shared volumes on Azure are never auto-deleted; removal is a manual `az storage share delete`. Docker gets full retention semantics (Task 6). Revisit in Phase 2 alongside snapshots.
- **`volumes:` is a mapping**, not a list — matches `providers`/`platforms`/`models` (spec updated).

## Self-review notes

- Spec coverage: schema (T1–T2), loader + validation (T3), hash (T4), Docker mapping + retention/sharing (T5–T6), Azure SMB naming + friendly errors (T7), NFS premium + preconditions (T8), examples (T9). Release-matrix V12 extension cells are deferred to Phase 2 with the snapshot lifecycle (they need deploy→destroy→re-apply plumbing that phase adds anyway) — noted here so it isn't silently dropped.
- Back-compat: legacy `persistence:` untouched at every layer; implicit volumes keep legacy resource names; agents without workspaces produce byte-identical hashes.
