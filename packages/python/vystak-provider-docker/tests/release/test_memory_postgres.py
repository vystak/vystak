"""D1-shape + Postgres memory store.

Integration tier. Same shape as sessions-postgres but declares
`memory:` instead of `sessions:`. The provider wires MEMORY_STORE_URL
into the agent env.
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_apply_ok,
    assert_health,
    assert_plan_ok,
    docker_exec,
    docker_running,
    vystak,
)

pytestmark = [pytest.mark.release_integration, pytest.mark.docker]


MEMORY_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
channels:
  - name: chat
    type: chat
    platform: local
agents:
  - name: memoryagent
    model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
      - {name: ANTHROPIC_API_URL}
    memory:
      name: memory-db
      type: postgres
      provider:
        name: docker
        type: docker
"""


def test_memory_postgres(postgres_clean, project):
    (project / "vystak.yaml").write_text(MEMORY_YAML)

    assert_plan_ok(
        cwd=project,
        expect_sections=["EnvFiles:", "memoryagent-agent"],
        absent_sections=["Vault:"],
    )

    assert_apply_ok(cwd=project)
    assert docker_running("vystak-memoryagent")

    from subprocess import run
    ps = run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=True,
    ).stdout
    memory_names = [
        name for name in ps.splitlines()
        if name.startswith("vystak-") and "memory" in name.lower()
    ]
    assert memory_names, (
        f"no Postgres memory-store container found. Running:\n{ps}"
    )

    agent_env = docker_exec("vystak-memoryagent", "env")
    assert "MEMORY_STORE_URL=" in agent_env, (
        f"agent env missing MEMORY_STORE_URL:\n{agent_env}"
    )
    assert "postgresql://" in agent_env or "postgres://" in agent_env

    assert_health("vystak-memoryagent")

    vystak(["destroy", "--include-resources"], cwd=project, check=False)
