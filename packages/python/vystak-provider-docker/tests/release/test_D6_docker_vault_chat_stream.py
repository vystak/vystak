"""Cell D6 — docker × vault × chat × stream (NATS).

Integration tier. Combines D2 (Vault) + D4 (NATS transport).

Verifies the two opt-in paths compose cleanly — Vault secrets delivered
via sidecar AND east-west traffic routed via NATS. Four containers
run in total: vystak-vault, vystak-nats, vystak-d6agent-agent-vault-agent,
vystak-d6agent, plus the chat channel.
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_a2a_accepts_task,
    assert_apply_ok,
    assert_health,
    assert_plan_ok,
    docker_exec,
    docker_running,
    vystak,
)

pytestmark = [pytest.mark.release_integration, pytest.mark.docker]


D6_YAML = """\
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
  - name: chat
    type: chat
    platform: local
agents:
  - name: d6agent
    model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
      - {name: ANTHROPIC_API_URL}
"""


def test_D6_full_cycle(vault_clean, project):
    (project / "vystak.yaml").write_text(D6_YAML)

    # V1 — both Vault and transport wiring reflected
    assert_plan_ok(
        cwd=project,
        expect_sections=["Vault:", "AppRoles:", "d6agent-agent"],
        absent_sections=["EnvFiles:"],
    )

    # V2 — all four "infrastructure" containers
    assert_apply_ok(cwd=project)
    for name in (
        "vystak-vault",
        "vystak-nats",
        "vystak-d6agent",
        "vystak-d6agent-agent-vault-agent",
    ):
        assert docker_running(name), f"{name} not running"

    # V3 — secrets delivered via Vault (read from /shared/secrets.env)
    secrets_env = docker_exec("vystak-d6agent", "cat /shared/secrets.env")
    assert "ANTHROPIC_API_KEY=" in secrets_env

    # V7 — NATS transport still wired alongside Vault
    agent_env = docker_exec("vystak-d6agent", "env")
    assert "VYSTAK_TRANSPORT_TYPE=nats" in agent_env
    assert "VYSTAK_NATS_URL=nats://vystak-nats:4222" in agent_env

    # V4, V6 — agent is still HTTP-serving for A2A in-band
    assert_health("vystak-d6agent")
    assert_a2a_accepts_task("vystak-d6agent")

    # V9
    vystak(["destroy", "--delete-vault"], cwd=project, check=False)
