"""Cell A6 — azure × keyvault × chat × stream (edge tier).

A2 + external NATS. Key Vault for secrets + NATS for east-west. Both
opt-in paths combined on Azure.

Requires AZURE_SUBSCRIPTION_ID + az login + VYSTAK_TEST_NATS_URL.
"""

from __future__ import annotations

import os
import uuid

import pytest

from .conftest import (
    app_exists,
    assert_apply_ok,
    assert_env_contains,
    assert_health_azure,
    assert_plan_ok,
    vystak,
)

pytestmark = [pytest.mark.release_integration]  # Edge; runs alongside integration


A6_YAML_TEMPLATE = """\
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
  - name: chat
    type: chat
    platform: aca
agents:
  - name: a6agent
    model: sonnet
    platform: aca
    secrets:
      - {{name: ANTHROPIC_API_KEY}}
      - {{name: ANTHROPIC_API_URL}}
      - {{name: VYSTAK_TEST_NATS_URL}}
"""


@pytest.fixture
def nats_env(azure_project):
    url = os.environ.get("VYSTAK_TEST_NATS_URL")
    if not url:
        pytest.skip("VYSTAK_TEST_NATS_URL not set — skipping A6")
    project, rg = azure_project
    with (project / ".env").open("a") as f:
        f.write(f"VYSTAK_TEST_NATS_URL={url}\n")
    return project, rg


def test_A6_full_cycle(nats_env):
    project, rg_name = nats_env
    kv_name = f"vystaksmoke{uuid.uuid4().hex[:8]}"
    (project / "vystak.yaml").write_text(
        A6_YAML_TEMPLATE.format(rg_name=rg_name, kv_name=kv_name)
    )

    assert_plan_ok(
        cwd=project,
        expect_sections=["Vault:", "Identities:", "a6agent-agent"],
        absent_sections=["EnvFiles:"],
    )

    assert_apply_ok(cwd=project, timeout=1500)
    assert app_exists("a6agent", rg_name)
    assert_env_contains("a6agent", rg_name, "ANTHROPIC_API_KEY")
    assert_env_contains("a6agent", rg_name, "VYSTAK_TEST_NATS_URL")
    assert_health_azure("a6agent", rg_name)

    vystak(
        ["destroy", "--delete-vault", "--include-resources", "--no-wait"],
        cwd=project, check=False,
    )
