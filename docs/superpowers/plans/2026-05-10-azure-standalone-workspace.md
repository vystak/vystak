# Azure Standalone Workspace — Sidecar to Two-App Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Azure Container Apps workspace sidecar (TCP RPC on `localhost:50051`) with a standalone two-app pattern (SSH-RPC on internal port 22), unifying transport with the Docker provider.

**Architecture:** Per spec at commit `e64251e` (`docs/superpowers/specs/2026-04-23-aca-workspace-compute-design.md`). Two ACA apps per agent+workspace pair: agent app (existing, external 443) and workspace app (new, internal TCP 22), both in the same ACA Environment for internal DNS. Azure Files mount at `/workspace` for `persistence: volume`. SSH key material stored in Azure Key Vault, delivered to containers via `secretRef`, materialized to disk by an extended entrypoint shim.

**Tech Stack:** Python 3.11, Pydantic v2 schema, Azure SDK (`azure-mgmt-containerapps`, `azure-mgmt-storage`), Docker SDK (alpine throwaway for keygen + image build), pytest, ruff, pyright.

**Branch:** Work on `feat/aca-workspace-compute` (already contains the spec at `e64251e` and the schema validator at `8020650`). Rebase on `main` before starting Task 1.

**Migration order:** Build new path alongside sidecar (no breakage), wire in, migrate example end-to-end, then remove sidecar. This keeps the branch deployable at every commit.

---

## Phase 1 — Schema validator on main

### Task 1: Confirm `_validate_workspace_platform_persistence` is on the working branch

**Files:**
- Verify: `packages/python/vystak/src/vystak/schema/multi_loader.py`
- Verify: `packages/python/vystak/tests/test_multi_loader_workspace.py`

- [ ] **Step 1: Rebase `feat/aca-workspace-compute` on `main`**

```bash
git checkout feat/aca-workspace-compute
git fetch origin
git rebase origin/main
```

Expected: clean rebase. If conflicts in `multi_loader.py`, take the branch version (it has the validator).

- [ ] **Step 2: Verify validator code is present**

Run: `grep -n "_validate_workspace_platform_persistence" packages/python/vystak/src/vystak/schema/multi_loader.py`
Expected: two hits — function definition (~line 28) and call site (~line 122).

- [ ] **Step 3: Run validator tests**

Run: `uv run pytest packages/python/vystak/tests/test_multi_loader_workspace.py -v -k persistence`
Expected: 4 tests PASS (covers ACA+bind reject, ACA+volume accept, ACA+ephemeral accept, Docker+bind accept).

- [ ] **Step 4: No commit needed** — validator is already committed on the branch.

---

## Phase 2 — New Azure provisioning nodes (TDD)

All four new nodes live in `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/`.

### Task 2: `AzureWorkspaceSshKeygenNode` — generate keys, push to Key Vault

Reuses `_keygen_via_docker()` logic from Docker side; pushes 4 secrets to Azure Key Vault.

**Files:**
- Create: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/workspace_ssh_keygen.py`
- Create: `packages/python/vystak-provider-azure/tests/test_workspace_ssh_keygen.py`

- [ ] **Step 1: Write the failing test**

```python
# packages/python/vystak-provider-azure/tests/test_workspace_ssh_keygen.py
from unittest.mock import MagicMock, patch

import pytest

from vystak_provider_azure.nodes.workspace_ssh_keygen import (
    AzureWorkspaceSshKeygenNode,
    _kv_secret_name,
)


def test_kv_secret_names_match_spec():
    """Spec mandates these exact KV secret names (dashes, not slashes)."""
    assert _kv_secret_name("assistant", "client-key") == (
        "vystak-workspace-ssh-assistant-client-key"
    )
    assert _kv_secret_name("assistant", "host-key") == (
        "vystak-workspace-ssh-assistant-host-key"
    )
    assert _kv_secret_name("assistant", "client-key-pub") == (
        "vystak-workspace-ssh-assistant-client-key-pub"
    )
    assert _kv_secret_name("assistant", "host-key-pub") == (
        "vystak-workspace-ssh-assistant-host-key-pub"
    )


def test_provision_pushes_four_secrets_to_keyvault():
    """First provision generates keys and uploads all 4 to KV."""
    secret_client = MagicMock()
    secret_client.get_secret.side_effect = Exception("ResourceNotFound")
    docker_client = MagicMock()

    node = AzureWorkspaceSshKeygenNode(
        agent_name="assistant",
        secret_client=secret_client,
        docker_client=docker_client,
    )

    with patch.object(
        node,
        "_keygen_via_docker",
        return_value=("CLIENT_PRIV", "CLIENT_PUB", "HOST_PRIV", "HOST_PUB"),
    ):
        result = node.provision({})

    assert result.success is True
    assert result.info["regenerated"] is True
    assert secret_client.set_secret.call_count == 4
    set_calls = {
        c.args[0]: c.args[1] for c in secret_client.set_secret.call_args_list
    }
    assert set_calls["vystak-workspace-ssh-assistant-client-key"] == "CLIENT_PRIV"
    assert set_calls["vystak-workspace-ssh-assistant-client-key-pub"] == "CLIENT_PUB"
    assert set_calls["vystak-workspace-ssh-assistant-host-key"] == "HOST_PRIV"
    assert set_calls["vystak-workspace-ssh-assistant-host-key-pub"] == "HOST_PUB"


def test_provision_idempotent_when_all_four_keys_exist():
    """Second provision is a no-op when all 4 secrets already in KV."""
    secret_client = MagicMock()
    secret_client.get_secret.return_value = MagicMock(value="exists")
    docker_client = MagicMock()

    node = AzureWorkspaceSshKeygenNode(
        agent_name="assistant",
        secret_client=secret_client,
        docker_client=docker_client,
    )

    with patch.object(node, "_keygen_via_docker") as mock_keygen:
        result = node.provision({})

    assert result.success is True
    assert result.info["regenerated"] is False
    mock_keygen.assert_not_called()
    secret_client.set_secret.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_workspace_ssh_keygen.py -v`
Expected: FAIL with `ModuleNotFoundError: vystak_provider_azure.nodes.workspace_ssh_keygen`.

- [ ] **Step 3: Implement the node**

```python
# packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/workspace_ssh_keygen.py
"""Generate workspace SSH keypairs and stash them in Azure Key Vault.

Mirrors vystak_provider_docker.nodes.workspace_ssh_keygen on the Vault path,
but pushes to Azure Key Vault instead of HashiCorp Vault. The four secrets
are referenced by the agent and workspace ACA apps via secretRef.
"""

from __future__ import annotations

import pathlib
import tempfile

from vystak.provisioning import Provisionable, ProvisionResult


_KEY_KINDS = ("client-key", "client-key-pub", "host-key", "host-key-pub")


def _kv_secret_name(agent_name: str, kind: str) -> str:
    return f"vystak-workspace-ssh-{agent_name}-{kind}"


class AzureWorkspaceSshKeygenNode(Provisionable):
    """Generate SSH keypairs once per agent; push to Key Vault.

    Idempotent — if all four secrets already exist, no keygen runs.
    """

    def __init__(
        self,
        *,
        agent_name: str,
        secret_client,
        docker_client,
    ) -> None:
        self._agent_name = agent_name
        self._secret_client = secret_client
        self._docker = docker_client

    @property
    def name(self) -> str:
        return f"workspace-ssh-keygen-{self._agent_name}"

    def provision(self, context: dict) -> ProvisionResult:
        if self._all_keys_exist():
            return ProvisionResult(
                name=self.name, success=True, info={"regenerated": False}
            )

        with tempfile.TemporaryDirectory() as td:
            client_priv, client_pub, host_priv, host_pub = self._keygen_via_docker(td)

        values = {
            "client-key": client_priv,
            "client-key-pub": client_pub,
            "host-key": host_priv,
            "host-key-pub": host_pub,
        }
        for kind, value in values.items():
            self._secret_client.set_secret(
                _kv_secret_name(self._agent_name, kind), value
            )

        return ProvisionResult(
            name=self.name, success=True, info={"regenerated": True}
        )

    def _all_keys_exist(self) -> bool:
        for kind in _KEY_KINDS:
            try:
                self._secret_client.get_secret(_kv_secret_name(self._agent_name, kind))
            except Exception:
                return False
        return True

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_workspace_ssh_keygen.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/workspace_ssh_keygen.py \
        packages/python/vystak-provider-azure/tests/test_workspace_ssh_keygen.py
git commit -m "feat(provider-azure): AzureWorkspaceSshKeygenNode — keygen + KV upload"
```

---

### Task 3: `AzureFilesShareNode` — idempotent share create/lookup

**Files:**
- Create: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/files_share.py`
- Create: `packages/python/vystak-provider-azure/tests/test_files_share.py`

- [ ] **Step 1: Write the failing test**

```python
# packages/python/vystak-provider-azure/tests/test_files_share.py
from unittest.mock import MagicMock

from azure.core.exceptions import ResourceNotFoundError

from vystak_provider_azure.nodes.files_share import AzureFilesShareNode


def test_provision_creates_share_when_missing():
    storage_client = MagicMock()
    storage_client.file_shares.get.side_effect = ResourceNotFoundError("not found")

    node = AzureFilesShareNode(
        client=storage_client,
        rg_name="vystak-test",
        storage_account="mystorage",
        share_name="vystak-assistant-workspace-data",
    )
    result = node.provision({})

    assert result.success is True
    storage_client.file_shares.create.assert_called_once()
    assert result.info["share_name"] == "vystak-assistant-workspace-data"
    assert result.info["created"] is True


def test_provision_idempotent_when_share_exists():
    storage_client = MagicMock()
    existing = MagicMock(name="existing-share")
    storage_client.file_shares.get.return_value = existing

    node = AzureFilesShareNode(
        client=storage_client,
        rg_name="vystak-test",
        storage_account="mystorage",
        share_name="vystak-assistant-workspace-data",
    )
    result = node.provision({})

    assert result.success is True
    storage_client.file_shares.create.assert_not_called()
    assert result.info["created"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_files_share.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the node**

```python
# packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/files_share.py
"""Idempotent Azure Files share for workspace persistence: volume."""

from __future__ import annotations

from azure.core.exceptions import ResourceNotFoundError

from vystak.provisioning import Provisionable, ProvisionResult


class AzureFilesShareNode(Provisionable):
    """Create or look up an Azure Files share. Idempotent.

    The storage account itself must exist; we do not create it (the spec
    requires the user provides ``platform.config.storage_account``).
    """

    def __init__(
        self,
        *,
        client,
        rg_name: str,
        storage_account: str,
        share_name: str,
    ) -> None:
        self._client = client
        self._rg_name = rg_name
        self._storage_account = storage_account
        self._share_name = share_name

    @property
    def name(self) -> str:
        return f"files-share-{self._share_name}"

    def provision(self, context: dict) -> ProvisionResult:
        try:
            self._client.file_shares.get(
                self._rg_name, self._storage_account, self._share_name
            )
            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "share_name": self._share_name,
                    "storage_account": self._storage_account,
                    "created": False,
                },
            )
        except ResourceNotFoundError:
            self._client.file_shares.create(
                self._rg_name,
                self._storage_account,
                self._share_name,
                {},
            )
            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "share_name": self._share_name,
                    "storage_account": self._storage_account,
                    "created": True,
                },
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_files_share.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/files_share.py \
        packages/python/vystak-provider-azure/tests/test_files_share.py
git commit -m "feat(provider-azure): AzureFilesShareNode — idempotent file share"
```

---

### Task 4: `ACAEnvStorageNode` — register share as ACA Environment storage

**Files:**
- Create: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_env_storage.py`
- Create: `packages/python/vystak-provider-azure/tests/test_aca_env_storage.py`

- [ ] **Step 1: Write the failing test**

```python
# packages/python/vystak-provider-azure/tests/test_aca_env_storage.py
from unittest.mock import MagicMock

from azure.core.exceptions import ResourceNotFoundError

from vystak_provider_azure.nodes.aca_env_storage import ACAEnvStorageNode


def test_provision_creates_env_storage_when_missing():
    aca_client = MagicMock()
    aca_client.managed_environments_storages.get.side_effect = (
        ResourceNotFoundError("not found")
    )
    storage_client = MagicMock()
    storage_client.storage_accounts.list_keys.return_value.keys = [
        MagicMock(value="account-key-1"),
    ]

    node = ACAEnvStorageNode(
        aca_client=aca_client,
        storage_client=storage_client,
        rg_name="vystak-test",
        env_name="vystak-env",
        storage_name="vystak-assistant-workspace",
        storage_account="mystorage",
        share_name="vystak-assistant-workspace-data",
    )
    result = node.provision({})

    assert result.success is True
    aca_client.managed_environments_storages.create_or_update.assert_called_once()
    body = aca_client.managed_environments_storages.create_or_update.call_args.kwargs[
        "managed_environment_storage_envelope"
    ]
    assert body["properties"]["azureFile"]["accountName"] == "mystorage"
    assert body["properties"]["azureFile"]["shareName"] == (
        "vystak-assistant-workspace-data"
    )
    assert body["properties"]["azureFile"]["accessMode"] == "ReadWrite"
    assert result.info["storage_name"] == "vystak-assistant-workspace"


def test_provision_idempotent_when_env_storage_exists():
    aca_client = MagicMock()
    aca_client.managed_environments_storages.get.return_value = MagicMock()
    storage_client = MagicMock()

    node = ACAEnvStorageNode(
        aca_client=aca_client,
        storage_client=storage_client,
        rg_name="vystak-test",
        env_name="vystak-env",
        storage_name="vystak-assistant-workspace",
        storage_account="mystorage",
        share_name="vystak-assistant-workspace-data",
    )
    result = node.provision({})

    assert result.success is True
    aca_client.managed_environments_storages.create_or_update.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_aca_env_storage.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the node**

```python
# packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_env_storage.py
"""Register an Azure Files share as ACA Environment storage.

Multiple Container Apps in the same Environment can mount the share via
volumeMounts; the storage entry is what ties them to the share + account key.
"""

from __future__ import annotations

from azure.core.exceptions import ResourceNotFoundError

from vystak.provisioning import Provisionable, ProvisionResult


class ACAEnvStorageNode(Provisionable):
    def __init__(
        self,
        *,
        aca_client,
        storage_client,
        rg_name: str,
        env_name: str,
        storage_name: str,
        storage_account: str,
        share_name: str,
    ) -> None:
        self._aca = aca_client
        self._storage = storage_client
        self._rg_name = rg_name
        self._env_name = env_name
        self._storage_name = storage_name
        self._storage_account = storage_account
        self._share_name = share_name

    @property
    def name(self) -> str:
        return f"aca-env-storage-{self._storage_name}"

    def provision(self, context: dict) -> ProvisionResult:
        try:
            self._aca.managed_environments_storages.get(
                self._rg_name, self._env_name, self._storage_name
            )
            return ProvisionResult(
                name=self.name,
                success=True,
                info={"storage_name": self._storage_name, "created": False},
            )
        except ResourceNotFoundError:
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
            self._aca.managed_environments_storages.create_or_update(
                resource_group_name=self._rg_name,
                environment_name=self._env_name,
                storage_name=self._storage_name,
                managed_environment_storage_envelope=envelope,
            )
            return ProvisionResult(
                name=self.name,
                success=True,
                info={"storage_name": self._storage_name, "created": True},
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_aca_env_storage.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_env_storage.py \
        packages/python/vystak-provider-azure/tests/test_aca_env_storage.py
git commit -m "feat(provider-azure): ACAEnvStorageNode — register Files share as env storage"
```

---

### Task 5: `ACAWorkspaceAppNode` — deploy the workspace ACA app

This is the largest new node. It builds the workspace image (reusing Docker's `generate_workspace_dockerfile`), pushes to ACR, then deploys an ACA app with internal TCP ingress on port 22 and Key Vault `secretRef` for SSH keys + user secrets.

**Files:**
- Create: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_workspace_app.py`
- Create: `packages/python/vystak-provider-azure/tests/test_aca_workspace_app.py`

- [ ] **Step 1: Write the failing test for revision body shape**

```python
# packages/python/vystak-provider-azure/tests/test_aca_workspace_app.py
from vystak_provider_azure.nodes.aca_workspace_app import (
    build_workspace_revision,
)


def test_build_workspace_revision_internal_tcp_ingress_port_22():
    """Workspace app must expose internal TCP ingress on port 22."""
    body = build_workspace_revision(
        agent_name="assistant",
        location="eastus",
        workspace_image="myacr.azurecr.io/vystak-assistant-workspace:abc",
        workspace_identity_resource_id=(
            "/subscriptions/x/resourceGroups/rg/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/uami-ws"
        ),
        vault_uri="https://kv.vault.azure.net/",
        ssh_kv_secrets=[
            "vystak-workspace-ssh-assistant-host-key",
            "vystak-workspace-ssh-assistant-client-key-pub",
        ],
        user_secrets=["STRIPE_API_KEY"],
        acr_login_server="myacr.azurecr.io",
        acr_password_secret_ref="acr-password",
        acr_password_value="REDACTED",
        storage_name="vystak-assistant-workspace",
        share_subpath="/workspace",
        persistence_mode="volume",
    )

    ingress = body["properties"]["configuration"]["ingress"]
    assert ingress["external"] is False
    assert ingress["transport"] == "tcp"
    assert ingress["targetPort"] == 22
    assert ingress["exposedPort"] == 22


def test_build_workspace_revision_mounts_volume_at_workspace():
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
        storage_name="vystak-assistant-workspace",
        share_subpath="/workspace",
        persistence_mode="volume",
    )
    template = body["properties"]["template"]
    assert template["volumes"] == [
        {
            "name": "workspace-data",
            "storageType": "AzureFile",
            "storageName": "vystak-assistant-workspace",
        }
    ]
    assert template["containers"][0]["volumeMounts"] == [
        {"volumeName": "workspace-data", "mountPath": "/workspace"}
    ]


def test_build_workspace_revision_ephemeral_no_volume_mount():
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
        storage_name=None,
        share_subpath=None,
        persistence_mode="ephemeral",
    )
    template = body["properties"]["template"]
    assert "volumes" not in template or template["volumes"] == []
    assert template["containers"][0].get("volumeMounts", []) == []


def test_build_workspace_revision_ssh_keys_via_secretref():
    body = build_workspace_revision(
        agent_name="assistant",
        location="eastus",
        workspace_image="acr/img:tag",
        workspace_identity_resource_id="x",
        vault_uri="https://kv.vault.azure.net/",
        ssh_kv_secrets=[
            "vystak-workspace-ssh-assistant-host-key",
            "vystak-workspace-ssh-assistant-client-key-pub",
        ],
        user_secrets=[],
        acr_login_server="acr.azurecr.io",
        acr_password_secret_ref="acr-pwd",
        acr_password_value="REDACTED",
        storage_name="ws",
        share_subpath="/workspace",
        persistence_mode="volume",
    )
    secrets = body["properties"]["configuration"]["secrets"]
    secret_names = {s["name"] for s in secrets}
    assert "vystak-workspace-ssh-assistant-host-key" in secret_names
    assert "vystak-workspace-ssh-assistant-client-key-pub" in secret_names

    container = body["properties"]["template"]["containers"][0]
    env_names = {e["name"] for e in container["env"]}
    assert "VYSTAK_SSH_HOST_KEY" in env_names
    assert "VYSTAK_SSH_AUTHORIZED_KEYS" in env_names


def test_build_workspace_revision_scale_locked_to_one():
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
        storage_name="ws",
        share_subpath="/workspace",
        persistence_mode="volume",
    )
    scale = body["properties"]["template"]["scale"]
    assert scale["minReplicas"] == 1
    assert scale["maxReplicas"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_aca_workspace_app.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `build_workspace_revision`**

```python
# packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_workspace_app.py
"""Workspace ACA app — standalone two-app pattern (port 22 internal TCP).

Mirrors the Docker workspace container but as a separate ACA app reachable
via internal DNS at <name>.internal.<env-default-domain>:22.
"""

from __future__ import annotations

from typing import Any

from vystak.provisioning import Provisionable, ProvisionResult


_SSH_ENV_MAP = {
    "host-key": "VYSTAK_SSH_HOST_KEY",
    "client-key-pub": "VYSTAK_SSH_AUTHORIZED_KEYS",
}


def _ssh_env_var_for_secret(secret_name: str) -> str | None:
    """Map a KV secret name → the env var the workspace shim consumes."""
    for kind, env in _SSH_ENV_MAP.items():
        if secret_name.endswith(f"-{kind}"):
            return env
    return None


def build_workspace_revision(
    *,
    agent_name: str,
    location: str,
    workspace_image: str,
    workspace_identity_resource_id: str,
    vault_uri: str,
    ssh_kv_secrets: list[str],
    user_secrets: list[str],
    acr_login_server: str,
    acr_password_secret_ref: str,
    acr_password_value: str,
    storage_name: str | None,
    share_subpath: str | None,
    persistence_mode: str,
) -> dict:
    """Construct the ACA revision body for a workspace app.

    persistence_mode: "volume" requires storage_name; "ephemeral" omits volumes.
    "bind" is rejected upstream by schema validator.
    """
    secrets_block: list[dict] = [
        {
            "name": s,
            "keyVaultUrl": f"{vault_uri}secrets/{s}",
            "identity": workspace_identity_resource_id,
        }
        for s in ssh_kv_secrets
    ]
    for s in user_secrets:
        secrets_block.append(
            {
                "name": s,
                "keyVaultUrl": f"{vault_uri}secrets/{s}",
                "identity": workspace_identity_resource_id,
            }
        )
    secrets_block.append(
        {"name": acr_password_secret_ref, "value": acr_password_value}
    )

    env: list[dict] = []
    for s in ssh_kv_secrets:
        env_var = _ssh_env_var_for_secret(s)
        if env_var is not None:
            env.append({"name": env_var, "secretRef": s})
    for s in user_secrets:
        env.append({"name": s, "secretRef": s})

    containers: list[dict[str, Any]] = [
        {
            "name": "workspace",
            "image": workspace_image,
            "env": env,
            "resources": {"cpu": 0.5, "memory": "1Gi"},
        }
    ]
    template: dict[str, Any] = {
        "containers": containers,
        "scale": {"minReplicas": 1, "maxReplicas": 1},
    }
    if persistence_mode == "volume":
        if storage_name is None or share_subpath is None:
            raise ValueError(
                "persistence='volume' requires storage_name and share_subpath"
            )
        template["volumes"] = [
            {
                "name": "workspace-data",
                "storageType": "AzureFile",
                "storageName": storage_name,
            }
        ]
        containers[0]["volumeMounts"] = [
            {"volumeName": "workspace-data", "mountPath": share_subpath}
        ]

    return {
        "location": location,
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {workspace_identity_resource_id: {}},
        },
        "properties": {
            "configuration": {
                "secrets": secrets_block,
                "registries": [
                    {
                        "server": acr_login_server,
                        "username": acr_login_server.split(".")[0],
                        "passwordSecretRef": acr_password_secret_ref,
                    }
                ],
                "ingress": {
                    "external": False,
                    "transport": "tcp",
                    "targetPort": 22,
                    "exposedPort": 22,
                },
                "identitySettings": [
                    {
                        "identity": workspace_identity_resource_id,
                        "lifecycle": "None",
                    }
                ],
            },
            "template": template,
        },
    }


class ACAWorkspaceAppNode(Provisionable):
    """Build + push workspace image, then deploy workspace ACA app.

    Image build uses Docker SDK locally (reuses Docker provider's
    generate_workspace_dockerfile). Pushed to ACR. ACA app deployed via
    the management client.
    """

    def __init__(
        self,
        *,
        aca_client,
        docker_client,
        rg_name: str,
        env_name: str,
        agent,
        platform_config: dict,
        location: str,
        ssh_keygen_node_name: str,
        files_share_node_name: str | None,
        env_storage_node_name: str | None,
        acr_node_name: str,
        vault_node_name: str,
        workspace_identity_node_name: str,
    ) -> None:
        self._aca = aca_client
        self._docker = docker_client
        self._rg_name = rg_name
        self._env_name = env_name
        self._agent = agent
        self._platform_config = platform_config
        self._location = location
        self._ssh_keygen = ssh_keygen_node_name
        self._files_share = files_share_node_name
        self._env_storage = env_storage_node_name
        self._acr = acr_node_name
        self._vault = vault_node_name
        self._ws_identity = workspace_identity_node_name

    @property
    def name(self) -> str:
        return f"workspace-app-{self._agent.name}"

    @property
    def app_name(self) -> str:
        return f"vystak-{self._agent.name}-workspace"

    def provision(self, context: dict) -> ProvisionResult:
        # Resolve dependencies from context
        acr = context[self._acr].info
        vault = context[self._vault].info
        ws_identity = context[self._ws_identity].info

        # Build & push workspace image
        workspace_image = self._build_and_push_image(
            acr_login_server=acr["login_server"],
            acr_username=acr["login_server"].split(".")[0],
            acr_password=acr["admin_password"],
        )

        # Compose KV secret names
        ssh_kv_secrets = [
            f"vystak-workspace-ssh-{self._agent.name}-host-key",
            f"vystak-workspace-ssh-{self._agent.name}-client-key-pub",
        ]
        user_secrets = [s.name for s in (self._agent.workspace.secrets or [])]

        storage_name = (
            None
            if self._env_storage is None
            else context[self._env_storage].info["storage_name"]
        )
        share_subpath = (
            "/workspace" if self._agent.workspace.persistence == "volume" else None
        )

        body = build_workspace_revision(
            agent_name=self._agent.name,
            location=self._location,
            workspace_image=workspace_image,
            workspace_identity_resource_id=ws_identity["resource_id"],
            vault_uri=vault["vault_uri"],
            ssh_kv_secrets=ssh_kv_secrets,
            user_secrets=user_secrets,
            acr_login_server=acr["login_server"],
            acr_password_secret_ref="acr-password",
            acr_password_value=acr["admin_password"],
            storage_name=storage_name,
            share_subpath=share_subpath,
            persistence_mode=self._agent.workspace.persistence,
        )

        poller = self._aca.container_apps.begin_create_or_update(
            resource_group_name=self._rg_name,
            container_app_name=self.app_name,
            container_app_envelope=body,
        )
        result = poller.result()

        env_default_domain = context[f"aca-env-{self._env_name}"].info[
            "default_domain"
        ]
        workspace_host = f"{self.app_name}.internal.{env_default_domain}"

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "app_name": self.app_name,
                "workspace_host": workspace_host,
                "image": workspace_image,
                "fqdn": getattr(result, "configuration", None),
            },
        )

    def _build_and_push_image(
        self,
        *,
        acr_login_server: str,
        acr_username: str,
        acr_password: str,
    ) -> str:
        """Reuse Docker provider's dockerfile generator + workspace_rpc bundle.

        Image tag includes a content hash so reused builds are skipped by ACR.
        """
        from pathlib import Path
        import shutil

        from vystak_provider_docker.workspace_image import (
            generate_workspace_dockerfile,
        )
        from vystak_provider_docker.templates import generate_entrypoint_shim

        ws = self._agent.workspace
        build_dir = Path(".vystak") / f"{self._agent.name}-workspace-azure"
        build_dir.mkdir(parents=True, exist_ok=True)

        if ws.dockerfile:
            shutil.copy(Path(ws.dockerfile).resolve(), build_dir / "Dockerfile")
        else:
            df = generate_workspace_dockerfile(
                image=ws.image,
                provision=ws.provision,
                copy=ws.copy,
                tool_deps_manager=ws.tool_deps_manager,
                use_entrypoint_shim=True,
            )
            (build_dir / "Dockerfile").write_text(df)

        (build_dir / "entrypoint-shim.sh").write_text(generate_entrypoint_shim())

        import vystak_workspace_rpc

        rpc_src = Path(vystak_workspace_rpc.__file__).parent
        rpc_dst = build_dir / "vystak_workspace_rpc"
        if rpc_dst.exists():
            shutil.rmtree(rpc_dst)
        shutil.copytree(rpc_src, rpc_dst)
        (build_dir / "setup.py").write_text(
            "from setuptools import setup, find_packages\n"
            "setup(name='vystak-workspace-rpc', version='0.1.0',\n"
            "      packages=find_packages())\n"
        )

        image_tag = (
            f"{acr_login_server}/vystak-{self._agent.name}-workspace:latest"
        )
        self._docker.login(
            registry=acr_login_server,
            username=acr_username,
            password=acr_password,
        )
        self._docker.images.build(path=str(build_dir), tag=image_tag, rm=True)
        for line in self._docker.images.push(image_tag, stream=True, decode=True):
            if line.get("error"):
                raise RuntimeError(f"Push failed: {line['error']}")
        return image_tag
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_aca_workspace_app.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_workspace_app.py \
        packages/python/vystak-provider-azure/tests/test_aca_workspace_app.py
git commit -m "feat(provider-azure): ACAWorkspaceAppNode — standalone two-app workspace"
```

---

## Phase 3 — Extend the entrypoint shim

### Task 6: Extend `generate_entrypoint_shim` to materialize SSH keys from env vars

Both Docker (Vault path) and Azure consume the same shim. The extension is backward-compatible — it only acts when `VYSTAK_SSH_*` env vars are set.

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py:155-193`
- Modify: `packages/python/vystak-provider-docker/tests/test_templates.py` (or appropriate test file)

- [ ] **Step 1: Write the failing test**

```python
# packages/python/vystak-provider-docker/tests/test_entrypoint_shim_ssh_keys.py
from vystak_provider_docker.templates import generate_entrypoint_shim


def test_shim_writes_host_key_from_env_var():
    """When VYSTAK_SSH_HOST_KEY is set, shim writes /etc/ssh/ssh_host_ed25519_key."""
    shim = generate_entrypoint_shim()
    assert 'VYSTAK_SSH_HOST_KEY' in shim
    assert '/etc/ssh/ssh_host_ed25519_key' in shim
    assert 'chmod 600 /etc/ssh/ssh_host_ed25519_key' in shim
    assert 'unset VYSTAK_SSH_HOST_KEY' in shim


def test_shim_writes_authorized_keys_from_env_var():
    shim = generate_entrypoint_shim()
    assert 'VYSTAK_SSH_AUTHORIZED_KEYS' in shim
    assert '/etc/ssh/authorized_keys_vystak-agent' in shim
    assert 'chmod 444 /etc/ssh/authorized_keys_vystak-agent' in shim
    assert 'unset VYSTAK_SSH_AUTHORIZED_KEYS' in shim


def test_shim_writes_client_key_from_env_var():
    shim = generate_entrypoint_shim()
    assert 'VYSTAK_SSH_CLIENT_KEY' in shim
    assert '/vystak/ssh/id_ed25519' in shim
    assert 'chmod 600 /vystak/ssh/id_ed25519' in shim


def test_shim_writes_known_hosts_from_env_var():
    shim = generate_entrypoint_shim()
    assert 'VYSTAK_SSH_KNOWN_HOSTS_PUB' in shim
    assert '/vystak/ssh/known_hosts' in shim
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_entrypoint_shim_ssh_keys.py -v`
Expected: FAIL on all four assertions (env vars not in current shim).

- [ ] **Step 3: Modify the shim generator**

Open `packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py` and replace the `return """..."""` block in `generate_entrypoint_shim` (lines ~166-193) with this expanded version:

```python
    return """\
#!/bin/sh
# vystak entrypoint shim — waits for Vault Agent to render secrets, then exec
set -e

SECRETS_FILE="/shared/secrets.env"

# Default-path containers won't have /shared/ — skip the wait when the file
# location doesn't exist either.
if [ -d /shared ]; then
  for i in $(seq 1 30); do
    [ -e "$SECRETS_FILE" ] && break
    sleep 1
  done

  if [ ! -e "$SECRETS_FILE" ]; then
    echo "vystak: $SECRETS_FILE never populated — Vault Agent unhealthy?" >&2
    exit 1
  fi

  # Settle: give sibling templates (SSH keys, etc.) a moment to finish.
  sleep 1

  if [ -s "$SECRETS_FILE" ]; then
    set -a
    . "$SECRETS_FILE"
    set +a
  fi
fi

# Materialize SSH key material from env vars (Azure path: secretRef → env).
# Each block writes one file with appropriate perms then unsets the env var
# so the value doesn't leak into the main process's /proc/<pid>/environ.

if [ -n "${VYSTAK_SSH_HOST_KEY:-}" ]; then
  mkdir -p /etc/ssh
  printf '%s' "$VYSTAK_SSH_HOST_KEY" > /etc/ssh/ssh_host_ed25519_key
  chmod 600 /etc/ssh/ssh_host_ed25519_key
  unset VYSTAK_SSH_HOST_KEY
fi

if [ -n "${VYSTAK_SSH_AUTHORIZED_KEYS:-}" ]; then
  mkdir -p /etc/ssh
  printf '%s\\n' "$VYSTAK_SSH_AUTHORIZED_KEYS" > /etc/ssh/authorized_keys_vystak-agent
  chmod 444 /etc/ssh/authorized_keys_vystak-agent
  unset VYSTAK_SSH_AUTHORIZED_KEYS
fi

if [ -n "${VYSTAK_SSH_CLIENT_KEY:-}" ]; then
  mkdir -p /vystak/ssh
  printf '%s' "$VYSTAK_SSH_CLIENT_KEY" > /vystak/ssh/id_ed25519
  chmod 600 /vystak/ssh/id_ed25519
  unset VYSTAK_SSH_CLIENT_KEY
fi

if [ -n "${VYSTAK_SSH_KNOWN_HOSTS_PUB:-}" ]; then
  mkdir -p /vystak/ssh
  printf '%s\\n' "$VYSTAK_SSH_KNOWN_HOSTS_PUB" > /vystak/ssh/known_hosts
  chmod 444 /vystak/ssh/known_hosts
  unset VYSTAK_SSH_KNOWN_HOSTS_PUB
fi

exec "$@"
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_entrypoint_shim_ssh_keys.py -v`
Expected: 4 tests PASS.

Also run existing Docker provider tests to ensure no regression:

Run: `uv run pytest packages/python/vystak-provider-docker/tests/ -v -m "not docker"`
Expected: all existing tests still PASS. (The shim now has an `if [ -d /shared ]` guard for default-path containers; verify this didn't break the Vault-path docker integration tests when run with `-m docker`.)

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py \
        packages/python/vystak-provider-docker/tests/test_entrypoint_shim_ssh_keys.py
git commit -m "feat(workspace): entrypoint shim materializes SSH keys from env vars

Backward-compatible — shim is a no-op when VYSTAK_SSH_* env vars are unset.
Used by the Azure standalone workspace path to render KV-delivered SSH key
material onto disk before exec'ing sshd."
```

---

## Phase 4 — Wire new nodes into `provider.py`

### Task 7: Add `set_workspace_context` to `ContainerAppNode` (agent side)

The agent needs `VYSTAK_WORKSPACE_HOST` (workspace app's internal FQDN) plus the agent's SSH client key + known_hosts envs. Mirrors `DockerAgentNode.set_workspace_context`.

**Files:**
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py` (add new method to `ContainerAppNode` class)
- Modify: `packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py` (new test)

- [ ] **Step 1: Write the failing test**

```python
# Append to packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py
def test_agent_revision_includes_workspace_host_when_context_set():
    """When set_workspace_context() is called, agent env contains
    VYSTAK_WORKSPACE_HOST plus the two SSH KV secretRefs."""
    revision = build_revision_for_vault(
        agent=_make_test_agent_no_workspace(),
        vault_uri="https://kv.vault.azure.net/",
        agent_identity_resource_id=(
            "/subscriptions/x/resourceGroups/rg/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/uami-agent"
        ),
        agent_identity_client_id=None,
        model_secrets=["ANTHROPIC_API_KEY"],
        acr_login_server="acr.azurecr.io",
        acr_password_secret_ref="acr-pwd",
        acr_password_value="REDACTED",
        agent_image="acr.azurecr.io/agent:tag",
        workspace_host="vystak-assistant-workspace.internal.eastus.azurecontainerapps.io",
        workspace_ssh_kv_secrets=[
            "vystak-workspace-ssh-assistant-client-key",
            "vystak-workspace-ssh-assistant-host-key-pub",
        ],
    )
    agent_container = revision["properties"]["template"]["containers"][0]
    env_by_name = {e["name"]: e for e in agent_container["env"]}
    assert env_by_name["VYSTAK_WORKSPACE_HOST"]["value"] == (
        "vystak-assistant-workspace.internal.eastus.azurecontainerapps.io"
    )
    assert env_by_name["VYSTAK_SSH_CLIENT_KEY"]["secretRef"] == (
        "vystak-workspace-ssh-assistant-client-key"
    )
    assert env_by_name["VYSTAK_SSH_KNOWN_HOSTS_PUB"]["secretRef"] == (
        "vystak-workspace-ssh-assistant-host-key-pub"
    )
```

You'll also need a helper `_make_test_agent_no_workspace()` if not present — copy/adapt the existing `_make_test_agent()` and remove the workspace.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py::test_agent_revision_includes_workspace_host_when_context_set -v`
Expected: FAIL — `build_revision_for_vault` doesn't accept `workspace_host`/`workspace_ssh_kv_secrets` kwargs yet.

- [ ] **Step 3: Add the parameters and emit logic**

In `aca_app.py`, change the `build_revision_for_vault` signature to add the two new keyword-only params (default `None` / `[]`) and remove the four sidecar-related ones in a follow-up task. For now, *add* without removing:

```python
def build_revision_for_vault(
    *,
    agent,
    vault_uri: str,
    agent_identity_resource_id: str,
    agent_identity_client_id: str | None,
    workspace_identity_resource_id: str | None,  # to be removed in Task 9
    workspace_identity_client_id: str | None,  # to be removed in Task 9
    model_secrets: list[str],
    workspace_secrets: list[str],  # to be removed in Task 9
    acr_login_server: str,
    acr_password_secret_ref: str,
    acr_password_value: str,
    agent_image: str,
    workspace_image: str | None,  # to be removed in Task 9
    extra_env: list[dict] | None = None,
    workspace_host: str | None = None,  # NEW
    workspace_ssh_kv_secrets: list[str] | None = None,  # NEW
) -> dict:
```

After the existing agent_env construction (around line 230, before the existing `if emit_workspace_sidecar` block), add:

```python
    if workspace_host is not None:
        agent_env.append({"name": "VYSTAK_WORKSPACE_HOST", "value": workspace_host})
    for s in workspace_ssh_kv_secrets or []:
        # Two KV secrets for the agent: client-key (priv) → known_hosts uses host-key-pub
        if s.endswith("-client-key"):
            agent_env.append({"name": "VYSTAK_SSH_CLIENT_KEY", "secretRef": s})
            kv_secrets_block.append(
                {
                    "name": s,
                    "keyVaultUrl": f"{vault_uri}secrets/{s}",
                    "identity": agent_identity_resource_id,
                }
            )
        elif s.endswith("-host-key-pub"):
            agent_env.append({"name": "VYSTAK_SSH_KNOWN_HOSTS_PUB", "secretRef": s})
            kv_secrets_block.append(
                {
                    "name": s,
                    "keyVaultUrl": f"{vault_uri}secrets/{s}",
                    "identity": agent_identity_resource_id,
                }
            )
```

Apply the same pattern to `build_revision_default_path` (which uses inline secrets, not KV refs). The default-path version stores SSH key values inline in `inline_secrets` and references via `secretRef` in `agent_env`. Use the SSH key values passed in via a new `workspace_ssh_secrets: dict[str, str] | None` parameter.

Then add `set_workspace_context` to `ContainerAppNode`:

```python
    def set_workspace_context(
        self,
        *,
        workspace_host: str,
        workspace_ssh_kv_secrets: list[str],
    ) -> None:
        """Wire workspace SSH client keys + known_hosts into the agent app.

        Agent reads VYSTAK_WORKSPACE_HOST + materializes its client key
        and known_hosts pub from KV-delivered secrets via the entrypoint
        shim (Task 6).
        """
        self._workspace_host = workspace_host
        self._workspace_ssh_kv_secrets = workspace_ssh_kv_secrets
```

And thread `_workspace_host` / `_workspace_ssh_kv_secrets` into `_build_body` so they reach `build_revision_for_vault` / `build_revision_default_path`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py -v`
Expected: new test PASSES, all existing tests still PASS (since new params are optional and default to None/[]).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py \
        packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py
git commit -m "feat(provider-azure): ContainerAppNode.set_workspace_context — wire VYSTAK_WORKSPACE_HOST + SSH KV refs"
```

---

### Task 8: Wire new nodes into `provider.py:apply()`

**Files:**
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/provider.py:565-695`
- Create: `packages/python/vystak-provider-azure/tests/test_provider_workspace_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# packages/python/vystak-provider-azure/tests/test_provider_workspace_graph.py
"""Verifies the provision graph wiring for standalone workspace.

Pure-Python test: stubs all Azure clients and asserts which nodes get
added and how dependencies wire."""
from unittest.mock import MagicMock, patch

from vystak.schema import Agent, Model, Platform, Provider, Workspace
from vystak.schema.workspace import WorkspaceSecret
from vystak_provider_azure.provider import AzureProvider


def _agent_with_workspace(persistence: str) -> Agent:
    return Agent(
        name="assistant",
        model=Model(name="claude", provider="anthropic"),
        platform=Platform(
            type="container-apps",
            provider=Provider(name="azure"),
            config={
                "subscription_id": "sub-test",
                "resource_group": "rg-test",
                "location": "eastus",
                "storage_account": "mystorage",  # required for volume
            },
        ),
        workspace=Workspace(
            name="dev",
            image="python:3.11-slim",
            persistence=persistence,
            secrets=[WorkspaceSecret(name="STRIPE_API_KEY")],
        ),
    )


def test_apply_adds_workspace_nodes_when_workspace_declared():
    agent = _agent_with_workspace("volume")
    provider = AzureProvider(agent=agent, generated_code=MagicMock())

    with patch.object(provider, "_build_clients") as build, \
         patch("vystak_provider_azure.provider.ProvisionGraph") as graph_cls:
        graph = MagicMock()
        graph.execute.return_value = {}
        graph_cls.return_value = graph
        build.return_value = (MagicMock(),) * 7  # match real arity

        try:
            provider.apply(MagicMock())
        except Exception:
            pass  # we only care about node additions

        added_node_types = [
            type(call.args[0]).__name__ for call in graph.add.call_args_list
        ]
        assert "AzureWorkspaceSshKeygenNode" in added_node_types
        assert "AzureFilesShareNode" in added_node_types
        assert "ACAEnvStorageNode" in added_node_types
        assert "ACAWorkspaceAppNode" in added_node_types


def test_apply_skips_files_share_when_persistence_ephemeral():
    agent = _agent_with_workspace("ephemeral")
    provider = AzureProvider(agent=agent, generated_code=MagicMock())

    with patch.object(provider, "_build_clients") as build, \
         patch("vystak_provider_azure.provider.ProvisionGraph") as graph_cls:
        graph = MagicMock()
        graph.execute.return_value = {}
        graph_cls.return_value = graph
        build.return_value = (MagicMock(),) * 7

        try:
            provider.apply(MagicMock())
        except Exception:
            pass

        added_node_types = [
            type(call.args[0]).__name__ for call in graph.add.call_args_list
        ]
        assert "AzureFilesShareNode" not in added_node_types
        assert "ACAEnvStorageNode" not in added_node_types
        assert "ACAWorkspaceAppNode" in added_node_types


def test_apply_raises_when_volume_persistence_without_storage_account():
    agent = _agent_with_workspace("volume")
    agent.platform.config.pop("storage_account")
    provider = AzureProvider(agent=agent, generated_code=MagicMock())

    with patch.object(provider, "_build_clients") as build:
        build.return_value = (MagicMock(),) * 7
        with pytest.raises(ValueError, match="storage_account"):
            provider.apply(MagicMock())
```

(Adjust mock arity in `build.return_value = (MagicMock(),) * 7` to match the real `_build_clients` signature — read its return tuple before writing the test.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_provider_workspace_graph.py -v`
Expected: FAIL on `AzureWorkspaceSshKeygenNode in added_node_types`.

- [ ] **Step 3: Wire workspace nodes in `provider.py:apply()`**

In `provider.py`, after the existing vault subgraph setup (around line 646, after `vault_ctx = self._add_vault_nodes(...)` returns), add a workspace subgraph. Insert before the `ContainerAppNode` is added (line 648):

```python
        # Workspace subgraph — only when agent declares workspace
        workspace_host = None
        workspace_ssh_kv_secrets: list[str] = []
        if self._agent.workspace is not None:
            ws = self._agent.workspace
            workspace_ssh_kv_secrets = [
                f"vystak-workspace-ssh-{self._agent.name}-client-key",
                f"vystak-workspace-ssh-{self._agent.name}-host-key-pub",
            ]

            # Validate prerequisites
            if ws.persistence == "volume":
                storage_account = cfg.get("storage_account")
                if not storage_account:
                    raise ValueError(
                        f"Agent '{self._agent.name}': workspace.persistence='volume' "
                        f"requires platform.config.storage_account to be set "
                        f"(name of an existing Azure Storage account). "
                        f"Add it to your vystak.yaml platform config, or use "
                        f"persistence: ephemeral if no persistence is needed."
                    )

            # 1. Keygen — uploads 4 SSH secrets to KV
            keygen_node = AzureWorkspaceSshKeygenNode(
                agent_name=self._agent.name,
                secret_client=secret_client,
                docker_client=docker_client,
            )
            graph.add(keygen_node)

            # 2. Files share + env storage — only on volume mode
            files_share_name = None
            env_storage_name = None
            if ws.persistence == "volume":
                share_name = f"vystak-{self._agent.name}-workspace-data"
                share_node = AzureFilesShareNode(
                    client=storage_client,
                    rg_name=rg_name,
                    storage_account=storage_account,
                    share_name=share_name,
                )
                graph.add(share_node)
                files_share_name = share_node.name

                storage_logical_name = f"vystak-{self._agent.name}-workspace"
                env_storage_node = ACAEnvStorageNode(
                    aca_client=aca_client,
                    storage_client=storage_client,
                    rg_name=rg_name,
                    env_name=env_name,
                    storage_name=storage_logical_name,
                    storage_account=storage_account,
                    share_name=share_name,
                )
                graph.add(env_storage_node)
                env_storage_name = env_storage_node.name

            # 3. Workspace app
            workspace_app = ACAWorkspaceAppNode(
                aca_client=aca_client,
                docker_client=docker_client,
                rg_name=rg_name,
                env_name=env_name,
                agent=self._agent,
                platform_config=cfg,
                location=location,
                ssh_keygen_node_name=keygen_node.name,
                files_share_node_name=files_share_name,
                env_storage_node_name=env_storage_name,
                acr_node_name=f"acr-{acr_name}",
                vault_node_name=vault_node.name if vault_node else "",
                workspace_identity_node_name=(
                    f"uami-{workspace_identity_key}" if workspace_identity_key else ""
                ),
            )
            graph.add(workspace_app)

            env_default_domain = "${" + env_name + ".defaultDomain}"  # resolved later
            workspace_host = f"{workspace_app.app_name}.internal.{env_default_domain}"
```

Then update the `set_vault_context` call (line 659-666) to also call `set_workspace_context`:

```python
        if workspace_host is not None:
            container_app_node.set_workspace_context(
                workspace_host=workspace_host,
                workspace_ssh_kv_secrets=workspace_ssh_kv_secrets,
            )
```

Add the imports at the top:

```python
from vystak_provider_azure.nodes.workspace_ssh_keygen import (
    AzureWorkspaceSshKeygenNode,
)
from vystak_provider_azure.nodes.files_share import AzureFilesShareNode
from vystak_provider_azure.nodes.aca_env_storage import ACAEnvStorageNode
from vystak_provider_azure.nodes.aca_workspace_app import ACAWorkspaceAppNode
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_provider_workspace_graph.py -v`
Expected: 3 tests PASS.

Run: `uv run pytest packages/python/vystak-provider-azure/tests/ -v -m "not release_smoke_azure"`
Expected: all existing Azure unit tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/provider.py \
        packages/python/vystak-provider-azure/tests/test_provider_workspace_graph.py
git commit -m "feat(provider-azure): wire standalone workspace nodes into apply graph

Adds AzureWorkspaceSshKeygenNode, optional AzureFilesShareNode +
ACAEnvStorageNode (volume mode), and ACAWorkspaceAppNode to the
provision graph when agent.workspace is declared. Validates
platform.config.storage_account when persistence='volume'."
```

---

## Phase 5 — Migrate the example, end-to-end verify

### Task 9: Migrate `examples/azure-workspace-vault` to standalone shape

**Files:**
- Modify: `examples/azure-workspace-vault/vystak.yaml`
- Modify: `examples/azure-workspace-vault/README.md`

- [ ] **Step 1: Update `vystak.yaml` workspace block**

Replace the existing workspace section (currently lines 35-41) with the standalone shape. The schema is unchanged — this is just exercising real fields:

```yaml
workspace:
  name: tools
  image: python:3.11-slim
  persistence: volume   # was: type: persistent
  provision:
    - pip install requests stripe
  secrets:
    - name: STRIPE_API_KEY
      framework: langchain-python
```

Also add `storage_account` to platform config:

```yaml
platform:
  type: container-apps
  provider:
    name: azure
  config:
    subscription_id: ${AZURE_SUBSCRIPTION_ID}
    resource_group: vystak-azure-workspace-vault
    location: eastus
    storage_account: ${AZURE_STORAGE_ACCOUNT}   # NEW — required for persistence: volume
```

- [ ] **Step 2: Update `README.md`** — replace prose mentioning sidecar/`localhost:50051` with the new topology (two ACA apps, internal SSH on port 22, Azure Files mount). Add a section on the prerequisite storage account.

- [ ] **Step 3: Run plan locally to verify shape**

Run: `cd examples/azure-workspace-vault && uv run vystak plan`
Expected: plan output shows the workspace under "Workspaces:" section, lists 4 new nodes (ssh-keygen, files-share, env-storage, workspace-app), no errors.

- [ ] **Step 4: Commit**

```bash
git add examples/azure-workspace-vault/vystak.yaml \
        examples/azure-workspace-vault/README.md
git commit -m "feat(examples): migrate azure-workspace-vault to standalone two-app shape

Was: sidecar in same ACA app, localhost:50051 RPC.
Now: separate workspace ACA app, internal SSH on port 22, Azure Files
mount for persistence: volume. Requires platform.config.storage_account."
```

---

### Task 10: Live deploy verification (opt-in, gated on Azure creds)

**Files:**
- Create: `packages/python/vystak-provider-azure/tests/release/test_A9_workspace_volume.py`

- [ ] **Step 1: Write the release-test cell**

```python
# packages/python/vystak-provider-azure/tests/release/test_A9_workspace_volume.py
"""A9 — Azure + workspace + volume persistence + Vault.

Asserts: V1 plan, V2 apply, V3 isolation (agent can SSH workspace and read
workspace secret; agent cannot read workspace's UAMI token), V4 health
(both apps running), V9 destroy clean.
"""
import os
import pytest

pytestmark = pytest.mark.release_smoke_azure


def test_A9_workspace_volume_lifecycle(azure_project, vault_clean):
    if not os.getenv("AZURE_SUBSCRIPTION_ID"):
        pytest.skip("AZURE_SUBSCRIPTION_ID not set")
    if not os.getenv("AZURE_STORAGE_ACCOUNT"):
        pytest.skip("AZURE_STORAGE_ACCOUNT not set (needed for persistence: volume)")

    # ... copy patterns from existing A1/A2 cells, adapted for workspace+volume.
    # Key assertions:
    # - `vystak plan` shows 4 workspace nodes
    # - `vystak apply` succeeds; both ACA apps reach Running state
    # - SSH from agent to workspace works (test by invoking a builtin tool that
    #   triggers workspace RPC)
    # - `vystak destroy` removes both apps; Azure Files share preserved
    # - `vystak destroy --delete-workspace-data` removes the share
```

- [ ] **Step 2: Run with real Azure creds (opt-in)**

```bash
az login
export AZURE_SUBSCRIPTION_ID=<your-sub>
export AZURE_STORAGE_ACCOUNT=<existing-account>
uv run pytest packages/python/vystak-provider-azure/tests/release/test_A9_workspace_volume.py -v -m release_smoke_azure
```

Expected: PASS in 5–8 minutes. Auto-skips without creds.

- [ ] **Step 3: Commit**

```bash
git add packages/python/vystak-provider-azure/tests/release/test_A9_workspace_volume.py
git commit -m "test(release-azure): A9 cell — workspace + volume + vault end-to-end"
```

---

## Phase 6 — Remove sidecar code

By now the standalone path is shipping. Sidecar code is unreachable; delete it.

### Task 11: Strip sidecar emission from `build_revision_default_path`

**Files:**
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py:29-159`

- [ ] **Step 1: Delete sidecar code blocks**

In `build_revision_default_path`:
- Delete lines 73-76 (the `emit_workspace_sidecar` computation and comment)
- Delete lines 88-94 (workspace secrets added to inline pool)
- Delete lines 104-107 (`VYSTAK_WORKSPACE_RPC_URL` injected into agent env)
- Delete lines 120-133 (workspace sidecar container definition)
- Remove parameters: `workspace_image`, `workspace_secrets` from the signature (lines 29-40)

The function now builds a single-container revision (agent only).

- [ ] **Step 2: Update callers**

In `aca_app.py`'s `ContainerAppNode._build_body`, where `build_revision_default_path` is called, drop the `workspace_image=` and `workspace_secrets=` kwargs.

- [ ] **Step 3: Run tests**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py -v`
Expected: tests that referenced sidecar will FAIL (e.g., `test_build_revision_default_path_isolates_workspace_from_agent`, `test_build_revision_default_path_no_workspace_image_no_sidecar`). These will be deleted in Task 13.

The new `set_workspace_context` test (added in Task 7) should still PASS.

- [ ] **Step 4: Commit (will not be green yet — sidecar tests still need deletion in Task 13)**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py
git commit -m "refactor(provider-azure)!: drop sidecar emission from build_revision_default_path

Workspace is now a standalone ACA app (see Task 8). The sidecar branch
in this builder is unreachable. Tests that exercised it are deleted in
the follow-up commit."
```

---

### Task 12: Strip sidecar emission from `build_revision_for_vault`

**Files:**
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py:162-300`

- [ ] **Step 1: Delete sidecar code blocks**

In `build_revision_for_vault`:
- Delete lines 196-198 (`emit_workspace_sidecar` computation)
- Delete lines 211-219 (workspace KV refs added to secrets block)
- Delete lines 237-245 (`VYSTAK_WORKSPACE_RPC_URL` injection)
- Delete lines 257-269 (workspace sidecar container)
- Remove parameters: `workspace_identity_resource_id`, `workspace_identity_client_id`, `workspace_secrets`, `workspace_image` from the signature (lines 162-178)
- Update `userAssignedIdentities` block (lines 187-191) to drop the workspace identity case

- [ ] **Step 2: Update `set_vault_context` signature in `ContainerAppNode`**

Drop `workspace_identity_key`, `workspace_secrets`, `workspace_image` parameters. Also delete the corresponding instance attrs and the lines in `_build_body` that pass them through.

- [ ] **Step 3: Update the only call site in `provider.py`**

In `provider.py:659-666`, the `set_vault_context` call drops three kwargs:

```python
        if vault_node is not None and agent_identity_key is not None:
            container_app_node.set_vault_context(
                vault_key=vault_node.name,
                agent_identity_key=agent_identity_key,
                model_secrets=model_secrets,
            )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/ -v -m "not release_smoke_azure"`
Expected: existing sidecar tests fail (deleted in next task); other tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_app.py \
        packages/python/vystak-provider-azure/src/vystak_provider_azure/provider.py
git commit -m "refactor(provider-azure)!: drop sidecar emission from build_revision_for_vault

set_vault_context loses workspace_identity_key, workspace_secrets,
workspace_image — workspace is wired separately via set_workspace_context."
```

---

### Task 13: Delete obsolete sidecar tests

**Files:**
- Modify: `packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py`

- [ ] **Step 1: Delete the following test functions (no longer applicable)**

- `test_build_revision_agent_plus_workspace_sidecar` (line 82)
- `test_container_app_node_uses_vault_path_when_vault_result_in_context` — *only* if it asserts on workspace sidecar; otherwise rewrite to drop workspace-specific assertions (line 126)
- `test_build_revision_default_path_isolates_workspace_from_agent` (line 291)
- `test_build_revision_default_path_no_workspace_image_no_sidecar` (line 339)
- `test_build_revision_for_vault_no_rpc_url_when_no_sidecar` (line 391)
- `test_build_revision_for_vault_drops_dead_workspace_refs` (line 423)

Keep tests that exercise inline-secret isolation between agent secrets and other inline values — they're still relevant.

- [ ] **Step 2: Run all tests**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/ -v -m "not release_smoke_azure"`
Expected: all PASS.

- [ ] **Step 3: Verify no `VYSTAK_WORKSPACE_RPC_URL` references remain**

Run: `grep -rn "VYSTAK_WORKSPACE_RPC_URL\|emit_workspace_sidecar\|localhost:50051" packages/python/vystak-provider-azure/`
Expected: no hits.

- [ ] **Step 4: Commit**

```bash
git add packages/python/vystak-provider-azure/tests/test_aca_app_secretref.py
git commit -m "test(provider-azure): drop sidecar tests — superseded by standalone path"
```

---

## Phase 7 — Hash + plan output + docs

### Task 14: Verify workspace hash still triggers redeploy

The hash tree includes `workspace.image` and `workspace.provision` already (see `vystak/hash/tree.py:91-276`). After the refactor, changing those should still bump the agent hash and trigger a new ACA revision.

**Files:**
- Verify only — no code changes expected.

- [ ] **Step 1: Run hash tests**

Run: `uv run pytest packages/python/vystak/tests/test_tree.py packages/python/vystak/tests/test_hash_tree_secrets.py -v`
Expected: all PASS.

- [ ] **Step 2: Manual sanity check**

Run: `cd examples/azure-workspace-vault && uv run vystak plan`
Note the agent hash. Edit `vystak.yaml`, change `workspace.image` from `python:3.11-slim` to `python:3.12-slim`. Run `vystak plan` again.
Expected: agent hash differs; plan output flags workspace app for redeploy.

Revert the change.

- [ ] **Step 3: No commit needed.**

---

### Task 15: Update `vystak plan` output for new workspace topology

The "Workspaces:" section in `plan.py` should describe the new shape (separate app, port 22, persistence mode) rather than implying sidecar.

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/plan.py` (the Workspaces section, ~line 85-125)
- Modify: `packages/python/vystak-cli/tests/test_plan_workspace_output.py` (if exists; otherwise add)

- [ ] **Step 1: Read current output format**

Run: `cd examples/azure-workspace-vault && uv run vystak plan`
Inspect the "Workspaces:" section. Note how it's worded.

- [ ] **Step 2: Update wording**

Aim for output like:

```
Workspaces:
  assistant.tools
    Image:        python:3.11-slim (4 RUN steps)
    Persistence:  volume → Azure Files share vystak-assistant-workspace-data
    Topology:     standalone ACA app (port 22, internal TCP)
    Secrets:      STRIPE_API_KEY
```

(Adjust the actual code in `plan.py` to match. If the current wording is platform-agnostic, less work is needed — just verify it doesn't claim "sidecar" anywhere.)

- [ ] **Step 3: Run tests + manual verify**

Run: `uv run pytest packages/python/vystak-cli/tests/ -v`
Run: `cd examples/azure-workspace-vault && uv run vystak plan`
Expected: tests PASS; plan output reflects new topology.

- [ ] **Step 4: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/plan.py \
        packages/python/vystak-cli/tests/  # if changed
git commit -m "feat(cli): plan output describes standalone workspace topology"
```

---

### Task 16: Final CI parity check + branch summary

- [ ] **Step 1: Full local CI**

Run:
```bash
just lint-python
just typecheck-python || true   # known pre-existing issues per CLAUDE.md
just test-python
```

Expected: lint PASS, test PASS. (`typecheck-python` has pre-existing failures unrelated to this work; verify no *new* errors in files touched by this branch.)

- [ ] **Step 2: Full Azure suite (with creds)**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/ -v -m "not release_smoke_azure"`
Expected: all PASS.

With `AZURE_SUBSCRIPTION_ID` set: `-m release_smoke_azure` should also PASS for A1, A2, and the new A9.

- [ ] **Step 3: Push branch + open PR**

```bash
git push -u origin feat/aca-workspace-compute
gh pr create --title "feat(provider-azure): standalone workspace (sidecar → two-app SSH-RPC)" \
  --body "$(cat <<'EOF'
## Summary
- Replaces ACA workspace sidecar (TCP RPC on localhost:50051) with a standalone two-app pattern (SSH-RPC on internal port 22)
- Unifies transport with the Docker provider (both now use SSH-RPC)
- Adds Azure Files persistence for `workspace.persistence: volume`

## Spec
`docs/superpowers/specs/2026-04-23-aca-workspace-compute-design.md` (commit e64251e)

## Test plan
- [x] All Azure unit tests pass (mocked clients)
- [x] `examples/azure-workspace-vault` migrated and `vystak plan` output verified
- [ ] Live A9 release test (workspace + volume + vault) green with real Azure creds
- [ ] Hash-based redeploy verified manually (image change → new revision)
EOF
)"
```

---

## Self-Review Checklist (run after writing the plan; do not commit)

- [x] **Spec coverage:** Every section of the spec is covered. Topology → Tasks 5, 8. New nodes → Tasks 2-5. Reused 1:1 → Tasks 5 (`generate_workspace_dockerfile`), 6 (shim). SSH key delivery table → Task 6. Persistence table → Tasks 3, 4, 5. Networking → Task 5. Scale → Task 5. Destroy semantics → existing CLI flags; no work. Schema changes → Task 1 (validator already on branch). Out-of-scope items honored (no human SSH on Azure, no KEDA, no multi-replica).

- [x] **Placeholder scan:** No "TBD", "implement later", "similar to". Code blocks present where steps modify code.

- [x] **Type consistency:** `AzureWorkspaceSshKeygenNode`, `AzureFilesShareNode`, `ACAEnvStorageNode`, `ACAWorkspaceAppNode` — names match across tasks. KV secret naming `vystak-workspace-ssh-<agent>-<kind>` consistent. Env var names (`VYSTAK_SSH_HOST_KEY`, etc.) consistent across shim, workspace app revision, and agent app revision.

- [x] **Known imperfection:** Task 7 keeps the sidecar parameters on `build_revision_for_vault` to maintain test passability across the migration. Task 12 deletes them. This is intentional — let the working branch stay deployable through Task 11.

- [x] **Risks acknowledged:** Spec's "Known risks" (idle SSH timeout, storage account creation race, cold-start) are inherited by this implementation. The plan does not add code to address them; they're operational concerns for the running system.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-10-azure-standalone-workspace.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
