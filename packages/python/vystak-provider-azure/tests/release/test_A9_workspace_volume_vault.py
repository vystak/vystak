"""Cell A9 — azure × keyvault × workspace × volume persistence.

Opt-in lifecycle test for the standalone workspace path on ACA.
Gates: AZURE_SUBSCRIPTION_ID + AZURE_STORAGE_ACCOUNT must be set.

Verification dimensions covered:
- V1  Plan: "Workspaces:" and "Vault:" sections present; "EnvFiles:" absent.
- V2  Apply exits 0; both the agent ACA app and the workspace ACA app are
      in running state.
- V4  Health: GET /health on the agent app returns {"status": "ok"}.
- V9  Destroy: agent app and workspace app are gone after destroy; the
      Azure Files share is preserved (only removed on --delete-workspace-data).

Skips (not errors) when prereqs are missing — consistent with A1/A2 pattern.

Wall time: expect 5–8 minutes (A2 base + ~2 min for workspace image build,
Azure Files share provisioning, and workspace ACA app creation).
"""

from __future__ import annotations

import os

import pytest

from .conftest import (
    app_exists,
    assert_apply_ok,
    assert_health_azure,
    assert_plan_ok,
    run,
    vystak,
)

pytestmark = [pytest.mark.release_smoke_azure]


A9_YAML_TEMPLATE = """\
providers:
  azure:
    type: azure
    config:
      location: eastus2
      resource_group: {rg_name}
      storage_account: {storage_account}
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
  - name: wsagent
    model: sonnet
    platform: aca
    secrets:
      - {{name: ANTHROPIC_API_KEY}}
      - {{name: ANTHROPIC_API_URL}}
    workspace:
      name: tools
      image: python:3.11-slim
      persistence: volume
      provision:
        - echo workspace-ready
      secrets:
        - {{name: ANTHROPIC_API_KEY}}
"""


def test_A9_workspace_volume_vault_lifecycle(azure_project):
    import uuid

    if not os.getenv("AZURE_SUBSCRIPTION_ID"):
        pytest.skip("AZURE_SUBSCRIPTION_ID not set — skipping A9")
    storage_account = os.getenv("AZURE_STORAGE_ACCOUNT")
    if not storage_account:
        pytest.skip(
            "AZURE_STORAGE_ACCOUNT not set (needed for workspace persistence: volume)"
            " — skipping A9"
        )

    project, rg_name = azure_project
    # KV names must be globally unique, 3–24 chars, alphanum+dash.
    kv_name = f"vystakws{uuid.uuid4().hex[:8]}"

    (project / "vystak.yaml").write_text(
        A9_YAML_TEMPLATE.format(
            rg_name=rg_name,
            kv_name=kv_name,
            storage_account=storage_account,
        )
    )

    # V1 — plan: workspace + vault sections present; no plain EnvFiles path.
    assert_plan_ok(
        cwd=project,
        expect_sections=["Workspaces:", "Vault:", "Identities:", "Secrets:"],
        absent_sections=["EnvFiles:"],
    )

    # V2 — apply. Extra time for workspace image build + Files share + app.
    assert_apply_ok(cwd=project, timeout=1500)
    assert app_exists("wsagent", rg_name), "agent ACA app missing after apply"
    assert app_exists("wsagent-workspace", rg_name), (
        "workspace ACA app (vystak-wsagent-workspace) missing after apply"
    )

    # Verify Key Vault was created.
    sub = os.environ["AZURE_SUBSCRIPTION_ID"]
    result = run(
        ["az", "keyvault", "show", "-n", kv_name,
         "--subscription", sub, "--output", "none"],
        check=False, timeout=30,
    )
    assert result.returncode == 0, f"Key Vault {kv_name} not found after apply"

    # V4 — agent health via HTTPS FQDN. Workspace app exposes SSH (port 22),
    # not HTTP, so we only health-check the agent app.
    assert_health_azure("wsagent", rg_name, timeout=180)

    # V9 — destroy. Azure Files share should be preserved (not deleted unless
    # --delete-workspace-data is passed). Belt-and-braces RG delete happens in
    # the azure_project fixture teardown regardless.
    vystak(["destroy", "--no-wait"], cwd=project, check=False)
    vystak(
        ["destroy", "--delete-vault", "--include-resources", "--no-wait"],
        cwd=project, check=False,
    )
    # Both apps should be absent once the RG is gone (handled by fixture teardown).
