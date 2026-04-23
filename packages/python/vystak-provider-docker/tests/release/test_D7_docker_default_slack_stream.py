"""Cell D7 — docker × default × slack × stream (NATS).

Integration tier. Combines D3 (Slack) + D4 (NATS).

Verifies: default-path secret delivery (--env-file equivalent via
docker run `environment=`) composes with a Slack channel that also
uses NATS east-west traffic.

Requires SLACK_BOT_TOKEN + SLACK_APP_TOKEN (auto-skip).
"""

from __future__ import annotations

import os

import pytest

from .conftest import (
    assert_apply_ok,
    assert_isolation,
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


D7_YAML = """\
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
  - name: d7agent
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
        pytest.skip("SLACK_BOT_TOKEN / SLACK_APP_TOKEN not set — skipping D7")
    with (project / ".env").open("a") as f:
        f.write(f"SLACK_BOT_TOKEN={bot}\nSLACK_APP_TOKEN={app}\n")
    return project


def test_D7_full_cycle(slack_env):
    project = slack_env
    (project / "vystak.yaml").write_text(D7_YAML)

    # NOTE: plan's EnvFiles section intentionally omits channel rows
    # (PR #5 Round-2) because the default-path graph doesn't create
    # per-channel env-file nodes — channels get secrets via the
    # DockerChannelNode's own `os.environ` passthrough. So we only
    # assert the agent row here; channel secret delivery is verified
    # at V3 below.
    assert_plan_ok(
        cwd=project,
        expect_sections=["EnvFiles:", "d7agent-agent"],
        absent_sections=["Vault:", "Orphan resources", "slack-channel"],
    )

    assert_apply_ok(cwd=project)
    for name in ("vystak-d7agent", "vystak-channel-slack", "vystak-nats"):
        assert docker_running(name), f"{name} not running"

    # V3 — default-path env scoping across two principals
    assert_isolation(
        containers_to_secrets={
            "vystak-d7agent": {"ANTHROPIC_API_KEY", "ANTHROPIC_API_URL"},
            "vystak-channel-slack": {"SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"},
        },
        forbidden_per_container={
            "vystak-d7agent": {"SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"},
            "vystak-channel-slack": {"ANTHROPIC_API_KEY", "ANTHROPIC_API_URL"},
        },
    )

    # V7 — both containers wired for NATS
    agent_env = docker_exec("vystak-d7agent", "env")
    channel_env = docker_exec("vystak-channel-slack", "env")
    assert "VYSTAK_TRANSPORT_TYPE=nats" in agent_env
    assert "VYSTAK_TRANSPORT_TYPE=nats" in channel_env

    vystak(["destroy"], cwd=project, check=False)
