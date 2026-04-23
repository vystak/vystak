"""Cell A4 — azure × keyvault × slack × http.

Integration tier. A2 (Key Vault + UAMI + lifecycle:None) + Slack
channel. Verifies:

- Slack channel gets its own UAMI with lifecycle:None + its own KV
  secrets granted.
- Agent UAMI cannot access SLACK_* secrets; slack-channel UAMI cannot
  access ANTHROPIC_*. Per-principal grant scoping.

Most expensive smoke/integration cell (KV + 2 UAMIs + 2 ACA apps with
grants + RBAC propagation). Timeout bumped accordingly.
"""

from __future__ import annotations

import os
import uuid

import pytest

from .conftest import (
    app_exists,
    assert_apply_ok,
    assert_env_absent,
    assert_env_contains,
    assert_plan_ok,
    run,
    vystak,
)

pytestmark = [pytest.mark.release_integration, pytest.mark.release_slack]


A4_YAML_TEMPLATE = """\
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
  - name: slack
    type: slack
    platform: aca
    secrets:
      - {{name: SLACK_BOT_TOKEN}}
      - {{name: SLACK_APP_TOKEN}}
agents:
  - name: a4agent
    model: sonnet
    platform: aca
    secrets:
      - {{name: ANTHROPIC_API_KEY}}
      - {{name: ANTHROPIC_API_URL}}
"""


@pytest.fixture
def slack_env(azure_project):
    bot = os.environ.get("SLACK_BOT_TOKEN")
    app = os.environ.get("SLACK_APP_TOKEN")
    if not bot or not app:
        pytest.skip("SLACK_BOT_TOKEN / SLACK_APP_TOKEN not set — skipping A4")
    project, rg = azure_project
    with (project / ".env").open("a") as f:
        f.write(f"SLACK_BOT_TOKEN={bot}\nSLACK_APP_TOKEN={app}\n")
    return project, rg


def test_A4_full_cycle(slack_env):
    project, rg_name = slack_env
    kv_name = f"vystaksmoke{uuid.uuid4().hex[:8]}"
    (project / "vystak.yaml").write_text(
        A4_YAML_TEMPLATE.format(rg_name=rg_name, kv_name=kv_name)
    )

    assert_plan_ok(
        cwd=project,
        expect_sections=["Vault:", "Identities:", "Grants:", "a4agent-agent", "slack-channel"],
        absent_sections=["EnvFiles:"],
    )

    # Longest apply — KV + 2 UAMIs + grants + 2 ACA apps
    assert_apply_ok(cwd=project, timeout=1500)
    assert app_exists("a4agent", rg_name)

    # Verify cross-principal KV grant scoping via `az role assignment list`
    result = run(
        ["az", "identity", "list", "-g", rg_name,
         "--query", "[].name", "-o", "tsv"],
        check=True, timeout=30,
    )
    identity_names = set(result.stdout.strip().splitlines())
    # Expect one UAMI per principal with declared secrets
    assert any("a4agent" in n for n in identity_names), (
        f"missing agent UAMI in {identity_names}"
    )
    assert any("slack" in n for n in identity_names), (
        f"missing slack-channel UAMI in {identity_names}"
    )

    # V3 — per-ACA-app env scoping (values come via secretRef → KV)
    assert_env_contains("a4agent", rg_name, "ANTHROPIC_API_KEY")
    assert_env_absent("a4agent", rg_name, "SLACK_BOT_TOKEN")

    vystak(
        ["destroy", "--delete-vault", "--include-resources", "--no-wait"],
        cwd=project, check=False,
    )
