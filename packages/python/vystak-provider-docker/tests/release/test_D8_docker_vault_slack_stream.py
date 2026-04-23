"""Cell D8 — docker × vault × slack × stream (edge tier).

Full stack for local: Vault + Slack + NATS. Verifies everything
composes. Most expensive Docker cell to run; executed only when
reproducing a specific cross-feature issue.

Requires SLACK_* tokens (auto-skip).
"""

from __future__ import annotations

import os

import pytest

from .conftest import (
    assert_apply_ok,
    assert_plan_ok,
    docker_exec,
    docker_running,
    vystak,
)

pytestmark = [
    pytest.mark.release_integration,  # Edge; runs alongside integration
    pytest.mark.release_slack,
    pytest.mark.docker,
]


D8_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local:
    type: docker
    provider: docker
    transport:
      name: nats-transport
      type: nats
      config:
        type: nats
        subject_prefix: "vystak"
vault:
  name: vystak-vault
  provider: docker
  type: vault
  mode: deploy
  config: {}
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
  - name: d8agent
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
        pytest.skip("SLACK_BOT_TOKEN / SLACK_APP_TOKEN not set — skipping D8")
    with (project / ".env").open("a") as f:
        f.write(f"SLACK_BOT_TOKEN={bot}\nSLACK_APP_TOKEN={app}\n")
    return project


def test_D8_full_cycle(vault_clean, slack_env):
    project = slack_env
    (project / "vystak.yaml").write_text(D8_YAML)

    assert_plan_ok(
        cwd=project,
        expect_sections=["Vault:", "AppRoles:", "d8agent-agent", "slack-channel"],
        absent_sections=["EnvFiles:"],
    )

    assert_apply_ok(cwd=project)
    for name in (
        "vystak-vault",
        "vystak-nats",
        "vystak-d8agent",
        "vystak-channel-slack",
        "vystak-d8agent-agent-vault-agent",
        "vystak-slack-channel-vault-agent",
    ):
        assert docker_running(name), f"{name} not running"

    # V3 — isolation via /shared/secrets.env (Vault-rendered)
    agent_secrets = docker_exec("vystak-d8agent", "cat /shared/secrets.env")
    channel_secrets = docker_exec("vystak-channel-slack", "cat /shared/secrets.env")
    assert "ANTHROPIC_API_KEY=" in agent_secrets
    assert "SLACK_BOT_TOKEN=" not in agent_secrets
    assert "SLACK_BOT_TOKEN=" in channel_secrets
    assert "ANTHROPIC_API_KEY=" not in channel_secrets

    # V7 — NATS wired on both containers
    assert "VYSTAK_TRANSPORT_TYPE=nats" in docker_exec("vystak-d8agent", "env")
    assert "VYSTAK_TRANSPORT_TYPE=nats" in docker_exec("vystak-channel-slack", "env")

    vystak(["destroy", "--delete-vault"], cwd=project, check=False)
