"""Cell A2 — azure × keyvault × chat × http.

Smoke tier. Same as A1 plus a `vault:` block declaring
`type=key-vault`. Provider stands up:
- Azure Key Vault (mode=deploy)
- Per-principal UAMI (user-assigned managed identity)
- `identitySettings[].lifecycle: None` on each UAMI so containers can't
  acquire tokens for them via the ACA token endpoint
- `configuration.secrets[]` with `keyVaultUrl` refs instead of inline
  values; secretRef in per-container env still scopes access

**Wall time expectation:** A1 + 1–2 min for KV create, UAMI provisioning,
grant assignment with RBAC propagation wait.
"""

from __future__ import annotations

import os

import pytest

from .conftest import (
    app_exists,
    assert_apply_ok,
    assert_env_contains,
    assert_health_azure,
    assert_plan_ok,
    run,
    vystak,
)

pytestmark = [pytest.mark.release_smoke_azure]


A2_YAML_TEMPLATE = """\
providers:
  azure:
    type: azure
    config:
      location: eastus2
      resource_group: {rg_name}
  anthropic: {{type: anthropic}}
platforms:
  aca: {{type: container-apps, provider: azure}}
vault:
  name: {kv_name}
  provider: azure
  type: key-vault
  mode: deploy
  config: {{vault_name: {kv_name}}}
models:
  sonnet: {{provider: anthropic, model_name: claude-sonnet-4-20250514}}
channels:
  - name: chat
    type: chat
    platform: aca
agents:
  - name: kvagent
    model: sonnet
    platform: aca
    secrets:
      - {{name: ANTHROPIC_API_KEY}}
      - {{name: ANTHROPIC_API_URL}}
"""


def test_A2_full_cycle(azure_project):
    import uuid

    project, rg_name = azure_project
    # KV names must be globally unique across Azure, 3–24 chars, alphanum+dash.
    kv_name = f"vystaksmoke{uuid.uuid4().hex[:8]}"

    (project / "vystak.yaml").write_text(
        A2_YAML_TEMPLATE.format(rg_name=rg_name, kv_name=kv_name)
    )

    # V1 — Vault/Identities/Secrets/Grants sections. EnvFiles absent.
    assert_plan_ok(
        cwd=project,
        expect_sections=["Vault:", "Identities:", "Secrets:", "Grants:"],
        absent_sections=["EnvFiles:"],
    )

    # V2 — apply. A2 adds KV create + per-principal UAMI + grants with
    # RBAC propagation wait; bump timeout accordingly.
    assert_apply_ok(cwd=project, timeout=1200)
    assert app_exists("kvagent", rg_name), "agent ACA app missing"

    # Verify the KV was created
    sub = os.environ["AZURE_SUBSCRIPTION_ID"]
    result = run(
        ["az", "keyvault", "show", "-n", kv_name,
         "--subscription", sub, "--output", "none"],
        check=False, timeout=30,
    )
    assert result.returncode == 0, f"Key Vault {kv_name} not found"

    # Verify the secret exists in KV (name normalized per ACA's
    # [a-z0-9][a-z0-9-]* constraint — but KV uses original names).
    result = run(
        ["az", "keyvault", "secret", "show",
         "--vault-name", kv_name, "-n", "ANTHROPIC-API-KEY",
         "--query", "name", "-o", "tsv"],
        check=False, timeout=30,
    )
    # KV secret names: Azure's convention varies; your provider may push
    # with original underscore-style or dash-normalized — check your
    # `secret_sync` node. This assertion is best-effort.
    assert result.returncode == 0 or "ANTHROPIC" in result.stdout.upper()

    # V3 — env is wired via secretRef → KV. `az containerapp exec env`
    # reflects the resolved value at runtime.
    assert_env_contains("kvagent", rg_name, "ANTHROPIC_API_KEY")

    # Verify lifecycle:None on UAMIs — containers can't acquire tokens
    # via the ACA token endpoint even though the UAMI is attached.
    result = run(
        ["az", "containerapp", "show", "-n", "kvagent", "-g", rg_name,
         "--query", "properties.configuration.identitySettings[].lifecycle",
         "-o", "tsv"],
        check=True, timeout=30,
    )
    lifecycles = result.stdout.strip().splitlines()
    assert lifecycles, "no identitySettings found on kvagent app"
    # All non-ACR-pull identities should be lifecycle: None
    assert all(lc == "None" for lc in lifecycles if lc), (
        f"expected all UAMIs to have lifecycle: None, got: {lifecycles}"
    )

    # V4, V5
    assert_health_azure("kvagent", rg_name)

    # V9 — destroy without --delete-vault preserves KV state by design.
    # Then tear KV down explicitly.
    vystak(["destroy", "--no-wait"], cwd=project, check=False)
    vystak(
        ["destroy", "--delete-vault", "--include-resources", "--no-wait"],
        cwd=project, check=False,
    )
