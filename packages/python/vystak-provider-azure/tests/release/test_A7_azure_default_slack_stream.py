"""Cell A7 — azure × default × slack × stream (edge tier).

A3 + NATS. Default-path secrets + Slack channel + external NATS.

Requires Azure + Slack + VYSTAK_TEST_NATS_URL.
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

pytestmark = [
    pytest.mark.release_integration,  # Edge; runs alongside integration
    pytest.mark.release_slack,
]


A7_YAML_TEMPLATE = """\
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
  - name: a7agent
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


def test_A7_full_cycle(full_env):
    project, rg_name = full_env
    (project / "vystak.yaml").write_text(A7_YAML_TEMPLATE.format(rg_name=rg_name))

    assert_plan_ok(
        cwd=project,
        expect_sections=["EnvFiles:", "a7agent-agent", "slack-channel"],
        absent_sections=["Vault:"],
    )

    assert_apply_ok(cwd=project, timeout=1200)
    assert app_exists("a7agent", rg_name)
    assert_env_contains("a7agent", rg_name, "ANTHROPIC_API_KEY")
    assert_env_absent("a7agent", rg_name, "SLACK_BOT_TOKEN")

    vystak(
        ["destroy", "--include-resources", "--no-wait"],
        cwd=project, check=False,
    )
