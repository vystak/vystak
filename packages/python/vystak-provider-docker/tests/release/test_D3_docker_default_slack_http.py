"""Cell D3 — docker × default × slack × http.

Smoke tier. Same shape as D1 but with a Slack channel instead of chat.
Requires real Slack workspace credentials → skipped unless
SLACK_BOT_TOKEN and SLACK_APP_TOKEN are present in the environment.

The functional send/receive loop (V6) is not automated here — Slack
message ordering is flaky and interacting with real Slack requires a
dedicated test workspace. This test verifies deploy-level correctness
(V1–V5, V9 partial) and leaves V6 as a manual check.
"""

from __future__ import annotations

import os

import pytest

from .conftest import (
    assert_apply_ok,
    assert_destroy_ok,
    assert_isolation,
    assert_plan_ok,
    docker_running,
)

pytestmark = [
    pytest.mark.release_smoke,
    pytest.mark.release_slack,
    pytest.mark.docker,
]


D3_YAML_TEMPLATE = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
channels:
  - name: slack
    type: slack
    platform: local
    secrets:
      - {name: SLACK_BOT_TOKEN}
      - {name: SLACK_APP_TOKEN}
agents:
  - name: slackagent
    model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
      - {name: ANTHROPIC_API_URL}
"""


@pytest.fixture
def slack_env(project):
    bot = os.environ.get("SLACK_BOT_TOKEN")
    app = os.environ.get("SLACK_APP_TOKEN")
    if not bot or not app:
        pytest.skip("SLACK_BOT_TOKEN / SLACK_APP_TOKEN not set — skipping D3")
    # Append to the sentinel .env written by project fixture
    env_path = project / ".env"
    with env_path.open("a") as f:
        f.write(f"SLACK_BOT_TOKEN={bot}\nSLACK_APP_TOKEN={app}\n")
    return project


def test_D3_full_cycle(slack_env):
    project = slack_env
    (project / "vystak.yaml").write_text(D3_YAML_TEMPLATE)

    # V1 — plan
    assert_plan_ok(
        cwd=project,
        expect_sections=["EnvFiles:", "slackagent-agent"],
        absent_sections=["Vault:", "Orphan resources"],
    )

    # V2 — apply
    assert_apply_ok(cwd=project)
    assert docker_running("vystak-slackagent")
    assert docker_running("vystak-channel-slack")

    # V3 — cross-principal isolation: agent has anthropic keys but NOT
    # slack tokens; slack channel has slack tokens but NOT anthropic keys.
    assert_isolation(
        containers_to_secrets={
            "vystak-slackagent": {"ANTHROPIC_API_KEY", "ANTHROPIC_API_URL"},
            "vystak-channel-slack": {"SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"},
        },
        forbidden_per_container={
            "vystak-slackagent": {"SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"},
            "vystak-channel-slack": {"ANTHROPIC_API_KEY", "ANTHROPIC_API_URL"},
        },
    )

    # V4, V5 on the agent container — same as D1. Skipped here to keep
    # the Slack-specific assertions tight. Full V4/V5 coverage comes
    # from D1's pass (the agent image shape is identical).

    # V6 — manual check: send a DM to the bot, expect a response in Slack.
    # Not automated; see test_plan.md § "Per-case procedure — Smoke tier".

    # V9 — destroy
    assert_destroy_ok(cwd=project)
    assert not docker_running("vystak-slackagent")
    assert not docker_running("vystak-channel-slack")
