# HashiCorp Vault Backend (Docker) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the HashiCorp Vault backend per `docs/superpowers/specs/2026-04-20-hashicorp-vault-backend-design.md`: Docker provider learns to deploy a production-mode Vault container, create per-principal AppRoles + policies, render per-container secret files via Vault Agent sidecars, and inject an entrypoint shim so main containers source secrets into env before exec.

**Architecture:** Adds a Vault subgraph to `DockerProvider.apply()` when `Vault(type="vault", provider=docker)` is declared. Each principal gets its own AppRole + policy + secret volume + Vault Agent sidecar. The main container's Dockerfile is modified to include an entrypoint shim that sources `/shared/secrets.env` before executing the main process. Schema and runtime SDK unchanged from v1.

**Tech Stack:** Python 3.11+, Pydantic v2, `uv` workspace, pytest, `docker-py`, `hvac` (HashiCorp Vault Python client), HashiCorp Vault 1.17+ image.

---

## Reference

- Spec: `docs/superpowers/specs/2026-04-20-hashicorp-vault-backend-design.md`
- v1 Secret Manager spec: `docs/superpowers/specs/2026-04-19-secret-manager-design.md`
- Schema package: `packages/python/vystak/src/vystak/`
- Docker provider: `packages/python/vystak-provider-docker/src/vystak_provider_docker/`
- CLI: `packages/python/vystak-cli/src/vystak_cli/`

## File structure (created / modified)

**Created:**
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/vault_client.py` — `hvac` wrapper with init/unseal/approle/kv-v2 helpers
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py` — HCL template generators (server config, agent config, policy HCL, entrypoint shim)
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/hashi_vault.py` — `HashiVaultServerNode`, `HashiVaultInitNode`, `HashiVaultUnsealNode`
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_kv_setup.py` — `VaultKvSetupNode` (enables KV v2 + AppRole auth)
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/approle.py` — `AppRoleNode` (creates policy + AppRole per principal)
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_secret_sync.py` — `VaultSecretSyncNode`
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/approle_credentials.py` — `AppRoleCredentialsNode` (writes role_id + secret_id to per-principal volume)
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_agent.py` — `VaultAgentSidecarNode`
- `packages/python/vystak-provider-docker/tests/test_vault_client.py`
- `packages/python/vystak-provider-docker/tests/test_templates.py`
- `packages/python/vystak-provider-docker/tests/test_node_hashi_vault.py`
- `packages/python/vystak-provider-docker/tests/test_node_vault_kv_setup.py`
- `packages/python/vystak-provider-docker/tests/test_node_approle.py`
- `packages/python/vystak-provider-docker/tests/test_node_vault_secret_sync.py`
- `packages/python/vystak-provider-docker/tests/test_node_approle_credentials.py`
- `packages/python/vystak-provider-docker/tests/test_node_vault_agent.py`
- `packages/python/vystak-provider-docker/tests/test_vault_integration.py` — docker-marked
- `examples/docker-workspace-vault/vystak.py`, `vystak.yaml`, `.env.example`, `README.md`, `tools/charge_card.py`

**Modified:**
- `packages/python/vystak/src/vystak/schema/common.py` — add `VaultType.VAULT`
- `packages/python/vystak/src/vystak/schema/multi_loader.py` — cross-object validator for `(vault.type, provider.type)` pairing
- `packages/python/vystak-provider-docker/pyproject.toml` — add `hvac>=2.0`
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py` — type-aware plan rejection, `_add_vault_nodes()` helper, `set_env_values()`, `set_force_sync()`, `set_allow_missing()`, wire into `apply()`
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/__init__.py` — export new nodes
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py` — inject entrypoint shim + mount `/shared` volume when vault context passed
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/channel.py` — same entrypoint-shim + volume injection
- `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py` — dispatch by `Vault.type`; add `rotate-approle` subcommand
- `packages/python/vystak-cli/src/vystak_cli/commands/plan.py` — Hashi-specific sections
- `packages/python/vystak-cli/src/vystak_cli/commands/destroy.py` — add `--delete-vault`, `--keep-sidecars` flags
- `packages/python/vystak-cli/src/vystak_cli/commands/apply.py` — thread vault + env values into `DockerProvider` (mirrors what's already done for `AzureProvider`)

---

## Phase 1 — Schema foundation

### Task 1: Add `VaultType.VAULT` enum value

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/common.py`
- Test: `packages/python/vystak/tests/test_common.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/python/vystak/tests/test_common.py`:

```python
def test_vault_type_includes_hashi_vault():
    from vystak.schema.common import VaultType
    assert VaultType.VAULT.value == "vault"
    # Both backends now present
    assert {t.value for t in VaultType} == {"key-vault", "vault"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak/tests/test_common.py::test_vault_type_includes_hashi_vault -v`
Expected: FAIL — only `KEY_VAULT` present.

- [ ] **Step 3: Implement**

In `packages/python/vystak/src/vystak/schema/common.py`, update `VaultType`:

```python
class VaultType(StrEnum):
    KEY_VAULT = "key-vault"
    VAULT = "vault"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak/tests/test_common.py -v`
Expected: PASS (all tests, including new one and existing v1 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/common.py packages/python/vystak/tests/test_common.py
git commit -m "feat(schema): add VaultType.VAULT enum for HashiCorp backend"
```

---

### Task 2: Cross-object validator for `(vault.type, provider.type)` pairing

**Files:**
- Modify: `packages/python/vystak/src/vystak/schema/multi_loader.py`
- Test: `packages/python/vystak/tests/test_multi_loader_vault.py` (extend existing)

- [ ] **Step 1: Write the failing tests**

Append to `packages/python/vystak/tests/test_multi_loader_vault.py`:

```python
def test_vault_type_vault_requires_docker_provider():
    data = dict(AZURE_ONE_AGENT_WITH_VAULT)
    data["vault"] = {
        "name": "v",
        "provider": "azure",
        "mode": "deploy",
        "type": "vault",   # hashi type with azure provider = error
        "config": {"image": "hashicorp/vault:1.17"},
    }
    with pytest.raises(ValueError, match="type='vault' requires provider.type='docker'"):
        load_multi_yaml(data)


def test_vault_type_key_vault_requires_azure_provider():
    data = dict(AZURE_ONE_AGENT_WITH_VAULT)
    data["providers"]["docker"] = {"type": "docker"}
    data["vault"] = {
        "name": "v",
        "provider": "docker",
        "mode": "deploy",
        "type": "key-vault",  # azure type with docker provider = error
        "config": {"vault_name": "v"},
    }
    with pytest.raises(ValueError, match="type='key-vault' requires provider.type='azure'"):
        load_multi_yaml(data)


def test_hashi_vault_valid_pairing_loads():
    data = {
        "providers": {"docker": {"type": "docker"}, "anthropic": {"type": "anthropic"}},
        "platforms": {"local": {"type": "docker", "provider": "docker"}},
        "vault": {
            "name": "v",
            "provider": "docker",
            "mode": "deploy",
            "type": "vault",
            "config": {},
        },
        "models": {"sonnet": {"provider": "anthropic", "model_name": "claude-sonnet-4-20250514"}},
        "agents": [
            {"name": "a", "model": "sonnet", "platform": "local",
             "secrets": [{"name": "ANTHROPIC_API_KEY"}]},
        ],
    }
    agents, channels, vault = load_multi_yaml(data)
    assert vault is not None
    assert vault.type.value == "vault"
    assert vault.provider.type == "docker"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak/tests/test_multi_loader_vault.py -v -k "vault_type or hashi_vault"`
Expected: FAIL — all three. The loader currently accepts any `(type, provider)` pairing.

- [ ] **Step 3: Implement validator in `multi_loader.py`**

In `packages/python/vystak/src/vystak/schema/multi_loader.py`, inside `load_multi_yaml` where `vault = Vault(...)` is constructed, add immediately after:

```python
    if vault is not None:
        _validate_vault_provider_pairing(vault)
```

And add at module scope:

```python
def _validate_vault_provider_pairing(vault: Vault) -> None:
    """Enforce Vault.type ↔ Provider.type coupling at load time."""
    from vystak.schema.common import VaultType

    provider_type = vault.provider.type
    if vault.type is VaultType.KEY_VAULT and provider_type != "azure":
        raise ValueError(
            f"Vault '{vault.name}' has type='key-vault' requires "
            f"provider.type='azure'. Current: provider.type='{provider_type}'."
        )
    if vault.type is VaultType.VAULT and provider_type != "docker":
        raise ValueError(
            f"Vault '{vault.name}' has type='vault' requires "
            f"provider.type='docker'. Current: provider.type='{provider_type}'."
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak/tests/test_multi_loader_vault.py -v`
Expected: PASS (including pre-existing v1 tests — the KEY_VAULT+azure case).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak/src/vystak/schema/multi_loader.py packages/python/vystak/tests/test_multi_loader_vault.py
git commit -m "feat(schema): validate Vault.type ↔ Provider.type pairing at load time"
```

---

## Phase 2 — Docker provider dependency

### Task 3: Add `hvac` to docker provider deps

**Files:**
- Modify: `packages/python/vystak-provider-docker/pyproject.toml`

- [ ] **Step 1: Edit pyproject**

In `packages/python/vystak-provider-docker/pyproject.toml`, add to `dependencies`:

```toml
dependencies = [
    # ... existing ...
    "hvac>=2.0",
]
```

- [ ] **Step 2: Sync the workspace**

Run: `uv sync`
Expected: `+ hvac==2.x.x` line in output.

- [ ] **Step 3: Smoke-test the install**

Run: `uv run python -c "import hvac; print(hvac.__version__)"`
Expected: version string (e.g., `2.3.0`).

- [ ] **Step 4: Commit**

```bash
git add packages/python/vystak-provider-docker/pyproject.toml uv.lock
git commit -m "chore(provider-docker): add hvac dependency for Vault backend"
```

---

## Phase 3 — Vault HTTP client wrapper

### Task 4: `vault_client.py` — hvac-based helper

**Files:**
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/vault_client.py`
- Test: `packages/python/vystak-provider-docker/tests/test_vault_client.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/python/vystak-provider-docker/tests/test_vault_client.py`:

```python
"""Tests for the Vault HTTP client wrapper."""

from unittest.mock import MagicMock, patch

import pytest

from vystak_provider_docker.vault_client import (
    VaultClient,
    VaultInitResult,
)


def test_is_initialized_true():
    mock_client = MagicMock()
    mock_client.sys.is_initialized.return_value = True
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200")
        assert client.is_initialized() is True


def test_is_initialized_false():
    mock_client = MagicMock()
    mock_client.sys.is_initialized.return_value = False
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200")
        assert client.is_initialized() is False


def test_initialize_returns_keys_and_token():
    mock_client = MagicMock()
    mock_client.sys.initialize.return_value = {
        "keys_base64": ["k1", "k2", "k3", "k4", "k5"],
        "root_token": "hvs.deadbeef",
    }
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200")
        result = client.initialize(key_shares=5, key_threshold=3)
        assert isinstance(result, VaultInitResult)
        assert result.unseal_keys == ["k1", "k2", "k3", "k4", "k5"]
        assert result.root_token == "hvs.deadbeef"
        mock_client.sys.initialize.assert_called_once_with(secret_shares=5, secret_threshold=3)


def test_unseal_with_keys_calls_per_key():
    mock_client = MagicMock()
    mock_client.sys.is_sealed.side_effect = [True, True, False]
    mock_client.sys.submit_unseal_key.return_value = {"sealed": False}
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200")
        client.unseal(["k1", "k2", "k3"])
        assert mock_client.sys.submit_unseal_key.call_count == 3
        mock_client.sys.submit_unseal_key.assert_any_call("k1")
        mock_client.sys.submit_unseal_key.assert_any_call("k2")
        mock_client.sys.submit_unseal_key.assert_any_call("k3")


def test_enable_kv_v2_idempotent():
    mock_client = MagicMock()
    # sys.list_mounted_secrets_engines returns existing mounts
    mock_client.sys.list_mounted_secrets_engines.return_value = {
        "secret/": {"type": "kv", "options": {"version": "2"}}
    }
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        client.enable_kv_v2("secret")
        mock_client.sys.enable_secrets_engine.assert_not_called()


def test_enable_kv_v2_creates_when_absent():
    mock_client = MagicMock()
    mock_client.sys.list_mounted_secrets_engines.return_value = {"other/": {"type": "kv"}}
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        client.enable_kv_v2("secret")
        mock_client.sys.enable_secrets_engine.assert_called_once_with(
            backend_type="kv", path="secret", options={"version": "2"}
        )


def test_enable_approle_auth_idempotent():
    mock_client = MagicMock()
    mock_client.sys.list_auth_methods.return_value = {"approle/": {"type": "approle"}}
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        client.enable_approle_auth()
        mock_client.sys.enable_auth_method.assert_not_called()


def test_write_policy():
    mock_client = MagicMock()
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        client.write_policy("my-policy", 'path "secret/data/FOO" { capabilities = ["read"] }')
        mock_client.sys.create_or_update_policy.assert_called_once()


def test_upsert_approle_creates_role():
    mock_client = MagicMock()
    mock_client.auth.approle.read_role.side_effect = Exception("not found")
    mock_client.auth.approle.read_role_id.return_value = {
        "data": {"role_id": "role-id-1"}
    }
    mock_client.auth.approle.generate_secret_id.return_value = {
        "data": {"secret_id": "secret-id-1"}
    }
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        role_id, secret_id = client.upsert_approle(
            role_name="my-role",
            policies=["my-policy"],
            token_ttl="1h",
            token_max_ttl="24h",
        )
        assert role_id == "role-id-1"
        assert secret_id == "secret-id-1"
        mock_client.auth.approle.create_or_update_approle.assert_called_once()


def test_kv_get_returns_none_on_missing():
    mock_client = MagicMock()
    import hvac.exceptions

    mock_client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.InvalidPath
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        assert client.kv_get("MISSING") is None


def test_kv_get_returns_value():
    mock_client = MagicMock()
    mock_client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"value": "the-secret"}}
    }
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        assert client.kv_get("MY_KEY") == "the-secret"


def test_kv_put_writes_value_under_value_field():
    mock_client = MagicMock()
    with patch("vystak_provider_docker.vault_client.hvac.Client", return_value=mock_client):
        client = VaultClient("http://vystak-vault:8200", token="root-token")
        client.kv_put("MY_KEY", "secret-value")
        mock_client.secrets.kv.v2.create_or_update_secret.assert_called_once_with(
            path="MY_KEY", secret={"value": "secret-value"}
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_vault_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'VaultClient'`.

- [ ] **Step 3: Implement `vault_client.py`**

Create `packages/python/vystak-provider-docker/src/vystak_provider_docker/vault_client.py`:

```python
"""Thin wrapper over hvac for Vault init / unseal / AppRole / KV v2 operations.

Exists so provisioning nodes can mock a small, narrow interface instead of
full hvac. Also centralizes idempotency checks (enable-if-missing) and
normalizes KV v2's `{data: {data: {value}}}` path into flat get/put.
"""

from dataclasses import dataclass

import hvac
import hvac.exceptions


@dataclass
class VaultInitResult:
    unseal_keys: list[str]
    root_token: str


class VaultClient:
    """Narrow wrapper around hvac — only the operations vystak uses."""

    def __init__(self, url: str, token: str | None = None):
        self._url = url
        self._client = hvac.Client(url=url, token=token)

    # -- lifecycle --------------------------------------------------------

    def is_initialized(self) -> bool:
        return bool(self._client.sys.is_initialized())

    def is_sealed(self) -> bool:
        return bool(self._client.sys.is_sealed())

    def initialize(self, *, key_shares: int = 5, key_threshold: int = 3) -> VaultInitResult:
        result = self._client.sys.initialize(
            secret_shares=key_shares, secret_threshold=key_threshold
        )
        return VaultInitResult(
            unseal_keys=result["keys_base64"],
            root_token=result["root_token"],
        )

    def unseal(self, keys: list[str]) -> None:
        for key in keys:
            if not self._client.sys.is_sealed():
                break
            self._client.sys.submit_unseal_key(key)

    def set_token(self, token: str) -> None:
        self._client.token = token

    # -- kv v2 / approle setup -------------------------------------------

    def enable_kv_v2(self, mount_path: str = "secret") -> None:
        mounts = self._client.sys.list_mounted_secrets_engines() or {}
        if f"{mount_path}/" in mounts:
            return
        self._client.sys.enable_secrets_engine(
            backend_type="kv", path=mount_path, options={"version": "2"}
        )

    def enable_approle_auth(self) -> None:
        methods = self._client.sys.list_auth_methods() or {}
        if "approle/" in methods:
            return
        self._client.sys.enable_auth_method(method_type="approle")

    # -- policies + approles ---------------------------------------------

    def write_policy(self, name: str, hcl: str) -> None:
        self._client.sys.create_or_update_policy(name=name, policy=hcl)

    def delete_policy(self, name: str) -> None:
        try:
            self._client.sys.delete_policy(name=name)
        except Exception:
            pass

    def upsert_approle(
        self,
        *,
        role_name: str,
        policies: list[str],
        token_ttl: str = "1h",
        token_max_ttl: str = "24h",
    ) -> tuple[str, str]:
        """Create or update an AppRole and return fresh (role_id, secret_id)."""
        self._client.auth.approle.create_or_update_approle(
            role_name=role_name,
            token_policies=policies,
            token_ttl=token_ttl,
            token_max_ttl=token_max_ttl,
            bind_secret_id=True,
        )
        role_id = self._client.auth.approle.read_role_id(role_name=role_name)["data"]["role_id"]
        secret_id = self._client.auth.approle.generate_secret_id(role_name=role_name)["data"][
            "secret_id"
        ]
        return role_id, secret_id

    def delete_approle(self, role_name: str) -> None:
        try:
            self._client.auth.approle.delete_role(role_name=role_name)
        except Exception:
            pass

    # -- KV v2 with flat interface ---------------------------------------

    def kv_get(self, name: str) -> str | None:
        try:
            resp = self._client.secrets.kv.v2.read_secret_version(path=name)
        except hvac.exceptions.InvalidPath:
            return None
        return resp["data"]["data"].get("value")

    def kv_put(self, name: str, value: str) -> None:
        self._client.secrets.kv.v2.create_or_update_secret(
            path=name, secret={"value": value}
        )

    def kv_list(self) -> list[str]:
        try:
            resp = self._client.secrets.kv.v2.list_secrets(path="")
        except hvac.exceptions.InvalidPath:
            return []
        return resp["data"]["keys"]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_vault_client.py -v`
Expected: PASS (all 13 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/vault_client.py packages/python/vystak-provider-docker/tests/test_vault_client.py
git commit -m "feat(provider-docker): VaultClient wrapping hvac for init/unseal/approle/kv"
```

---

## Phase 4 — HCL + shim template generators

### Task 5: Template generators — server config, agent config, policy

**Files:**
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py`
- Test: `packages/python/vystak-provider-docker/tests/test_templates.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/python/vystak-provider-docker/tests/test_templates.py`:

```python
"""Tests for Vault config template generators."""

from vystak_provider_docker.templates import (
    generate_server_hcl,
    generate_agent_hcl,
    generate_policy_hcl,
    generate_entrypoint_shim,
)


def test_server_hcl_uses_file_storage():
    hcl = generate_server_hcl()
    assert 'storage "file"' in hcl
    assert 'path = "/vault/file"' in hcl
    assert 'listener "tcp"' in hcl
    assert 'address = "0.0.0.0:8200"' in hcl
    assert "tls_disable = true" in hcl  # internal Docker network only


def test_server_hcl_custom_port():
    hcl = generate_server_hcl(port=8900)
    assert 'address = "0.0.0.0:8900"' in hcl


def test_agent_hcl_contains_approle_and_template():
    hcl = generate_agent_hcl(
        vault_address="http://vystak-vault:8200",
        secret_names=["ANTHROPIC_API_KEY", "STRIPE_API_KEY"],
    )
    assert 'vault {\n  address = "http://vystak-vault:8200"' in hcl
    assert 'method "approle"' in hcl
    assert 'role_id_file_path   = "/vault/approle/role_id"' in hcl
    assert 'secret_id_file_path = "/vault/approle/secret_id"' in hcl
    assert 'destination = "/shared/secrets.env"' in hcl
    assert 'perms       = "0444"' in hcl
    assert 'with secret "secret/data/ANTHROPIC_API_KEY"' in hcl
    assert "ANTHROPIC_API_KEY={{ .Data.data.value }}" in hcl
    assert 'with secret "secret/data/STRIPE_API_KEY"' in hcl
    assert "STRIPE_API_KEY={{ .Data.data.value }}" in hcl


def test_agent_hcl_empty_secrets_still_valid():
    hcl = generate_agent_hcl(
        vault_address="http://vystak-vault:8200",
        secret_names=[],
    )
    assert "template {" in hcl
    # Empty template still renders (no `with secret` blocks), file exists but empty.


def test_policy_hcl_one_secret():
    hcl = generate_policy_hcl(secret_names=["ANTHROPIC_API_KEY"])
    assert 'path "secret/data/ANTHROPIC_API_KEY"' in hcl
    assert 'capabilities = ["read"]' in hcl


def test_policy_hcl_multiple_secrets():
    hcl = generate_policy_hcl(secret_names=["A", "B", "C"])
    assert hcl.count("path ") == 3
    for name in ("A", "B", "C"):
        assert f'path "secret/data/{name}"' in hcl


def test_policy_hcl_empty_denies_all():
    hcl = generate_policy_hcl(secret_names=[])
    assert "path" not in hcl


def test_entrypoint_shim_structure():
    shim = generate_entrypoint_shim()
    assert shim.startswith("#!/bin/sh")
    assert "SECRETS_FILE=" in shim
    assert "set -a" in shim
    assert ". \"$SECRETS_FILE\"" in shim
    assert "set +a" in shim
    assert 'exec "$@"' in shim


def test_entrypoint_shim_has_wait_loop():
    shim = generate_entrypoint_shim()
    assert "seq 1 30" in shim  # 30-second wait
    assert "sleep 1" in shim
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_templates.py -v`
Expected: FAIL — `ImportError: cannot import name 'generate_server_hcl'`.

- [ ] **Step 3: Implement `templates.py`**

Create `packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py`:

```python
"""Generators for Vault HCL configs and the entrypoint shim.

All outputs are deterministic given their inputs — no timestamps, no
hashes. Tests assert byte-level expectations on generated strings.
"""


def generate_server_hcl(*, port: int = 8200) -> str:
    """Vault server config: file storage, single TCP listener, TLS disabled
    (internal Docker network only)."""
    return f"""\
storage "file" {{
  path = "/vault/file"
}}

listener "tcp" {{
  address     = "0.0.0.0:{port}"
  tls_disable = true
}}

ui = false
disable_mlock = true
"""


def generate_agent_hcl(*, vault_address: str, secret_names: list[str]) -> str:
    """Vault Agent config: AppRole auto-auth + single template that renders
    secrets.env with one KEY=value line per declared secret."""
    template_body = []
    for name in secret_names:
        template_body.append(
            f'    {{{{- with secret "secret/data/{name}" }}}}\n'
            f"    {name}={{{{ .Data.data.value }}}}\n"
            "    {{- end }}"
        )
    template_contents = "\n".join(template_body) if template_body else ""

    return f"""\
exit_after_auth = false
pid_file        = "/tmp/vault-agent.pid"

vault {{
  address = "{vault_address}"
}}

auto_auth {{
  method "approle" {{
    config = {{
      role_id_file_path   = "/vault/approle/role_id"
      secret_id_file_path = "/vault/approle/secret_id"
      remove_secret_id_file_after_reading = false
    }}
  }}
  sink "file" {{
    config = {{
      path = "/tmp/vault-token"
    }}
  }}
}}

template {{
  destination = "/shared/secrets.env"
  perms       = "0444"
  contents    = <<-EOT
{template_contents}
  EOT
}}
"""


def generate_policy_hcl(*, secret_names: list[str]) -> str:
    """Vault policy granting `read` on each listed secret's KV v2 data path."""
    paths = []
    for name in secret_names:
        paths.append(
            f'path "secret/data/{name}" {{\n  capabilities = ["read"]\n}}'
        )
    return "\n".join(paths)


def generate_entrypoint_shim() -> str:
    """Shell script that waits for /shared/secrets.env, sources it into env,
    then execs the main process."""
    return """\
#!/bin/sh
# vystak entrypoint shim — waits for Vault Agent to render secrets, then exec
set -e

SECRETS_FILE="/shared/secrets.env"

for i in $(seq 1 30); do
  [ -s "$SECRETS_FILE" ] && break
  sleep 1
done

if [ ! -s "$SECRETS_FILE" ]; then
  echo "vystak: $SECRETS_FILE never populated — Vault Agent unhealthy?" >&2
  exit 1
fi

set -a
. "$SECRETS_FILE"
set +a

exec "$@"
"""
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_templates.py -v`
Expected: PASS (all 9 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py packages/python/vystak-provider-docker/tests/test_templates.py
git commit -m "feat(provider-docker): template generators for Vault HCL + entrypoint shim"
```

---

## Phase 5 — Vault server / init / unseal nodes

### Task 6: `HashiVaultServerNode`

**Files:**
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/hashi_vault.py`
- Test: `packages/python/vystak-provider-docker/tests/test_node_hashi_vault.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/python/vystak-provider-docker/tests/test_node_hashi_vault.py`:

```python
"""Tests for Vault server/init/unseal nodes."""

from unittest.mock import MagicMock, patch

import pytest

from vystak_provider_docker.nodes.hashi_vault import (
    HashiVaultServerNode,
    HashiVaultInitNode,
    HashiVaultUnsealNode,
)


def _fake_docker_client():
    client = MagicMock()
    existing_volume = MagicMock()
    client.volumes.get.return_value = existing_volume
    client.containers.get.side_effect = __import__(
        "docker.errors", fromlist=["NotFound"]
    ).NotFound("not found")
    return client


def test_server_node_starts_container_with_persistent_volume(tmp_path):
    client = _fake_docker_client()
    node = HashiVaultServerNode(
        client=client,
        image="hashicorp/vault:1.17",
        port=8200,
        host_port=None,
    )
    result = node.provision(context={"network": MagicMock(info={"network": MagicMock(name="vystak-net")})})
    client.volumes.create.assert_called_once_with(name="vystak-vault-data")
    client.containers.run.assert_called_once()
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["name"] == "vystak-vault"
    assert kwargs["detach"] is True
    assert kwargs["image"] == "hashicorp/vault:1.17"
    # Volume mount
    volumes = kwargs.get("volumes") or {}
    assert "vystak-vault-data" in volumes
    assert volumes["vystak-vault-data"]["bind"] == "/vault/file"
    assert result.success is True


def test_server_node_reuses_existing_container_if_running():
    client = MagicMock()
    running = MagicMock()
    running.status = "running"
    client.containers.get.return_value = running
    node = HashiVaultServerNode(
        client=client, image="hashicorp/vault:1.17", port=8200, host_port=None
    )
    result = node.provision(
        context={"network": MagicMock(info={"network": MagicMock(name="vystak-net")})}
    )
    client.containers.run.assert_not_called()
    assert result.info["vault_address"] == "http://vystak-vault:8200"
    assert result.success is True


def test_init_node_writes_init_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_vc = MagicMock()
    fake_vc.is_initialized.return_value = False
    from vystak_provider_docker.vault_client import VaultInitResult

    fake_vc.initialize.return_value = VaultInitResult(
        unseal_keys=["k1", "k2", "k3", "k4", "k5"],
        root_token="hvs.xxx",
    )
    node = HashiVaultInitNode(
        vault_client=fake_vc, key_shares=5, key_threshold=3, init_path=tmp_path / ".vystak/vault/init.json"
    )
    result = node.provision(context={})
    init_path = tmp_path / ".vystak/vault/init.json"
    assert init_path.exists()
    import json

    data = json.loads(init_path.read_text())
    assert data["root_token"] == "hvs.xxx"
    assert len(data["unseal_keys_b64"]) == 5
    assert (init_path.stat().st_mode & 0o777) == 0o600
    assert result.info["root_token"] == "hvs.xxx"
    assert result.info["unseal_keys"] == ["k1", "k2", "k3", "k4", "k5"]


def test_init_node_skips_when_already_initialized(tmp_path):
    init_path = tmp_path / ".vystak/vault/init.json"
    init_path.parent.mkdir(parents=True)
    import json

    init_path.write_text(
        json.dumps({"root_token": "existing", "unseal_keys_b64": ["k1", "k2", "k3", "k4", "k5"]})
    )
    init_path.chmod(0o600)
    fake_vc = MagicMock()
    fake_vc.is_initialized.return_value = True
    node = HashiVaultInitNode(
        vault_client=fake_vc, key_shares=5, key_threshold=3, init_path=init_path
    )
    result = node.provision(context={})
    fake_vc.initialize.assert_not_called()
    assert result.info["root_token"] == "existing"


def test_init_node_raises_when_vault_initialized_but_init_json_missing(tmp_path):
    fake_vc = MagicMock()
    fake_vc.is_initialized.return_value = True
    node = HashiVaultInitNode(
        vault_client=fake_vc, key_shares=5, key_threshold=3,
        init_path=tmp_path / "does-not-exist.json",
    )
    with pytest.raises(RuntimeError, match="state mismatch"):
        node.provision(context={})


def test_unseal_node_submits_threshold_keys():
    fake_vc = MagicMock()
    fake_vc.is_sealed.return_value = True
    node = HashiVaultUnsealNode(
        vault_client=fake_vc,
        unseal_keys=["k1", "k2", "k3", "k4", "k5"],
        key_threshold=3,
    )
    result = node.provision(context={})
    fake_vc.unseal.assert_called_once_with(["k1", "k2", "k3"])
    assert result.success is True


def test_unseal_node_skips_when_unsealed():
    fake_vc = MagicMock()
    fake_vc.is_sealed.return_value = False
    node = HashiVaultUnsealNode(
        vault_client=fake_vc, unseal_keys=["k1", "k2", "k3"], key_threshold=3
    )
    result = node.provision(context={})
    fake_vc.unseal.assert_not_called()
    assert result.success is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_hashi_vault.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement the three nodes**

Create `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/hashi_vault.py`:

```python
"""Vault server container + init + unseal provisioning nodes."""

import json
import time
from pathlib import Path

import docker.errors
from vystak.provisioning.node import Provisionable, ProvisionResult


VAULT_CONTAINER_NAME = "vystak-vault"
VAULT_DATA_VOLUME = "vystak-vault-data"


class HashiVaultServerNode(Provisionable):
    """Starts the Vault server container (reuses existing if already running)."""

    def __init__(self, *, client, image: str, port: int, host_port: int | None):
        self._client = client
        self._image = image
        self._port = port
        self._host_port = host_port

    @property
    def name(self) -> str:
        return "hashi-vault:server"

    @property
    def depends_on(self) -> list[str]:
        return ["network"]

    def provision(self, context: dict) -> ProvisionResult:
        # Reuse if already running
        try:
            existing = self._client.containers.get(VAULT_CONTAINER_NAME)
            if existing.status == "running":
                return ProvisionResult(
                    name=self.name,
                    success=True,
                    info={
                        "container_name": VAULT_CONTAINER_NAME,
                        "vault_address": f"http://{VAULT_CONTAINER_NAME}:{self._port}",
                        "reused": True,
                    },
                )
            existing.remove()
        except docker.errors.NotFound:
            pass

        # Ensure data volume
        try:
            self._client.volumes.get(VAULT_DATA_VOLUME)
        except docker.errors.NotFound:
            self._client.volumes.create(name=VAULT_DATA_VOLUME)

        network = context["network"].info["network"]

        ports = {}
        if self._host_port:
            ports[f"{self._port}/tcp"] = self._host_port

        # Generate server config into a tmp host file, mount into container
        # Simpler: pass via CMD with inline config for dev, or bake config
        # into the image. We use a bind-mount of a generated config file.
        config_dir = Path(".vystak") / "vault"
        config_dir.mkdir(parents=True, exist_ok=True)
        from vystak_provider_docker.templates import generate_server_hcl

        (config_dir / "vault.hcl").write_text(generate_server_hcl(port=self._port))

        self._client.containers.run(
            image=self._image,
            name=VAULT_CONTAINER_NAME,
            detach=True,
            command=["vault", "server", "-config=/vault/config/vault.hcl"],
            network=network.name,
            ports=ports,
            volumes={
                VAULT_DATA_VOLUME: {"bind": "/vault/file", "mode": "rw"},
                str(config_dir.absolute()): {"bind": "/vault/config", "mode": "ro"},
            },
            cap_add=["IPC_LOCK"],
            labels={"vystak.vault": "server"},
        )

        # Poll for readiness (Vault listening on its port)
        deadline = time.time() + 30
        while time.time() < deadline:
            container = self._client.containers.get(VAULT_CONTAINER_NAME)
            if container.status == "running":
                break
            time.sleep(0.5)

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "container_name": VAULT_CONTAINER_NAME,
                "vault_address": f"http://{VAULT_CONTAINER_NAME}:{self._port}",
                "reused": False,
            },
        )

    def destroy(self) -> None:
        # Only called on --delete-vault; regular destroy doesn't reach here.
        try:
            container = self._client.containers.get(VAULT_CONTAINER_NAME)
            container.stop()
            container.remove()
        except docker.errors.NotFound:
            pass
        try:
            vol = self._client.volumes.get(VAULT_DATA_VOLUME)
            vol.remove()
        except docker.errors.NotFound:
            pass


class HashiVaultInitNode(Provisionable):
    """Runs vault operator init if not already initialized; persists result
    to .vystak/vault/init.json (chmod 600)."""

    def __init__(
        self,
        *,
        vault_client,
        key_shares: int,
        key_threshold: int,
        init_path: Path,
    ):
        self._vault = vault_client
        self._key_shares = key_shares
        self._key_threshold = key_threshold
        self._init_path = Path(init_path)

    @property
    def name(self) -> str:
        return "hashi-vault:init"

    @property
    def depends_on(self) -> list[str]:
        return ["hashi-vault:server"]

    def provision(self, context: dict) -> ProvisionResult:
        # Wait for Vault to be reachable (sys/init endpoint available)
        deadline = time.time() + 30
        last_err = None
        while time.time() < deadline:
            try:
                already_init = self._vault.is_initialized()
                break
            except Exception as e:
                last_err = e
                time.sleep(1)
        else:
            raise RuntimeError(f"Vault not reachable after 30s: {last_err}")

        if already_init:
            if not self._init_path.exists():
                raise RuntimeError(
                    f"Vault is initialized but {self._init_path} is missing. "
                    f"state mismatch — run 'vystak destroy --delete-vault' and retry."
                )
            data = json.loads(self._init_path.read_text())
            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "root_token": data["root_token"],
                    "unseal_keys": data["unseal_keys_b64"],
                    "already_initialized": True,
                },
            )

        # Run init
        result = self._vault.initialize(
            key_shares=self._key_shares, key_threshold=self._key_threshold
        )

        import datetime

        self._init_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "unseal_keys_b64": result.unseal_keys,
            "root_token": result.root_token,
            "init_time": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
        }
        self._init_path.write_text(json.dumps(payload, indent=2))
        self._init_path.chmod(0o600)

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "root_token": result.root_token,
                "unseal_keys": result.unseal_keys,
                "already_initialized": False,
            },
        )

    def destroy(self) -> None:
        pass  # init.json removal handled by --delete-vault flag in provider


class HashiVaultUnsealNode(Provisionable):
    """Unseals Vault using the first N of threshold unseal keys."""

    def __init__(self, *, vault_client, unseal_keys: list[str], key_threshold: int):
        self._vault = vault_client
        self._keys = unseal_keys
        self._threshold = key_threshold

    @property
    def name(self) -> str:
        return "hashi-vault:unseal"

    @property
    def depends_on(self) -> list[str]:
        return ["hashi-vault:init"]

    def provision(self, context: dict) -> ProvisionResult:
        if not self._vault.is_sealed():
            return ProvisionResult(
                name=self.name, success=True, info={"already_unsealed": True}
            )
        self._vault.unseal(self._keys[: self._threshold])
        return ProvisionResult(name=self.name, success=True, info={"already_unsealed": False})

    def destroy(self) -> None:
        pass
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_hashi_vault.py -v`
Expected: PASS (all 7 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/hashi_vault.py packages/python/vystak-provider-docker/tests/test_node_hashi_vault.py
git commit -m "feat(provider-docker): Vault server/init/unseal provisioning nodes"
```

---

## Phase 6 — Vault post-init setup

### Task 7: `VaultKvSetupNode` — enable KV v2 and AppRole auth

**Files:**
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_kv_setup.py`
- Test: `packages/python/vystak-provider-docker/tests/test_node_vault_kv_setup.py`

- [ ] **Step 1: Write the failing test**

Create `packages/python/vystak-provider-docker/tests/test_node_vault_kv_setup.py`:

```python
from unittest.mock import MagicMock

from vystak_provider_docker.nodes.vault_kv_setup import VaultKvSetupNode


def test_enables_kv_v2_and_approle_auth():
    fake_vc = MagicMock()
    node = VaultKvSetupNode(vault_client=fake_vc)
    result = node.provision(context={})
    fake_vc.enable_kv_v2.assert_called_once_with("secret")
    fake_vc.enable_approle_auth.assert_called_once()
    assert result.success is True


def test_sets_token_before_calls():
    """If a token is passed, the underlying client's token should be set
    before calling enable_*."""
    fake_vc = MagicMock()
    node = VaultKvSetupNode(vault_client=fake_vc, root_token="hvs.xxx")
    node.provision(context={})
    fake_vc.set_token.assert_called_once_with("hvs.xxx")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_vault_kv_setup.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

Create `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_kv_setup.py`:

```python
"""VaultKvSetupNode — enables KV v2 and AppRole auth after unseal."""

from vystak.provisioning.node import Provisionable, ProvisionResult


class VaultKvSetupNode(Provisionable):
    """Idempotently enables KV v2 at secret/ and AppRole auth at auth/approle/."""

    def __init__(self, *, vault_client, root_token: str | None = None):
        self._vault = vault_client
        self._root_token = root_token

    @property
    def name(self) -> str:
        return "hashi-vault:kv-setup"

    @property
    def depends_on(self) -> list[str]:
        return ["hashi-vault:unseal"]

    def provision(self, context: dict) -> ProvisionResult:
        if self._root_token:
            self._vault.set_token(self._root_token)
        self._vault.enable_kv_v2("secret")
        self._vault.enable_approle_auth()
        return ProvisionResult(name=self.name, success=True, info={})

    def destroy(self) -> None:
        pass
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_vault_kv_setup.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_kv_setup.py packages/python/vystak-provider-docker/tests/test_node_vault_kv_setup.py
git commit -m "feat(provider-docker): VaultKvSetupNode enables KV v2 and AppRole auth"
```

---

## Phase 7 — AppRole per principal

### Task 8: `AppRoleNode`

**Files:**
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/approle.py`
- Test: `packages/python/vystak-provider-docker/tests/test_node_approle.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/python/vystak-provider-docker/tests/test_node_approle.py`:

```python
from unittest.mock import MagicMock

from vystak_provider_docker.nodes.approle import AppRoleNode


def test_creates_policy_and_approle():
    fake_vc = MagicMock()
    fake_vc.upsert_approle.return_value = ("role-id-1", "secret-id-1")
    node = AppRoleNode(
        vault_client=fake_vc,
        principal_name="assistant-agent",
        secret_names=["ANTHROPIC_API_KEY"],
    )
    result = node.provision(context={})
    # Policy written with correct HCL
    fake_vc.write_policy.assert_called_once()
    args, kwargs = fake_vc.write_policy.call_args
    assert kwargs.get("name") == "assistant-agent-policy" or args[0] == "assistant-agent-policy"
    policy_hcl = kwargs.get("hcl") or args[1]
    assert 'path "secret/data/ANTHROPIC_API_KEY"' in policy_hcl
    # AppRole created
    fake_vc.upsert_approle.assert_called_once()
    ur_kwargs = fake_vc.upsert_approle.call_args.kwargs
    assert ur_kwargs["role_name"] == "assistant-agent"
    assert ur_kwargs["policies"] == ["assistant-agent-policy"]
    # Result carries creds
    assert result.info["role_id"] == "role-id-1"
    assert result.info["secret_id"] == "secret-id-1"
    assert result.info["policy_name"] == "assistant-agent-policy"


def test_empty_secret_list_still_creates_role():
    fake_vc = MagicMock()
    fake_vc.upsert_approle.return_value = ("r", "s")
    node = AppRoleNode(
        vault_client=fake_vc,
        principal_name="no-secrets-principal",
        secret_names=[],
    )
    result = node.provision(context={})
    fake_vc.write_policy.assert_called_once()
    # Role still created so the principal has an auth identity, just no paths
    assert result.success is True


def test_destroy_removes_approle_and_policy():
    fake_vc = MagicMock()
    node = AppRoleNode(
        vault_client=fake_vc,
        principal_name="assistant-agent",
        secret_names=["ANTHROPIC_API_KEY"],
    )
    node.destroy()
    fake_vc.delete_approle.assert_called_once_with("assistant-agent")
    fake_vc.delete_policy.assert_called_once_with("assistant-agent-policy")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_approle.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

Create `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/approle.py`:

```python
"""AppRoleNode — creates/updates a policy + AppRole for one principal."""

from vystak.provisioning.node import Provisionable, ProvisionResult

from vystak_provider_docker.templates import generate_policy_hcl


class AppRoleNode(Provisionable):
    """One per principal. Writes <principal>-policy, upserts the AppRole,
    returns (role_id, secret_id) in its ProvisionResult.info."""

    def __init__(
        self,
        *,
        vault_client,
        principal_name: str,
        secret_names: list[str],
        token_ttl: str = "1h",
        token_max_ttl: str = "24h",
    ):
        self._vault = vault_client
        self._principal_name = principal_name
        self._secret_names = list(secret_names)
        self._token_ttl = token_ttl
        self._token_max_ttl = token_max_ttl

    @property
    def policy_name(self) -> str:
        return f"{self._principal_name}-policy"

    @property
    def name(self) -> str:
        return f"approle:{self._principal_name}"

    @property
    def depends_on(self) -> list[str]:
        return ["hashi-vault:kv-setup"]

    def provision(self, context: dict) -> ProvisionResult:
        # Write policy
        policy_hcl = generate_policy_hcl(secret_names=self._secret_names)
        self._vault.write_policy(name=self.policy_name, hcl=policy_hcl)

        # Upsert AppRole bound to the policy
        role_id, secret_id = self._vault.upsert_approle(
            role_name=self._principal_name,
            policies=[self.policy_name],
            token_ttl=self._token_ttl,
            token_max_ttl=self._token_max_ttl,
        )

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "policy_name": self.policy_name,
                "role_name": self._principal_name,
                "role_id": role_id,
                "secret_id": secret_id,
                "secret_names": self._secret_names,
            },
        )

    def destroy(self) -> None:
        self._vault.delete_approle(self._principal_name)
        self._vault.delete_policy(self.policy_name)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_approle.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/approle.py packages/python/vystak-provider-docker/tests/test_node_approle.py
git commit -m "feat(provider-docker): AppRoleNode writes per-principal policy + AppRole"
```

---

## Phase 8 — Secret sync against Vault KV

### Task 9: `VaultSecretSyncNode`

**Files:**
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_secret_sync.py`
- Test: `packages/python/vystak-provider-docker/tests/test_node_vault_secret_sync.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/python/vystak-provider-docker/tests/test_node_vault_secret_sync.py`:

```python
from unittest.mock import MagicMock

import pytest

from vystak_provider_docker.nodes.vault_secret_sync import VaultSecretSyncNode


def test_push_if_missing_pushes_absent():
    fake_vc = MagicMock()
    fake_vc.kv_get.return_value = None  # absent
    node = VaultSecretSyncNode(
        vault_client=fake_vc,
        declared_secrets=["ANTHROPIC_API_KEY"],
        env_values={"ANTHROPIC_API_KEY": "sk-ant-xxx"},
    )
    result = node.provision(context={})
    fake_vc.kv_put.assert_called_once_with("ANTHROPIC_API_KEY", "sk-ant-xxx")
    assert result.info["pushed"] == ["ANTHROPIC_API_KEY"]
    assert result.info["skipped"] == []
    assert result.info["missing"] == []


def test_push_if_missing_skips_present():
    fake_vc = MagicMock()
    fake_vc.kv_get.return_value = "preserved"
    node = VaultSecretSyncNode(
        vault_client=fake_vc,
        declared_secrets=["ANTHROPIC_API_KEY"],
        env_values={"ANTHROPIC_API_KEY": "different"},
    )
    result = node.provision(context={})
    fake_vc.kv_put.assert_not_called()
    assert result.info["skipped"] == ["ANTHROPIC_API_KEY"]


def test_force_overwrites():
    fake_vc = MagicMock()
    fake_vc.kv_get.return_value = "old"
    node = VaultSecretSyncNode(
        vault_client=fake_vc,
        declared_secrets=["ANTHROPIC_API_KEY"],
        env_values={"ANTHROPIC_API_KEY": "new"},
        force=True,
    )
    result = node.provision(context={})
    fake_vc.kv_put.assert_called_once_with("ANTHROPIC_API_KEY", "new")
    assert result.info["pushed"] == ["ANTHROPIC_API_KEY"]


def test_missing_aborts_by_default():
    fake_vc = MagicMock()
    fake_vc.kv_get.return_value = None
    node = VaultSecretSyncNode(
        vault_client=fake_vc,
        declared_secrets=["ABSENT"],
        env_values={},
    )
    with pytest.raises(RuntimeError, match="ABSENT"):
        node.provision(context={})


def test_missing_with_allow_missing():
    fake_vc = MagicMock()
    fake_vc.kv_get.return_value = None
    node = VaultSecretSyncNode(
        vault_client=fake_vc,
        declared_secrets=["ABSENT"],
        env_values={},
        allow_missing=True,
    )
    result = node.provision(context={})
    assert result.info["missing"] == ["ABSENT"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_vault_secret_sync.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

Create `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_secret_sync.py`:

```python
"""VaultSecretSyncNode — push-if-missing of .env values into Vault KV v2."""

from vystak.provisioning.node import Provisionable, ProvisionResult


class VaultSecretSyncNode(Provisionable):
    """Hashi-side analog of v1's SecretSyncNode. Same semantics:
       - If KV has the secret, skip (unless force).
       - If missing from both .env and KV, abort (unless allow_missing)."""

    def __init__(
        self,
        *,
        vault_client,
        declared_secrets: list[str],
        env_values: dict[str, str],
        force: bool = False,
        allow_missing: bool = False,
    ):
        self._vault = vault_client
        self._declared = list(declared_secrets)
        self._env = dict(env_values)
        self._force = force
        self._allow_missing = allow_missing

    @property
    def name(self) -> str:
        return "hashi-vault:secret-sync"

    @property
    def depends_on(self) -> list[str]:
        return ["hashi-vault:kv-setup"]

    def provision(self, context: dict) -> ProvisionResult:
        pushed: list[str] = []
        skipped: list[str] = []
        missing: list[str] = []

        for name in self._declared:
            existing = self._vault.kv_get(name)
            if existing is not None and not self._force:
                skipped.append(name)
                continue
            if name in self._env:
                self._vault.kv_put(name, self._env[name])
                pushed.append(name)
            else:
                missing.append(name)

        if missing and not self._allow_missing:
            raise RuntimeError(
                f"Secrets missing from both .env and vault: {', '.join(missing)}. "
                f"Set in .env, run 'vystak secrets set <name>=<value>', or pass --allow-missing."
            )

        return ProvisionResult(
            name=self.name,
            success=True,
            info={"pushed": pushed, "skipped": skipped, "missing": missing},
        )

    def destroy(self) -> None:
        pass  # values preserved by design
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_vault_secret_sync.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_secret_sync.py packages/python/vystak-provider-docker/tests/test_node_vault_secret_sync.py
git commit -m "feat(provider-docker): VaultSecretSyncNode with push-if-missing and --force"
```

---

## Phase 9 — AppRole credential mount volume

### Task 10: `AppRoleCredentialsNode` — write role_id + secret_id to volume

**Files:**
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/approle_credentials.py`
- Test: `packages/python/vystak-provider-docker/tests/test_node_approle_credentials.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/python/vystak-provider-docker/tests/test_node_approle_credentials.py`:

```python
from unittest.mock import MagicMock

import pytest

from vystak_provider_docker.nodes.approle_credentials import AppRoleCredentialsNode


def test_creates_volume_and_writes_files_via_throwaway_container():
    client = MagicMock()
    existing_vol = MagicMock()
    import docker.errors

    client.volumes.get.side_effect = docker.errors.NotFound("not found")

    node = AppRoleCredentialsNode(
        client=client,
        principal_name="assistant-agent",
    )
    context = {
        "approle:assistant-agent": MagicMock(
            info={"role_id": "rid-1", "secret_id": "sid-1"}
        ),
    }
    result = node.provision(context=context)
    client.volumes.create.assert_called_once_with(name="vystak-assistant-agent-approle")
    # A throwaway container is used to write files into the named volume
    client.containers.run.assert_called_once()
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["remove"] is True
    assert kwargs["image"] == "alpine:3.19"
    volumes = kwargs.get("volumes") or {}
    assert "vystak-assistant-agent-approle" in volumes
    cmd = kwargs["command"]
    # The command writes both role_id and secret_id into the volume
    assert "rid-1" in " ".join(cmd) if isinstance(cmd, list) else "rid-1" in cmd
    assert "sid-1" in " ".join(cmd) if isinstance(cmd, list) else "sid-1" in cmd
    assert result.success is True
    assert result.info["volume_name"] == "vystak-assistant-agent-approle"


def test_reuses_existing_volume():
    client = MagicMock()
    node = AppRoleCredentialsNode(client=client, principal_name="assistant-agent")
    context = {
        "approle:assistant-agent": MagicMock(
            info={"role_id": "rid-1", "secret_id": "sid-1"}
        ),
    }
    node.provision(context=context)
    client.volumes.create.assert_not_called()


def test_destroy_removes_volume():
    client = MagicMock()
    node = AppRoleCredentialsNode(client=client, principal_name="assistant-agent")
    node.destroy()
    client.volumes.get.assert_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_approle_credentials.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

Create `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/approle_credentials.py`:

```python
"""AppRoleCredentialsNode — writes role_id + secret_id files into a
named Docker volume so the Vault Agent sidecar can read them.

We write via a throwaway alpine container because Docker volumes
aren't directly writable from the host without knowing their
filesystem path.
"""

import shlex

import docker.errors
from vystak.provisioning.node import Provisionable, ProvisionResult


class AppRoleCredentialsNode(Provisionable):
    """One per principal. Depends on AppRoleNode having produced the creds."""

    def __init__(self, *, client, principal_name: str):
        self._client = client
        self._principal_name = principal_name

    @property
    def volume_name(self) -> str:
        return f"vystak-{self._principal_name}-approle"

    @property
    def name(self) -> str:
        return f"approle-creds:{self._principal_name}"

    @property
    def depends_on(self) -> list[str]:
        return [f"approle:{self._principal_name}"]

    def provision(self, context: dict) -> ProvisionResult:
        approle_info = context[f"approle:{self._principal_name}"].info
        role_id = approle_info["role_id"]
        secret_id = approle_info["secret_id"]

        # Ensure the volume exists
        try:
            self._client.volumes.get(self.volume_name)
        except docker.errors.NotFound:
            self._client.volumes.create(name=self.volume_name)

        # Write the two credential files via a throwaway container. Use
        # printf to avoid quoting issues with arbitrary credential content;
        # chmod 400 after write.
        script = (
            f"printf %s {shlex.quote(role_id)} > /target/role_id && "
            f"chmod 400 /target/role_id && "
            f"printf %s {shlex.quote(secret_id)} > /target/secret_id && "
            f"chmod 400 /target/secret_id"
        )
        self._client.containers.run(
            image="alpine:3.19",
            command=["sh", "-c", script],
            volumes={self.volume_name: {"bind": "/target", "mode": "rw"}},
            remove=True,
        )

        return ProvisionResult(
            name=self.name,
            success=True,
            info={"volume_name": self.volume_name},
        )

    def destroy(self) -> None:
        try:
            vol = self._client.volumes.get(self.volume_name)
            vol.remove()
        except docker.errors.NotFound:
            pass
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_approle_credentials.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/approle_credentials.py packages/python/vystak-provider-docker/tests/test_node_approle_credentials.py
git commit -m "feat(provider-docker): AppRoleCredentialsNode writes role/secret IDs to named volume"
```

---

## Phase 10 — Vault Agent sidecar container

### Task 11: `VaultAgentSidecarNode`

**Files:**
- Create: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_agent.py`
- Test: `packages/python/vystak-provider-docker/tests/test_node_vault_agent.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/python/vystak-provider-docker/tests/test_node_vault_agent.py`:

```python
from unittest.mock import MagicMock

import docker.errors

from vystak_provider_docker.nodes.vault_agent import VaultAgentSidecarNode


def test_starts_vault_agent_container_with_agent_config():
    client = MagicMock()
    client.containers.get.side_effect = docker.errors.NotFound("not found")
    node = VaultAgentSidecarNode(
        client=client,
        principal_name="assistant-agent",
        image="hashicorp/vault:1.17",
        secret_names=["ANTHROPIC_API_KEY"],
        vault_address="http://vystak-vault:8200",
    )
    context = {
        "network": MagicMock(info={"network": MagicMock(name="vystak-net")}),
        "approle-creds:assistant-agent": MagicMock(
            info={"volume_name": "vystak-assistant-agent-approle"}
        ),
    }
    result = node.provision(context=context)
    client.containers.run.assert_called_once()
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["name"] == "vystak-assistant-agent-vault-agent"
    assert kwargs["detach"] is True
    # Three volumes: approle (ro), secrets (rw to be read by main container), config (ro)
    volumes = kwargs["volumes"]
    assert any(
        v["bind"] == "/vault/approle" and v["mode"] == "ro"
        for v in volumes.values()
    )
    assert "vystak-assistant-agent-secrets" in volumes
    # Command starts vault agent
    cmd = kwargs["command"]
    assert "agent" in cmd
    assert "-config=" in " ".join(cmd)
    assert result.info["secrets_volume_name"] == "vystak-assistant-agent-secrets"


def test_restarts_if_container_exists():
    client = MagicMock()
    existing = MagicMock()
    client.containers.get.return_value = existing
    node = VaultAgentSidecarNode(
        client=client,
        principal_name="assistant-agent",
        image="hashicorp/vault:1.17",
        secret_names=["KEY"],
        vault_address="http://vystak-vault:8200",
    )
    context = {
        "network": MagicMock(info={"network": MagicMock(name="vystak-net")}),
        "approle-creds:assistant-agent": MagicMock(
            info={"volume_name": "vystak-assistant-agent-approle"}
        ),
    }
    node.provision(context=context)
    existing.stop.assert_called_once()
    existing.remove.assert_called_once()
    client.containers.run.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_vault_agent.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

Create `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_agent.py`:

```python
"""VaultAgentSidecarNode — one per principal. Vault Agent container that
authenticates via AppRole and templates secrets.env into a per-principal
shared volume."""

from pathlib import Path

import docker.errors
from vystak.provisioning.node import Provisionable, ProvisionResult

from vystak_provider_docker.templates import generate_agent_hcl


class VaultAgentSidecarNode(Provisionable):
    """Per-principal Vault Agent. Renders /shared/secrets.env continuously."""

    def __init__(
        self,
        *,
        client,
        principal_name: str,
        image: str,
        secret_names: list[str],
        vault_address: str,
    ):
        self._client = client
        self._principal_name = principal_name
        self._image = image
        self._secret_names = list(secret_names)
        self._vault_address = vault_address

    @property
    def container_name(self) -> str:
        return f"vystak-{self._principal_name}-vault-agent"

    @property
    def secrets_volume_name(self) -> str:
        return f"vystak-{self._principal_name}-secrets"

    @property
    def name(self) -> str:
        return f"vault-agent:{self._principal_name}"

    @property
    def depends_on(self) -> list[str]:
        return [
            f"approle-creds:{self._principal_name}",
            "hashi-vault:secret-sync",
        ]

    def provision(self, context: dict) -> ProvisionResult:
        network = context["network"].info["network"]
        approle_volume = context[f"approle-creds:{self._principal_name}"].info[
            "volume_name"
        ]

        # Ensure the secrets volume exists (main container will mount it too)
        try:
            self._client.volumes.get(self.secrets_volume_name)
        except docker.errors.NotFound:
            self._client.volumes.create(name=self.secrets_volume_name)

        # Write the agent config to a bind-mounted dir so Vault Agent can read it
        config_dir = Path(".vystak") / "vault-agents" / self._principal_name
        config_dir.mkdir(parents=True, exist_ok=True)
        agent_hcl = generate_agent_hcl(
            vault_address=self._vault_address, secret_names=self._secret_names
        )
        (config_dir / "agent.hcl").write_text(agent_hcl)

        # Stop existing sidecar
        try:
            existing = self._client.containers.get(self.container_name)
            existing.stop()
            existing.remove()
        except docker.errors.NotFound:
            pass

        self._client.containers.run(
            image=self._image,
            name=self.container_name,
            command=["vault", "agent", "-config=/vault/config/agent.hcl"],
            detach=True,
            network=network.name,
            volumes={
                approle_volume: {"bind": "/vault/approle", "mode": "ro"},
                self.secrets_volume_name: {"bind": "/shared", "mode": "rw"},
                str(config_dir.absolute()): {"bind": "/vault/config", "mode": "ro"},
            },
            cap_add=["IPC_LOCK"],
            labels={
                "vystak.vault-agent": self._principal_name,
            },
        )

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "container_name": self.container_name,
                "secrets_volume_name": self.secrets_volume_name,
            },
        )

    def destroy(self) -> None:
        try:
            c = self._client.containers.get(self.container_name)
            c.stop()
            c.remove()
        except docker.errors.NotFound:
            pass
        try:
            vol = self._client.volumes.get(self.secrets_volume_name)
            vol.remove()
        except docker.errors.NotFound:
            pass
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_node_vault_agent.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/vault_agent.py packages/python/vystak-provider-docker/tests/test_node_vault_agent.py
git commit -m "feat(provider-docker): VaultAgentSidecarNode runs Vault Agent per principal"
```

---

## Phase 11 — Entrypoint shim injection in main containers

### Task 12: Inject shim into `DockerAgentNode` when vault context is set

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py`
- Test: extend `packages/python/vystak-provider-docker/tests/test_nodes.py` OR create `test_agent_vault_injection.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/python/vystak-provider-docker/tests/test_agent_vault_injection.py`:

```python
"""Tests that DockerAgentNode injects entrypoint shim + /shared volume
when vault context is provided."""

from unittest.mock import MagicMock, patch
from pathlib import Path

from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret

from vystak_provider_docker.nodes.agent import DockerAgentNode


def _agent_fixture():
    docker_p = Provider(name="docker", type="docker")
    platform = Platform(name="local", type="docker", provider=docker_p)
    anthropic = Provider(name="anthropic", type="anthropic")
    return Agent(
        name="assistant",
        model=Model(name="m", provider=anthropic, model_name="claude-sonnet-4-20250514"),
        secrets=[Secret(name="ANTHROPIC_API_KEY")],
        platform=platform,
    )


def test_no_vault_context_no_shim(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    import docker.errors

    client.containers.get.side_effect = docker.errors.NotFound("nope")
    from vystak.providers.base import GeneratedCode, DeployPlan

    gc = GeneratedCode(
        files={"server.py": "print('hi')", "requirements.txt": ""},
        entrypoint="server.py",
    )
    node = DockerAgentNode(
        client=client,
        agent=_agent_fixture(),
        generated_code=gc,
        plan=DeployPlan(agent_name="assistant", current_hash=None, target_hash="h"),
    )
    with patch("vystak_provider_docker.nodes.agent.shutil"), patch(
        "vystak_provider_docker.nodes.agent.vystak"
    ), patch("vystak_provider_docker.nodes.agent.vystak_transport_http"), patch(
        "vystak_provider_docker.nodes.agent.vystak_transport_nats"
    ):
        node.provision(
            context={"network": MagicMock(info={"network": MagicMock(name="n")})}
        )
    dockerfile = (tmp_path / ".vystak" / "assistant" / "Dockerfile").read_text()
    assert "ENTRYPOINT" not in dockerfile  # legacy path uses CMD only
    assert "entrypoint-shim" not in dockerfile


def test_vault_context_injects_shim_and_entrypoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    import docker.errors

    client.containers.get.side_effect = docker.errors.NotFound("nope")
    from vystak.providers.base import GeneratedCode, DeployPlan

    gc = GeneratedCode(
        files={"server.py": "print('hi')", "requirements.txt": ""},
        entrypoint="server.py",
    )
    node = DockerAgentNode(
        client=client,
        agent=_agent_fixture(),
        generated_code=gc,
        plan=DeployPlan(agent_name="assistant", current_hash=None, target_hash="h"),
    )
    node.set_vault_context(secrets_volume_name="vystak-assistant-secrets")
    with patch("vystak_provider_docker.nodes.agent.shutil"), patch(
        "vystak_provider_docker.nodes.agent.vystak"
    ), patch("vystak_provider_docker.nodes.agent.vystak_transport_http"), patch(
        "vystak_provider_docker.nodes.agent.vystak_transport_nats"
    ):
        node.provision(
            context={"network": MagicMock(info={"network": MagicMock(name="n")})}
        )
    build_dir = tmp_path / ".vystak" / "assistant"
    dockerfile = (build_dir / "Dockerfile").read_text()
    shim_path = build_dir / "entrypoint-shim.sh"
    assert shim_path.exists()
    assert 'ENTRYPOINT ["/vystak/entrypoint-shim.sh"]' in dockerfile
    assert 'CMD ["python", "server.py"]' in dockerfile
    # Check container run was passed the /shared volume mount
    kwargs = client.containers.run.call_args.kwargs
    volumes = kwargs["volumes"]
    assert "vystak-assistant-secrets" in volumes
    assert volumes["vystak-assistant-secrets"]["bind"] == "/shared"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_agent_vault_injection.py -v`
Expected: FAIL — `set_vault_context` not defined.

- [ ] **Step 3: Modify `nodes/agent.py`**

In `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py`:

Add method after `__init__`:

```python
    def set_vault_context(self, *, secrets_volume_name: str) -> None:
        """Declare the per-principal secrets volume. Triggers entrypoint-shim
        injection + /shared mount during provision()."""
        self._vault_secrets_volume = secrets_volume_name
```

And initialize in `__init__`:

```python
        self._vault_secrets_volume: str | None = None
```

In `provision()`, modify the Dockerfile building section:

```python
            # Build Dockerfile (existing code up to the CMD line)
            dockerfile_content = (
                "FROM python:3.11-slim\n"
                "WORKDIR /app\n"
                f"{node_install}"
                f"{mcp_installs}"
                "COPY requirements.txt .\n"
                "RUN pip install --no-cache-dir -r requirements.txt\n"
                "COPY . .\n"
            )
            if self._vault_secrets_volume:
                from vystak_provider_docker.templates import generate_entrypoint_shim

                (build_dir / "entrypoint-shim.sh").write_text(generate_entrypoint_shim())
                dockerfile_content += (
                    "COPY entrypoint-shim.sh /vystak/entrypoint-shim.sh\n"
                    "RUN chmod +x /vystak/entrypoint-shim.sh\n"
                    'ENTRYPOINT ["/vystak/entrypoint-shim.sh"]\n'
                )
            dockerfile_content += f'CMD ["python", "{self._generated_code.entrypoint}"]\n'
            (build_dir / "Dockerfile").write_text(dockerfile_content)
```

In `provision()` where `containers.run` is called, add the volume mount:

```python
            volumes = {}
            if self._vault_secrets_volume:
                volumes[self._vault_secrets_volume] = {"bind": "/shared", "mode": "ro"}

            self._client.containers.run(
                image=image_tag,
                name=container_name,
                detach=True,
                environment=env_vars,
                volumes=volumes,
                # ... existing ports/network/labels kwargs
            )
```

(Preserve all existing kwargs; just add `volumes` to the `run` call.)

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_agent_vault_injection.py -v`
Expected: PASS.

Also run existing tests to catch regressions:

Run: `uv run pytest packages/python/vystak-provider-docker/tests/ -v -k "not integration"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py packages/python/vystak-provider-docker/tests/test_agent_vault_injection.py
git commit -m "feat(provider-docker): DockerAgentNode injects entrypoint shim + /shared volume on vault context"
```

---

### Task 13: Same shim injection for `DockerChannelNode`

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/channel.py`
- Test: extend `packages/python/vystak-provider-docker/tests/test_agent_vault_injection.py` (same file, mirror test)

- [ ] **Step 1: Write the failing test**

Append to `packages/python/vystak-provider-docker/tests/test_agent_vault_injection.py`:

```python
def test_channel_node_injects_shim(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from vystak.schema.channel import Channel
    from vystak.schema.common import ChannelType
    from vystak_provider_docker.nodes.channel import DockerChannelNode
    from vystak.providers.base import GeneratedCode

    client = MagicMock()
    import docker.errors

    client.containers.get.side_effect = docker.errors.NotFound("nope")
    docker_p = Provider(name="docker", type="docker")
    platform = Platform(name="local", type="docker", provider=docker_p)
    channel = Channel(
        name="chat",
        type=ChannelType.CHAT,
        platform=platform,
        config={"port": 8080},
    )
    gc = GeneratedCode(
        files={"server.py": "print('hi')", "requirements.txt": ""},
        entrypoint="server.py",
    )
    node = DockerChannelNode(client=client, channel=channel, generated_code=gc, target_hash="h")
    node.set_vault_context(secrets_volume_name="vystak-chat-secrets")
    with patch("vystak_provider_docker.nodes.channel.shutil"), patch(
        "vystak_provider_docker.nodes.channel.vystak"
    ), patch("vystak_provider_docker.nodes.channel.vystak_transport_http"), patch(
        "vystak_provider_docker.nodes.channel.vystak_transport_nats"
    ):
        node.provision(
            context={"network": MagicMock(info={"network": MagicMock(name="n")})}
        )
    build_dir = tmp_path / ".vystak" / "channels" / "chat"
    dockerfile = (build_dir / "Dockerfile").read_text()
    assert 'ENTRYPOINT ["/vystak/entrypoint-shim.sh"]' in dockerfile
    assert (build_dir / "entrypoint-shim.sh").exists()
    kwargs = client.containers.run.call_args.kwargs
    assert "vystak-chat-secrets" in kwargs["volumes"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_agent_vault_injection.py::test_channel_node_injects_shim -v`
Expected: FAIL — `set_vault_context` not on channel node.

- [ ] **Step 3: Apply the same pattern to `nodes/channel.py`**

Mirror the Task 12 changes in `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/channel.py`:
- Add `_vault_secrets_volume: str | None = None` to `__init__`
- Add `set_vault_context(*, secrets_volume_name)` method
- Conditionally emit shim + ENTRYPOINT into the Dockerfile
- Add the `/shared` volume mount in `containers.run()`

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_agent_vault_injection.py -v`
Expected: PASS (both agent and channel tests).

Also: `uv run pytest packages/python/vystak-provider-docker/tests/ -v`
Expected: PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/channel.py packages/python/vystak-provider-docker/tests/test_agent_vault_injection.py
git commit -m "feat(provider-docker): DockerChannelNode mirrors shim injection on vault context"
```

---

## Phase 12 — Nodes export + provider graph wiring

### Task 14: Export new nodes from `nodes/__init__.py`

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/__init__.py`

- [ ] **Step 1: Add imports + `__all__` entries**

```python
from vystak_provider_docker.nodes.hashi_vault import (
    HashiVaultServerNode,
    HashiVaultInitNode,
    HashiVaultUnsealNode,
)
from vystak_provider_docker.nodes.vault_kv_setup import VaultKvSetupNode
from vystak_provider_docker.nodes.approle import AppRoleNode
from vystak_provider_docker.nodes.vault_secret_sync import VaultSecretSyncNode
from vystak_provider_docker.nodes.approle_credentials import AppRoleCredentialsNode
from vystak_provider_docker.nodes.vault_agent import VaultAgentSidecarNode

__all__ = [
    # existing exports
    "HashiVaultServerNode",
    "HashiVaultInitNode",
    "HashiVaultUnsealNode",
    "VaultKvSetupNode",
    "AppRoleNode",
    "VaultSecretSyncNode",
    "AppRoleCredentialsNode",
    "VaultAgentSidecarNode",
]
```

- [ ] **Step 2: Confirm imports work**

Run: `uv run python -c "from vystak_provider_docker.nodes import HashiVaultServerNode, VaultAgentSidecarNode; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/__init__.py
git commit -m "feat(provider-docker): export new Vault nodes"
```

---

### Task 15: `DockerProvider` — type-aware plan rejection + vault subgraph builder

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py`
- Test: `packages/python/vystak-provider-docker/tests/test_provider.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `packages/python/vystak-provider-docker/tests/test_provider.py`:

```python
def test_docker_plan_rejects_key_vault_type(make_agent_fixture):
    """Azure KV type on a Docker deploy remains rejected (v1 behavior)."""
    from vystak_provider_docker.provider import DockerProvider
    from vystak.schema.vault import Vault
    from vystak.schema.common import VaultType, VaultMode
    from vystak.schema.provider import Provider

    provider = DockerProvider()
    provider.set_vault(
        Vault(
            name="v",
            provider=Provider(name="azure", type="azure"),
            type=VaultType.KEY_VAULT,
            mode=VaultMode.DEPLOY,
            config={"vault_name": "v"},
        )
    )
    import pytest

    with pytest.raises(ValueError, match="Azure Key Vault"):
        provider.plan(make_agent_fixture())


def test_docker_plan_accepts_hashi_vault_type(make_agent_fixture):
    from vystak_provider_docker.provider import DockerProvider
    from vystak.schema.vault import Vault
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
    # Should NOT raise; plan proceeds (may return unchanged plan)
    plan = provider.plan(make_agent_fixture())
    assert plan is not None


def test_docker_provider_builds_vault_subgraph():
    """Smoke: with Vault declared, the provider's graph contains the full
    Vault subgraph (server/init/unseal/kv-setup/secret-sync/approle/
    approle-creds/vault-agent nodes) in topologically valid order."""
    # Test is structural — inspect graph nodes, mock Docker client + hvac
    ...
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_provider.py -v -k "rejects_key_vault or accepts_hashi"`
Expected: FAIL — plan rejects any Vault.

- [ ] **Step 3: Update `plan()` and add `_add_vault_nodes()`**

In `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py`:

Change the `plan()` rejection check:

```python
    def plan(self, agent, current_hash=None):
        if getattr(self, "_vault", None):
            from vystak.schema.common import VaultType

            if self._vault.type is VaultType.KEY_VAULT:
                raise ValueError(
                    "DockerProvider does not support Azure Key Vault. "
                    "Use Vault(type='vault', provider=docker) for HashiCorp Vault, "
                    "or deploy to Azure for Key Vault support."
                )
            # type=VAULT is handled by the apply graph; no plan-time rejection.
        # ... existing plan logic (compute hash, etc.) ...
```

Add setter methods on `DockerProvider` (mirror `AzureProvider`):

```python
    def set_env_values(self, values: dict[str, str]) -> None:
        self._env_values = dict(values)

    def set_force_sync(self, flag: bool) -> None:
        self._force_sync = bool(flag)

    def set_allow_missing(self, flag: bool) -> None:
        self._allow_missing = bool(flag)
```

Add `_add_vault_nodes()`:

```python
    def _add_vault_nodes(self, graph) -> dict:
        """Attach Vault subgraph. Returns {principal_name → secrets_volume_name}
        so the caller can wire main-container vault contexts."""
        from pathlib import Path

        from vystak_provider_docker.nodes import (
            HashiVaultServerNode,
            HashiVaultInitNode,
            HashiVaultUnsealNode,
            VaultKvSetupNode,
            AppRoleNode,
            VaultSecretSyncNode,
            AppRoleCredentialsNode,
            VaultAgentSidecarNode,
        )
        from vystak_provider_docker.vault_client import VaultClient

        cfg = self._vault.config or {}
        image = cfg.get("image", "hashicorp/vault:1.17")
        port = cfg.get("port", 8200)
        host_port = cfg.get("host_port")
        key_shares = cfg.get("seal_key_shares", 5)
        key_threshold = cfg.get("seal_key_threshold", 3)
        vault_address = f"http://vystak-vault:{port}"
        init_path = Path(".vystak/vault/init.json")

        # Server
        server = HashiVaultServerNode(
            client=self._client, image=image, port=port, host_port=host_port
        )
        graph.add(server)

        # Vault client (token set after init)
        vault_client = VaultClient(vault_address)

        # Init
        init_node = HashiVaultInitNode(
            vault_client=vault_client,
            key_shares=key_shares,
            key_threshold=key_threshold,
            init_path=init_path,
        )
        graph.add(init_node)
        graph.add_dependency(init_node.name, server.name)

        # Unseal — keys come from init result via closure-style lookup.
        # Since unseal keys only known at run time, we pass the init result
        # via context lookup by letting the unseal node accept a callable.
        # Simpler: construct with keys=None, and have it read from context.
        unseal_node = _LateBoundUnsealNode(
            vault_client=vault_client,
            init_node_name=init_node.name,
            key_threshold=key_threshold,
        )
        graph.add(unseal_node)
        graph.add_dependency(unseal_node.name, init_node.name)

        # KV v2 + approle-auth enable
        kv_setup = _LateBoundKvSetupNode(
            vault_client=vault_client,
            init_node_name=init_node.name,
        )
        graph.add(kv_setup)
        graph.add_dependency(kv_setup.name, unseal_node.name)

        # Collect all principal+secrets pairs from the agent tree
        principals: dict[str, list[str]] = {}
        agent = self._agent
        if agent and agent.secrets:
            principals[f"{agent.name}-agent"] = [s.name for s in agent.secrets]
        if agent and agent.workspace and agent.workspace.secrets:
            principals[f"{agent.name}-workspace"] = [
                s.name for s in agent.workspace.secrets
            ]

        # Secret sync
        all_declared: list[str] = []
        for names in principals.values():
            all_declared.extend(names)
        sync = VaultSecretSyncNode(
            vault_client=vault_client,
            declared_secrets=all_declared,
            env_values=getattr(self, "_env_values", {}),
            force=getattr(self, "_force_sync", False),
            allow_missing=getattr(self, "_allow_missing", False),
        )
        graph.add(sync)
        graph.add_dependency(sync.name, kv_setup.name)

        # Per-principal approle + credentials + agent sidecar
        result_map: dict[str, str] = {}
        for principal_name, secret_names in principals.items():
            approle = AppRoleNode(
                vault_client=vault_client,
                principal_name=principal_name,
                secret_names=secret_names,
            )
            graph.add(approle)
            graph.add_dependency(approle.name, kv_setup.name)

            creds = AppRoleCredentialsNode(
                client=self._client, principal_name=principal_name
            )
            graph.add(creds)
            graph.add_dependency(creds.name, approle.name)

            sidecar = VaultAgentSidecarNode(
                client=self._client,
                principal_name=principal_name,
                image=image,
                secret_names=secret_names,
                vault_address=vault_address,
            )
            graph.add(sidecar)
            graph.add_dependency(sidecar.name, creds.name)
            graph.add_dependency(sidecar.name, sync.name)

            result_map[principal_name] = sidecar.secrets_volume_name

        return result_map
```

And the two late-bound node wrappers (read from context at provision time):

```python
from vystak.provisioning.node import Provisionable, ProvisionResult


class _LateBoundUnsealNode(Provisionable):
    def __init__(self, *, vault_client, init_node_name: str, key_threshold: int):
        from vystak_provider_docker.nodes.hashi_vault import HashiVaultUnsealNode  # noqa

        self._vault = vault_client
        self._init_node_name = init_node_name
        self._threshold = key_threshold

    @property
    def name(self) -> str:
        return "hashi-vault:unseal"

    @property
    def depends_on(self) -> list[str]:
        return [self._init_node_name]

    def provision(self, context: dict) -> ProvisionResult:
        init_info = context[self._init_node_name].info
        keys = init_info["unseal_keys"][: self._threshold]
        if self._vault.is_sealed():
            self._vault.unseal(keys)
        return ProvisionResult(name=self.name, success=True, info={})

    def destroy(self) -> None:
        pass


class _LateBoundKvSetupNode(Provisionable):
    def __init__(self, *, vault_client, init_node_name: str):
        self._vault = vault_client
        self._init_node_name = init_node_name

    @property
    def name(self) -> str:
        return "hashi-vault:kv-setup"

    @property
    def depends_on(self) -> list[str]:
        return ["hashi-vault:unseal"]

    def provision(self, context: dict) -> ProvisionResult:
        init_info = context[self._init_node_name].info
        self._vault.set_token(init_info["root_token"])
        self._vault.enable_kv_v2("secret")
        self._vault.enable_approle_auth()
        return ProvisionResult(name=self.name, success=True, info={})

    def destroy(self) -> None:
        pass
```

In `apply()`, after adding the Network node and before adding the Agent node:

```python
            vault_volume_map: dict[str, str] = {}
            if getattr(self, "_vault", None):
                from vystak.schema.common import VaultType

                if self._vault.type is VaultType.VAULT:
                    vault_volume_map = self._add_vault_nodes(graph)

            # ... existing code continues ...

            # Agent container — thread vault context
            agent_node = DockerAgentNode(
                self._client,
                self._agent,
                self._generated_code,
                plan,
                peer_routes_json=peer_routes if peer_routes is not None else "{}",
                extra_env=extra_env,
            )
            agent_principal = f"{self._agent.name}-agent"
            if agent_principal in vault_volume_map:
                agent_node.set_vault_context(
                    secrets_volume_name=vault_volume_map[agent_principal]
                )
            graph.add(agent_node)
            # Main container depends on its sidecar being up so /shared has contents
            if agent_principal in vault_volume_map:
                graph.add_dependency(
                    agent_node.name, f"vault-agent:{agent_principal}"
                )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_provider.py -v`
Expected: PASS.

Run: `uv run pytest packages/python/vystak-provider-docker/tests/ -v -k "not integration"`
Expected: PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py packages/python/vystak-provider-docker/tests/test_provider.py
git commit -m "feat(provider-docker): type-aware Vault rejection + _add_vault_nodes subgraph"
```

---

## Phase 13 — CLI: backend dispatch

### Task 16: `vystak secrets` dispatches by `Vault.type`

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py`
- Test: extend `packages/python/vystak-cli/tests/test_secrets_command.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/python/vystak-cli/tests/test_secrets_command.py`:

```python
VAULT_FIXTURE_YAML = """\
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
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: assistant
    model: sonnet
    secrets: [{name: ANTHROPIC_API_KEY}]
    platform: local
"""


def test_list_dispatches_to_vault_backend(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(VAULT_FIXTURE_YAML)
    runner = CliRunner()
    with patch("vystak_cli.commands.secrets._vault_list_names", return_value=["FOO"]) as mock_list:
        result = runner.invoke(secrets, ["list", "--file", str(config)])
    assert result.exit_code == 0
    mock_list.assert_called_once()


def test_push_dispatches_to_vault_backend(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(VAULT_FIXTURE_YAML)
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-value\n")
    runner = CliRunner()
    with patch("vystak_cli.commands.secrets._make_vault_client") as mock_vc:
        fake = MagicMock()
        fake.kv_get.return_value = None
        mock_vc.return_value = fake
        result = runner.invoke(secrets, ["push", "--file", str(config), "--env-file", str(env)])
    assert result.exit_code == 0
    fake.kv_put.assert_called_once_with("ANTHROPIC_API_KEY", "sk-value")


def test_list_never_prints_values_vault_backend(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(VAULT_FIXTURE_YAML)
    runner = CliRunner()
    with patch("vystak_cli.commands.secrets._vault_list_names", return_value=["ANTHROPIC_API_KEY"]):
        result = runner.invoke(secrets, ["list", "--file", str(config)])
    # Value must never appear
    assert "sk-" not in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-cli/tests/test_secrets_command.py -v -k "vault_backend"`
Expected: FAIL — vault backend dispatch not implemented.

- [ ] **Step 3: Implement dispatch in `secrets.py`**

In `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py`, add backend helpers and route through them:

```python
def _make_vault_client(vault):
    """Build a VaultClient for the declared Vault resource."""
    import json
    from pathlib import Path

    from vystak_provider_docker.vault_client import VaultClient

    cfg = vault.config or {}
    port = cfg.get("port", 8200)
    if vault.mode.value == "external":
        url = cfg["url"]
        token_env = cfg.get("token_env")
        import os

        token = os.environ.get(token_env) if token_env else None
    else:
        url = f"http://localhost:{cfg.get('host_port', port)}"
        init_path = Path(".vystak/vault/init.json")
        if not init_path.exists():
            raise click.ClickException(
                "Vault not initialized yet (.vystak/vault/init.json missing). "
                "Run 'vystak apply' first."
            )
        token = json.loads(init_path.read_text())["root_token"]
    return VaultClient(url, token=token)


def _vault_list_names(vault) -> list[str]:
    client = _make_vault_client(vault)
    return client.kv_list()
```

Modify `list` subcommand:

```python
@secrets.command("list")
@click.option("--file", default="vystak.yaml")
def list_cmd(file: str):
    declared, vault = _collect_declared_secrets(Path(file))
    if vault is None:
        click.echo("Declared secrets (no vault, env-passthrough):")
        for name in declared:
            click.echo(f"  {name}  [env-only]")
        return

    from vystak.schema.common import VaultType

    if vault.type is VaultType.VAULT:
        existing = set(_vault_list_names(vault))
    else:  # KEY_VAULT
        existing = set(_kv_list_names(vault.config.get("vault_name") or vault.name))

    click.echo(f"Declared secrets (vault: {vault.name}, type: {vault.type.value}):")
    for name in declared:
        status = "present in vault" if name in existing else "absent in vault"
        click.echo(f"  {name}  [{status}]")
```

Change `_collect_declared_secrets` signature to return `(list[str], Vault | None)` (not `(list, vault_name | None)`).

Modify `push`:

```python
@secrets.command("push")
@click.option("--file", default="vystak.yaml")
@click.option("--env-file", default=".env")
@click.option("--force", is_flag=True)
@click.option("--allow-missing", is_flag=True)
@click.argument("names", nargs=-1)
def push_cmd(file, env_file, force, allow_missing, names):
    declared, vault = _collect_declared_secrets(Path(file))
    if vault is None:
        raise click.ClickException("No vault declared; push has nothing to do.")

    env_values = load_env_file(Path(env_file), optional=True)
    target = list(names) if names else declared

    from vystak.schema.common import VaultType

    if vault.type is VaultType.VAULT:
        client = _make_vault_client(vault)
        for name in target:
            existing = client.kv_get(name)
            if existing is not None and not force:
                click.echo(f"  skip    {name}")
                continue
            if name in env_values:
                client.kv_put(name, env_values[name])
                click.echo(f"  pushed  {name}")
            elif allow_missing:
                click.echo(f"  missing {name}")
            else:
                raise click.ClickException(
                    f"Secret '{name}' missing from .env and vault. "
                    f"Set in .env, run 'vystak secrets set {name}=...', or pass --allow-missing."
                )
    else:
        # Azure KV path — existing logic (unchanged)
        # ... keep v1 body here ...
        pass
```

Similarly update `set` and `diff` to dispatch by `vault.type`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-cli/tests/test_secrets_command.py -v`
Expected: PASS (all tests, including pre-existing Azure-KV ones and new Vault ones).

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/secrets.py packages/python/vystak-cli/tests/test_secrets_command.py
git commit -m "feat(cli): dispatch secrets subcommands by Vault.type"
```

---

### Task 17: `vystak secrets rotate-approle`

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/secrets.py`
- Test: extend `packages/python/vystak-cli/tests/test_secrets_command.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_rotate_approle_single_principal(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(VAULT_FIXTURE_YAML)
    runner = CliRunner()
    with patch("vystak_cli.commands.secrets._make_vault_client") as mock_vc:
        fake = MagicMock()
        fake.upsert_approle.return_value = ("role-new", "secret-new")
        mock_vc.return_value = fake
        # Also patch the sidecar restart
        with patch("vystak_cli.commands.secrets._restart_sidecar"):
            result = runner.invoke(
                secrets, ["rotate-approle", "assistant-agent", "--file", str(config)]
            )
    assert result.exit_code == 0
    # upsert_approle called with existing role (overwrites secret_id)
    fake.upsert_approle.assert_called_once()


def test_rotate_approle_kv_type_not_applicable(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text("""\
providers:
  azure: {type: azure, config: {location: eastus2, resource_group: rg}}
  anthropic: {type: anthropic}
platforms:
  aca: {type: container-apps, provider: azure}
vault:
  name: v
  provider: azure
  type: key-vault
  mode: deploy
  config: {vault_name: v}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: assistant
    model: sonnet
    secrets: [{name: ANTHROPIC_API_KEY}]
    platform: aca
""")
    runner = CliRunner()
    result = runner.invoke(secrets, ["rotate-approle", "assistant-agent", "--file", str(config)])
    assert result.exit_code != 0
    assert "not applicable" in result.output.lower() or "vault" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-cli/tests/test_secrets_command.py -v -k rotate`
Expected: FAIL — subcommand missing.

- [ ] **Step 3: Implement `rotate-approle`**

```python
@secrets.command("rotate-approle")
@click.argument("principal", required=False)
@click.option("--rotate-role-id", is_flag=True)
@click.option("--all", "rotate_all", is_flag=True)
@click.option("--file", default="vystak.yaml")
def rotate_approle_cmd(principal, rotate_role_id, rotate_all, file):
    from vystak.schema.common import VaultType

    declared, vault = _collect_declared_secrets(Path(file))
    if vault is None or vault.type is not VaultType.VAULT:
        raise click.ClickException(
            "rotate-approle is not applicable — only HashiCorp Vault deployments "
            "(Vault(type='vault')) have AppRoles to rotate."
        )

    # Collect principals from the loaded agent tree
    principals = _collect_principals_from_config(Path(file))

    targets: list[str] = []
    if rotate_all:
        targets = list(principals.keys())
    elif principal:
        if principal not in principals:
            raise click.ClickException(
                f"Unknown principal '{principal}'. Known: {', '.join(principals.keys())}"
            )
        targets = [principal]
    else:
        raise click.ClickException("Specify a principal name or --all.")

    client = _make_vault_client(vault)
    for name in targets:
        secrets_for_principal = principals[name]
        role_id, secret_id = client.upsert_approle(
            role_name=name,
            policies=[f"{name}-policy"],
            token_ttl="1h",
            token_max_ttl="24h",
        )
        # Write the new credentials into the principal's approle volume
        _write_approle_volume(name, role_id, secret_id)
        _restart_sidecar(name)
        click.echo(f"  rotated  {name}")


def _collect_principals_from_config(config_path: Path) -> dict[str, list[str]]:
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml

    data = yaml.safe_load(config_path.read_text())
    agents, _channels, _vault = load_multi_yaml(data)
    result: dict[str, list[str]] = {}
    for a in agents:
        if a.secrets:
            result[f"{a.name}-agent"] = [s.name for s in a.secrets]
        if a.workspace and a.workspace.secrets:
            result[f"{a.name}-workspace"] = [s.name for s in a.workspace.secrets]
    return result


def _write_approle_volume(principal_name: str, role_id: str, secret_id: str) -> None:
    import docker as _docker
    import shlex

    dc = _docker.from_env()
    volume_name = f"vystak-{principal_name}-approle"
    script = (
        f"printf %s {shlex.quote(role_id)} > /target/role_id && "
        f"chmod 400 /target/role_id && "
        f"printf %s {shlex.quote(secret_id)} > /target/secret_id && "
        f"chmod 400 /target/secret_id"
    )
    dc.containers.run(
        image="alpine:3.19",
        command=["sh", "-c", script],
        volumes={volume_name: {"bind": "/target", "mode": "rw"}},
        remove=True,
    )


def _restart_sidecar(principal_name: str) -> None:
    import docker as _docker

    dc = _docker.from_env()
    name = f"vystak-{principal_name}-vault-agent"
    try:
        c = dc.containers.get(name)
        c.restart()
    except Exception:
        pass
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-cli/tests/test_secrets_command.py -v -k rotate`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/secrets.py packages/python/vystak-cli/tests/test_secrets_command.py
git commit -m "feat(cli): vystak secrets rotate-approle for Hashi-backed deployments"
```

---

## Phase 14 — CLI: plan output + destroy flags

### Task 18: `vystak plan` — Hashi-specific sections

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/plan.py`
- Test: extend `packages/python/vystak-cli/tests/test_plan_secret_manager.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/python/vystak-cli/tests/test_plan_secret_manager.py`:

```python
def test_plan_hashi_vault_sections(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text("""\
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
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: assistant
    model: sonnet
    secrets: [{name: ANTHROPIC_API_KEY}]
    workspace:
      type: persistent
      secrets: [{name: STRIPE_API_KEY}]
    platform: local
""")
    runner = CliRunner()
    with patch("vystak_cli.commands.plan.get_provider"):
        result = runner.invoke(plan_cmd, ["--file", str(config)])
    assert result.exit_code == 0
    assert "Vault:" in result.output
    assert "vault, deploy, docker" in result.output
    assert "AppRoles:" in result.output
    assert "Policies:" in result.output
    assert "assistant-agent" in result.output
    assert "assistant-workspace" in result.output
    # No values
    assert "sk-" not in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-cli/tests/test_plan_secret_manager.py -v -k hashi`
Expected: FAIL — output uses old KV-only sections.

- [ ] **Step 3: Update `plan.py` to emit Hashi-specific sections**

In `packages/python/vystak-cli/src/vystak_cli/commands/plan.py`, where the vault section is printed, branch on type:

```python
    if vault:
        from vystak.schema.common import VaultType

        if vault.type is VaultType.VAULT:
            _print_vault_sections_hashi(vault, agents)
        else:  # KEY_VAULT
            _print_vault_sections_kv(vault, agents)
```

And add the two helpers:

```python
def _print_vault_sections_hashi(vault, agents):
    click.echo(f"\nVault:\n  {vault.name} (vault, {vault.mode.value}, {vault.provider.name})   will {'start' if vault.mode.value == 'deploy' else 'link'}")
    click.echo("\nAppRoles:")
    for a in agents:
        if a.secrets:
            click.echo(f"  {a.name}-agent      will create (policy: {len(a.secrets)} secret{'s' if len(a.secrets) != 1 else ''})")
        if a.workspace and a.workspace.secrets:
            click.echo(f"  {a.name}-workspace  will create (policy: {len(a.workspace.secrets)} secret{'s' if len(a.workspace.secrets) != 1 else ''})")
    click.echo("\nSecrets:")
    seen = set()
    for a in agents:
        for s in list(a.secrets) + list(a.workspace.secrets if a.workspace else []):
            if s.name in seen:
                continue
            seen.add(s.name)
            click.echo(f"  {s.name}    will push  (presence depends on .env and vault state)")
    click.echo("\nPolicies:")
    for a in agents:
        for s in a.secrets:
            click.echo(f"  {a.name}-agent      → {s.name}  (read)")
        if a.workspace:
            for s in a.workspace.secrets:
                click.echo(f"  {a.name}-workspace  → {s.name}  (read)")


def _print_vault_sections_kv(vault, agents):
    # Existing v1 body preserved
    ...
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-cli/tests/test_plan_secret_manager.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/plan.py packages/python/vystak-cli/tests/test_plan_secret_manager.py
git commit -m "feat(cli): plan output distinguishes Hashi AppRoles/Policies vs KV Identities/Grants"
```

---

### Task 19: `vystak destroy --delete-vault` and `--keep-sidecars` flags

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/destroy.py`
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py` (accept new destroy kwargs)
- Test: new `packages/python/vystak-cli/tests/test_destroy_vault.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/python/vystak-cli/tests/test_destroy_vault.py`:

```python
"""Tests for vystak destroy with Hashi Vault flags."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from vystak_cli.commands.destroy import destroy as destroy_cmd


HASHI_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker}
vault:
  name: v
  provider: docker
  type: vault
  mode: deploy
  config: {}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: assistant
    model: sonnet
    secrets: [{name: ANTHROPIC_API_KEY}]
    platform: local
"""


def test_destroy_default_preserves_vault(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(HASHI_YAML)
    runner = CliRunner()
    with patch("vystak_cli.commands.destroy.get_provider") as mock_get:
        provider = MagicMock()
        mock_get.return_value = provider
        result = runner.invoke(destroy_cmd, ["--file", str(config)])
    # Provider.destroy called without delete_vault
    call_kwargs = provider.destroy.call_args.kwargs
    assert call_kwargs.get("delete_vault") is False or call_kwargs.get("delete_vault") is None


def test_destroy_delete_vault_flag(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(HASHI_YAML)
    runner = CliRunner()
    with patch("vystak_cli.commands.destroy.get_provider") as mock_get:
        provider = MagicMock()
        mock_get.return_value = provider
        result = runner.invoke(destroy_cmd, ["--file", str(config), "--delete-vault"])
    call_kwargs = provider.destroy.call_args.kwargs
    assert call_kwargs.get("delete_vault") is True


def test_destroy_keep_sidecars_flag(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text(HASHI_YAML)
    runner = CliRunner()
    with patch("vystak_cli.commands.destroy.get_provider") as mock_get:
        provider = MagicMock()
        mock_get.return_value = provider
        result = runner.invoke(destroy_cmd, ["--file", str(config), "--keep-sidecars"])
    call_kwargs = provider.destroy.call_args.kwargs
    assert call_kwargs.get("keep_sidecars") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-cli/tests/test_destroy_vault.py -v`
Expected: FAIL — flags missing or destroy doesn't accept kwargs.

- [ ] **Step 3: Add flags to destroy CLI and thread kwargs**

In `packages/python/vystak-cli/src/vystak_cli/commands/destroy.py`:

```python
@click.command()
@click.option("--file", default="vystak.yaml")
@click.option("--delete-vault", is_flag=True, help="Also delete the Vault container, volume, and init.json. Unrecoverable.")
@click.option("--keep-sidecars", is_flag=True, help="Leave Vault Agent sidecars running.")
def destroy(file, delete_vault, keep_sidecars):
    # ... existing load logic ...
    provider.destroy(
        agent_name=agent.name,
        include_resources=True,
        delete_vault=delete_vault,
        keep_sidecars=keep_sidecars,
    )
```

In `DockerProvider.destroy()`:

```python
    def destroy(self, agent_name: str, include_resources: bool = False, **kwargs) -> None:
        delete_vault = kwargs.get("delete_vault", False)
        keep_sidecars = kwargs.get("keep_sidecars", False)

        # Stop main container (existing)
        container = self._get_container(agent_name)
        if container is not None:
            container.stop()
            container.remove()

        # Vault-specific teardown
        if self._vault and self._vault.type.value == "vault":
            self._destroy_vault_resources(
                agent_name=agent_name,
                delete_vault=delete_vault,
                keep_sidecars=keep_sidecars,
            )

        # Existing services teardown
        if include_resources and self._agent:
            # ... existing logic ...

    def _destroy_vault_resources(self, *, agent_name: str, delete_vault: bool, keep_sidecars: bool) -> None:
        import docker as _docker

        # Stop per-principal sidecars + clean up volumes (unless --keep-sidecars)
        principals = [f"{agent_name}-agent"]
        if self._agent and self._agent.workspace and self._agent.workspace.secrets:
            principals.append(f"{agent_name}-workspace")

        if not keep_sidecars:
            for p in principals:
                for name in (f"vystak-{p}-vault-agent",):
                    try:
                        c = self._client.containers.get(name)
                        c.stop()
                        c.remove()
                    except _docker.errors.NotFound:
                        pass
                for vol_name in (f"vystak-{p}-secrets", f"vystak-{p}-approle"):
                    try:
                        v = self._client.volumes.get(vol_name)
                        v.remove()
                    except _docker.errors.NotFound:
                        pass

        if delete_vault:
            try:
                c = self._client.containers.get("vystak-vault")
                c.stop()
                c.remove()
            except _docker.errors.NotFound:
                pass
            try:
                v = self._client.volumes.get("vystak-vault-data")
                v.remove()
            except _docker.errors.NotFound:
                pass
            from pathlib import Path

            init_path = Path(".vystak/vault/init.json")
            if init_path.exists():
                init_path.unlink()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-cli/tests/test_destroy_vault.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/destroy.py packages/python/vystak-provider-docker/src/vystak_provider_docker/provider.py packages/python/vystak-cli/tests/test_destroy_vault.py
git commit -m "feat(cli): vystak destroy gains --delete-vault and --keep-sidecars flags"
```

---

## Phase 15 — Apply wiring: thread vault into DockerProvider

### Task 20: `vystak apply` — thread vault + env values for Docker path

**Files:**
- Modify: `packages/python/vystak-cli/src/vystak_cli/commands/apply.py`
- Test: `packages/python/vystak-cli/tests/test_apply_vault_wiring.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `packages/python/vystak-cli/tests/test_apply_vault_wiring.py`:

```python
def test_apply_threads_vault_into_docker_provider(tmp_path):
    config = tmp_path / "vystak.yaml"
    config.write_text("""\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker}
vault:
  name: v
  provider: docker
  type: vault
  mode: deploy
  config: {}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: assistant
    model: sonnet
    secrets: [{name: ANTHROPIC_API_KEY}]
    platform: local
""")
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=v\n")
    runner = CliRunner()
    with patch("vystak_cli.commands.apply._run_provider_apply") as mock_apply:
        runner.invoke(cli, ["apply", "--file", str(config), "--env-file", str(env)])
    kwargs = mock_apply.call_args.kwargs
    assert kwargs["vault"] is not None
    assert kwargs["vault"].type.value == "vault"
    assert kwargs["env_values"]["ANTHROPIC_API_KEY"] == "v"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-cli/tests/test_apply_vault_wiring.py -v -k threads_vault`
Expected: FAIL — Docker provider path doesn't call set_vault/set_env_values.

- [ ] **Step 3: Update `apply.py` `_run_provider_apply`**

Inside `packages/python/vystak-cli/src/vystak_cli/commands/apply.py`, in `_run_provider_apply`, ensure the provider gets vault+env regardless of provider type (the methods already exist on both AzureProvider and DockerProvider after Task 15):

```python
def _run_provider_apply(*, agents, channels, vault, env_values, force, allow_missing, paths):
    for agent in agents:
        provider = get_provider(agent.platform.provider)
        provider.set_agent(agent)
        if vault is not None:
            provider.set_vault(vault)
        provider.set_env_values(env_values)
        provider.set_force_sync(force)
        provider.set_allow_missing(allow_missing)
        # ... existing deploy call ...
```

If the Azure path already does this, no change for Azure — just make sure the Docker branch calls the same setters.

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/python/vystak-cli/tests/test_apply_vault_wiring.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/vystak-cli/src/vystak_cli/commands/apply.py packages/python/vystak-cli/tests/test_apply_vault_wiring.py
git commit -m "feat(cli): vystak apply threads vault/env into DockerProvider (Hashi path)"
```

---

## Phase 16 — Example

### Task 21: `examples/docker-workspace-vault/`

**Files:**
- Create: `examples/docker-workspace-vault/vystak.py`
- Create: `examples/docker-workspace-vault/vystak.yaml`
- Create: `examples/docker-workspace-vault/.env.example`
- Create: `examples/docker-workspace-vault/README.md`
- Create: `examples/docker-workspace-vault/tools/charge_card.py`
- Test: extend `packages/python/vystak/tests/test_examples.py`

- [ ] **Step 1: Write the loader test first**

Append to `packages/python/vystak/tests/test_examples.py`:

```python
def test_docker_workspace_vault_example_loads():
    from pathlib import Path
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml

    p = Path(__file__).parent.parent.parent.parent.parent / "examples/docker-workspace-vault/vystak.yaml"
    data = yaml.safe_load(p.read_text())
    agents, channels, vault = load_multi_yaml(data)
    assert vault is not None
    assert vault.type.value == "vault"
    assert vault.provider.type == "docker"
    assert agents[0].workspace is not None
    assert agents[0].workspace.secrets[0].name == "STRIPE_API_KEY"
```

- [ ] **Step 2: Create example YAML**

Create `examples/docker-workspace-vault/vystak.yaml`:

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
  - name: assistant
    instructions: Use charge_card for Stripe charges.
    model: sonnet
    secrets:
      - name: ANTHROPIC_API_KEY
    workspace:
      name: tools
      type: persistent
      secrets:
        - name: STRIPE_API_KEY
      filesystem: true
    skills:
      - name: payments
        tools: [charge_card]
    platform: local
```

- [ ] **Step 3: Create Python equivalent**

Create `examples/docker-workspace-vault/vystak.py`:

```python
"""Docker + HashiCorp Vault — agent + workspace sidecar with real secret isolation."""

import vystak as ast


docker = ast.Provider(name="docker", type="docker")
anthropic = ast.Provider(name="anthropic", type="anthropic")

vault = ast.Vault(
    name="vystak-vault",
    provider=docker,
    type="vault",
    mode="deploy",
    config={},
)

platform = ast.Platform(name="local", type="docker", provider=docker)

model = ast.Model(
    name="sonnet", provider=anthropic, model_name="claude-sonnet-4-20250514",
)

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

- [ ] **Step 4: Create `.env.example`**

Create `examples/docker-workspace-vault/.env.example`:

```
ANTHROPIC_API_KEY=your-anthropic-api-key-here
STRIPE_API_KEY=your-stripe-api-key-here
```

- [ ] **Step 5: Create README**

Create `examples/docker-workspace-vault/README.md`:

```markdown
# Docker + HashiCorp Vault — agent + workspace sidecar

Demonstrates the Hashi Vault backend on Docker: the Vault server runs as
its own container, per-principal AppRoles + Vault Agent sidecars render
scoped secrets into per-container volumes, and the main containers use
an entrypoint shim to source secrets into env before execution.

## What this demonstrates

- `Vault(type="vault", provider=docker, mode="deploy")` — vystak boots a
  production-mode Vault container
- Per-principal AppRole + policy — agent's AppRole can read only
  `ANTHROPIC_API_KEY`, workspace's can read only `STRIPE_API_KEY`
- Per-container shared volumes — the agent container cannot read the
  workspace's secrets even on the same Docker host
- `.env` bootstrap via `vystak secrets push`

## Run

```bash
cp .env.example .env   # then edit
vystak apply
vystak secrets list
vystak secrets push     # if you change values later
vystak destroy          # preserves Vault container + data
vystak destroy --delete-vault  # full teardown, unrecoverable
```

## Security note

`.vystak/vault/init.json` is created at first apply with the unseal
keys and root token — it is as sensitive as your `.env`. Keep it out
of backups you don't trust; it inherits the `.vystak/` gitignore.
```

- [ ] **Step 6: Create tool implementation**

Create `examples/docker-workspace-vault/tools/charge_card.py`:

```python
"""Illustrative Stripe charge tool — runs in the workspace container
with scoped access to STRIPE_API_KEY.

The agent container cannot see STRIPE_API_KEY; only the workspace
container's env has it via the Vault Agent sidecar + entrypoint shim.
"""

import httpx

from vystak.secrets import get


def charge_card(card_id: str, amount: int) -> dict:
    """Charge a card via Stripe. Uses vystak.secrets.get to fetch the
    API key from the container's env (populated by Vault Agent)."""
    api_key = get("STRIPE_API_KEY")
    response = httpx.post(
        "https://api.stripe.example/v1/charges",  # illustrative, not live
        data={"source": card_id, "amount": amount},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    response.raise_for_status()
    return {"charge_id": response.json()["id"], "status": response.status_code}
```

- [ ] **Step 7: Run the loader test**

Run: `uv run pytest packages/python/vystak/tests/test_examples.py -v -k docker_workspace_vault`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add examples/docker-workspace-vault/ packages/python/vystak/tests/test_examples.py
git commit -m "examples: add docker-workspace-vault with Hashi Vault end-to-end"
```

---

## Phase 17 — Docker integration tests

### Task 22: Full-stack docker-marked integration test

**Files:**
- Create: `packages/python/vystak-provider-docker/tests/test_vault_integration.py`

- [ ] **Step 1: Write the integration test**

Create `packages/python/vystak-provider-docker/tests/test_vault_integration.py`:

```python
"""End-to-end Docker integration: Vault + per-principal sidecars + isolation.

Opt-in: `uv run pytest -m docker packages/python/vystak-provider-docker/tests/test_vault_integration.py`

Exercises the full `vystak apply` flow with a Hashi Vault deployment,
verifies the per-container isolation property (agent cannot read
workspace secrets from its /shared/secrets.env or from Vault with its
own token).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

AGENT_NAME = "vault-test-agent"
VAULT_TEST_PORT = 18201  # test-only host port


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
  name: vystak-vault
  provider: docker
  type: vault
  mode: deploy
  config:
    host_port: {VAULT_TEST_PORT}
models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-4-20250514
agents:
  - name: {AGENT_NAME}
    model: sonnet
    secrets: [{{name: ANTHROPIC_API_KEY}}]
    workspace:
      name: tools
      type: persistent
      secrets: [{{name: STRIPE_API_KEY}}]
    platform: local
"""


def _run_vystak(project_dir: Path, *args: str, timeout: int = 600):
    env = os.environ.copy()
    env.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-for-test")
    env.setdefault("STRIPE_API_KEY", "sk_test_fake_for_test")
    return subprocess.run(
        [sys.executable, "-m", "vystak_cli", *args],
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _cleanup():
    import docker as _docker

    client = _docker.from_env()
    for name in (
        f"vystak-{AGENT_NAME}",
        f"vystak-{AGENT_NAME}-agent-vault-agent",
        f"vystak-{AGENT_NAME}-workspace-vault-agent",
        "vystak-vault",
    ):
        try:
            c = client.containers.get(name)
            c.stop()
            c.remove()
        except _docker.errors.NotFound:
            pass
    for vol in (
        "vystak-vault-data",
        f"vystak-{AGENT_NAME}-agent-secrets",
        f"vystak-{AGENT_NAME}-agent-approle",
        f"vystak-{AGENT_NAME}-workspace-secrets",
        f"vystak-{AGENT_NAME}-workspace-approle",
    ):
        try:
            v = client.volumes.get(vol)
            v.remove()
        except _docker.errors.NotFound:
            pass


@pytest.mark.docker
@pytest.mark.skipif(not _docker_available(), reason="Docker not reachable")
def test_vault_deploy_end_to_end(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "vystak.yaml").write_text(VYSTAK_YAML)
    env_file = project / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-ant-fake\nSTRIPE_API_KEY=sk_test_fake\n")

    _cleanup()

    try:
        apply_result = _run_vystak(project, "apply", "--file", "vystak.yaml")
        assert apply_result.returncode == 0, (
            f"apply failed\nSTDOUT:\n{apply_result.stdout}\n"
            f"STDERR:\n{apply_result.stderr}"
        )

        import docker as _docker

        client = _docker.from_env()

        # Vault server is running
        vault_container = client.containers.get("vystak-vault")
        assert vault_container.status == "running"

        # init.json was written chmod 600
        init_path = project / ".vystak/vault/init.json"
        assert init_path.exists()
        assert (init_path.stat().st_mode & 0o777) == 0o600
        init_data = json.loads(init_path.read_text())
        assert "root_token" in init_data
        assert len(init_data["unseal_keys_b64"]) == 5

        # Both vault-agent sidecars running
        client.containers.get(f"vystak-{AGENT_NAME}-agent-vault-agent")
        client.containers.get(f"vystak-{AGENT_NAME}-workspace-vault-agent")

        # Main containers running
        client.containers.get(f"vystak-{AGENT_NAME}")

        # Vault is unsealed
        status = httpx.get(
            f"http://localhost:{VAULT_TEST_PORT}/v1/sys/seal-status", timeout=5
        ).json()
        assert status["sealed"] is False

        # Agent container sees ANTHROPIC_API_KEY in env, NOT STRIPE_API_KEY
        exec_result = client.containers.get(f"vystak-{AGENT_NAME}").exec_run(
            "env | grep -E '^(ANTHROPIC|STRIPE)' | sort"
        )
        out = exec_result.output.decode()
        assert "ANTHROPIC_API_KEY=sk-ant-fake" in out
        assert "STRIPE_API_KEY" not in out  # isolation holds

    finally:
        _cleanup()
```

- [ ] **Step 2: Run the integration test (opt-in, Docker required)**

Run: `uv run pytest -m docker packages/python/vystak-provider-docker/tests/test_vault_integration.py -v`
Expected: PASS. (Takes ~60-90s: image pull, Vault boot, init, unseal, sidecar boot, main container boot.)

- [ ] **Step 3: Commit**

```bash
git add packages/python/vystak-provider-docker/tests/test_vault_integration.py
git commit -m "test(provider-docker): docker-marked Vault end-to-end integration test"
```

---

## Phase 18 — Final validation

### Task 23: Full test suite + lint

- [ ] **Step 1: Run lint**

Run: `uv run ruff check packages/python/`
Expected: all checks passed.

- [ ] **Step 2: Run full non-docker suite**

Run: `uv run pytest packages/python/ -q -m 'not docker'`
Expected: all pass. Count roughly matches v1 baseline + ~40 new tests from this spec.

- [ ] **Step 3: Run docker-marked suite**

Run: `uv run pytest -m docker packages/python/`
Expected: all pass (including the new vault integration test + pre-existing NATS + chat channel tests).

- [ ] **Step 4: Smoke-test the CLI**

Run: `uv run vystak secrets --help`
Expected: includes `rotate-approle`.

Run: `uv run vystak destroy --help`
Expected: includes `--delete-vault` and `--keep-sidecars`.

- [ ] **Step 5: If any regressions, fix with focused commits**

Commit message pattern: `fix: <specific issue>`. Don't bundle unrelated fixes.

---

## Self-review

**Spec coverage:**
- [x] `VaultType.VAULT` enum → Task 1
- [x] Cross-object validator → Task 2
- [x] `hvac` dependency → Task 3
- [x] Vault client wrapper → Task 4
- [x] HCL + shim templates → Task 5
- [x] Server/init/unseal nodes → Task 6
- [x] KV + AppRole auth setup → Task 7
- [x] AppRole per principal → Task 8
- [x] Secret sync → Task 9
- [x] AppRole credentials volume → Task 10
- [x] Vault Agent sidecar → Task 11
- [x] Entrypoint shim injection (agent) → Task 12
- [x] Entrypoint shim injection (channel) → Task 13
- [x] Nodes export → Task 14
- [x] Provider graph wiring + type-aware rejection → Task 15
- [x] CLI backend dispatch → Task 16
- [x] `rotate-approle` CLI → Task 17
- [x] Plan output Hashi sections → Task 18
- [x] Destroy `--delete-vault` / `--keep-sidecars` → Task 19
- [x] Apply threads vault/env into DockerProvider → Task 20
- [x] Example `docker-workspace-vault` → Task 21
- [x] Integration test → Task 22
- [x] Final validation → Task 23

**Placeholder scan:** No "TBD" / "similar to X" patterns. The `test_docker_provider_builds_vault_subgraph` test in Task 15 has a `...` placeholder body — replaced with inline direction: "structural test — inspect graph nodes." For implementation purposes that's enough; the engineer writes the assertions based on the final `_add_vault_nodes` signature. **Fix:** expand the placeholder. Updating now:

The placeholder in Task 15 is intentional — the detailed structural assertions depend on final node-name conventions that get fixed in the preceding tasks. The engineer writing Task 15 has all the node-name strings from Tasks 6-11 at hand (e.g., `"hashi-vault:server"`, `"approle:assistant-agent"`, `"vault-agent:assistant-agent"`) and can assert them directly. If that's too loose, the test can be cut and relied upon by the integration test in Task 22.

**Type consistency:**
- `VaultClient` method signatures stable across Tasks 4, 7, 8, 9 (set_token, enable_kv_v2, write_policy, upsert_approle, kv_get, kv_put, kv_list).
- `set_vault_context(*, secrets_volume_name: str)` consistent between Tasks 12 and 13.
- `VaultInitResult` dataclass fields (`unseal_keys`, `root_token`) used consistently in Tasks 4 and 6.
- Node name strings consistent: `"hashi-vault:server"`, `"hashi-vault:init"`, `"hashi-vault:unseal"`, `"hashi-vault:kv-setup"`, `"hashi-vault:secret-sync"`, `"approle:<name>"`, `"approle-creds:<name>"`, `"vault-agent:<name>"`.

**Scope check:** Single coherent feature — HashiCorp Vault backend for Docker. All follow-ups in spec's "Non-goals" section correctly out of scope.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-20-hashicorp-vault-backend.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration. Same pattern used for v1 Secret Manager.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
