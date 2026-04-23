"""Cell A8 — azure × keyvault × slack × stream (edge tier).

Everything opt-in at once on Azure. KV-backed secrets + per-principal
UAMIs + Slack channel + external NATS transport. Most expensive cell
in the matrix.

Requires AZURE_SUBSCRIPTION_ID + az login + SLACK_* + VYSTAK_TEST_NATS_URL.
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

pytestmark = [
    pytest.mark.release_integration,  # Edge; runs alongside integration
    pytest.mark.release_slack,
]


A8_YAML_TEMPLATE = """\
providers:
  azure:
    type: azure
    config:
      location: eastus2
      resource_group: {rg_name}
  anthropic: {{type: anthropic}}
platforms:
  aca:
    type: container-apps
    provider: azure
    transport:
      name: nats-transport
      type: nats
      connection:
        url_env: VYSTAK_TEST_NATS_URL
      config:
        type: nats
        subject_prefix: "vystak"
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
  - name: a8agent
    model: sonnet
    platform: aca
    secrets:
      - {{name: ANTHROPIC_API_KEY}}
      - {{name: ANTHROPIC_API_URL}}
      - {{name: VYSTAK_TEST_NATS_URL}}
"""


@pytest.fixture
def full_env(azure_project):
    bot = os.environ.get("SLACK_BOT_TOKEN")
    app = os.environ.get("SLACK_APP_TOKEN")
    url = os.environ.get("VYSTAK_TEST_NATS_URL")
    if not (bot and app and url):
        pytest.skip(
            "SLACK_BOT_TOKEN / SLACK_APP_TOKEN / VYSTAK_TEST_NATS_URL required"
        )
    project, rg = azure_project
    with (project / ".env").open("a") as f:
        f.write(
            f"SLACK_BOT_TOKEN={bot}\nSLACK_APP_TOKEN={app}\n"
            f"VYSTAK_TEST_NATS_URL={url}\n"
        )
    return project, rg


def test_A8_full_cycle(full_env):
    project, rg_name = full_env
    kv_name = f"vystaksmoke{uuid.uuid4().hex[:8]}"
    (project / "vystak.yaml").write_text(
        A8_YAML_TEMPLATE.format(rg_name=rg_name, kv_name=kv_name)
    )

    assert_plan_ok(
        cwd=project,
        expect_sections=["Vault:", "Identities:", "Grants:", "a8agent-agent", "slack-channel"],
        absent_sections=["EnvFiles:"],
    )

    # Slowest cell in the matrix — KV + 2 UAMIs + grants + 2 apps
    assert_apply_ok(cwd=project, timeout=1800)
    assert app_exists("a8agent", rg_name)

    # Both UAMIs created
    result = run(
        ["az", "identity", "list", "-g", rg_name, "--query", "[].name", "-o", "tsv"],
        check=True, timeout=30,
    )
    names = set(result.stdout.strip().splitlines())
    assert any("a8agent" in n for n in names), f"missing agent UAMI: {names}"
    assert any("slack" in n for n in names), f"missing slack UAMI: {names}"

    # V3 — cross-principal isolation via secretRef scoping
    assert_env_contains("a8agent", rg_name, "ANTHROPIC_API_KEY")
    assert_env_contains("a8agent", rg_name, "VYSTAK_TEST_NATS_URL")
    assert_env_absent("a8agent", rg_name, "SLACK_BOT_TOKEN")

    vystak(
        ["destroy", "--delete-vault", "--include-resources", "--no-wait"],
        cwd=project, check=False,
    )
