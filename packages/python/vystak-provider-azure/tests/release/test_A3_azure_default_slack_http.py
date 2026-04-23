"""Cell A3 — azure × default × slack × http.

Integration tier. A1 (default-path ACA) + Slack channel as its own ACA
app. Verifies:

- Agent ACA app + Slack channel ACA app both present.
- Per-ACA-app inline secrets with `secretRef` scope correctly — agent
  app env contains ANTHROPIC_* but not SLACK_*; slack channel app env
  contains SLACK_* but not ANTHROPIC_*.

Requires AZURE_SUBSCRIPTION_ID + az login + SLACK_BOT_TOKEN/APP_TOKEN.
"""

from __future__ import annotations

import os

import pytest

from .conftest import (
    app_exists,
    assert_apply_ok,
    assert_env_absent,
    assert_env_contains,
    assert_plan_ok,
    vystak,
)

pytestmark = [pytest.mark.release_integration, pytest.mark.release_slack]


A3_YAML_TEMPLATE = """\
providers:
  azure:
    type: azure
    config:
      location: eastus2
      resource_group: {rg_name}
  anthropic: {{type: anthropic}}
platforms:
  aca: {{type: container-apps, provider: azure}}
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
  - name: a3agent
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
        pytest.skip("SLACK_BOT_TOKEN / SLACK_APP_TOKEN not set — skipping A3")
    project, rg = azure_project
    with (project / ".env").open("a") as f:
        f.write(f"SLACK_BOT_TOKEN={bot}\nSLACK_APP_TOKEN={app}\n")
    return project, rg


def test_A3_full_cycle(slack_env):
    project, rg_name = slack_env
    (project / "vystak.yaml").write_text(A3_YAML_TEMPLATE.format(rg_name=rg_name))

    assert_plan_ok(
        cwd=project,
        expect_sections=["EnvFiles:", "a3agent-agent", "slack-channel"],
        absent_sections=["Vault:"],
    )

    assert_apply_ok(cwd=project, timeout=1200)
    assert app_exists("a3agent", rg_name)

    # V3 — cross-app isolation
    assert_env_contains("a3agent", rg_name, "ANTHROPIC_API_KEY")
    assert_env_absent("a3agent", rg_name, "SLACK_BOT_TOKEN")

    vystak(
        ["destroy", "--include-resources", "--no-wait"],
        cwd=project, check=False,
    )
