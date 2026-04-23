"""Cell D5 — docker × vault × slack × http.

Integration tier. Combines D2 (Vault) + D3 (Slack channel). Verifies:

- Vault stack stands up (server, init, unseal, KV setup).
- The Slack channel gets its OWN principal — separate AppRole, separate
  Vault Agent sidecar, separate /shared volume. Slack tokens land in
  the channel container only; the agent container's /shared/secrets.env
  never contains them.
- The agent's secrets (ANTHROPIC_*) are scoped to the agent principal,
  not leaked to the slack channel principal.

Requires SLACK_BOT_TOKEN + SLACK_APP_TOKEN (auto-skip otherwise).
V6 (real Slack DM round-trip) is manual — see test_plan.md.
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
    pytest.mark.release_integration,
    pytest.mark.release_slack,
    pytest.mark.docker,
]


D5_YAML = """\
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
channels:
  - name: slack
    type: slack
    platform: local
    secrets:
      - {name: SLACK_BOT_TOKEN}
      - {name: SLACK_APP_TOKEN}
agents:
  - name: d5agent
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
        pytest.skip("SLACK_BOT_TOKEN / SLACK_APP_TOKEN not set — skipping D5")
    with (project / ".env").open("a") as f:
        f.write(f"SLACK_BOT_TOKEN={bot}\nSLACK_APP_TOKEN={app}\n")
    return project


def test_D5_full_cycle(vault_clean, slack_env):
    project = slack_env
    (project / "vystak.yaml").write_text(D5_YAML)

    # V1 — Hashi sections + slack channel principal in AppRoles
    assert_plan_ok(
        cwd=project,
        expect_sections=["Vault:", "AppRoles:", "d5agent-agent", "slack-channel"],
        absent_sections=["EnvFiles:"],
    )

    # V2 — apply with full Vault + per-principal sidecars
    assert_apply_ok(cwd=project)
    assert docker_running("vystak-vault")
    assert docker_running("vystak-d5agent")
    assert docker_running("vystak-channel-slack")
    assert docker_running("vystak-d5agent-agent-vault-agent")
    # Slack channel has its own sidecar too
    assert docker_running("vystak-slack-channel-vault-agent"), (
        "slack channel vault-agent sidecar missing — cross-principal "
        "isolation requires per-channel AppRole"
    )

    # V3 — agent's /shared/secrets.env has ANTHROPIC only
    agent_secrets = docker_exec("vystak-d5agent", "cat /shared/secrets.env")
    assert "ANTHROPIC_API_KEY=" in agent_secrets
    assert "SLACK_BOT_TOKEN=" not in agent_secrets, (
        "agent /shared/secrets.env leaked Slack tokens"
    )
    # Channel's /shared/secrets.env has Slack only
    channel_secrets = docker_exec("vystak-channel-slack", "cat /shared/secrets.env")
    assert "SLACK_BOT_TOKEN=" in channel_secrets
    assert "ANTHROPIC_API_KEY=" not in channel_secrets, (
        "slack channel /shared/secrets.env leaked ANTHROPIC_API_KEY"
    )

    # V6 — manual (real Slack round-trip)
    # V7 — http transport implicit through V2/V3 success

    # V9 — teardown + remove Vault
    vystak(["destroy", "--delete-vault"], cwd=project, check=False)
