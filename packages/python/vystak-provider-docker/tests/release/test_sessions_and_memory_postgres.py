"""D1-shape + Postgres sessions AND Postgres memory.

Integration tier. Both services declared: the provider stands up two
separate Postgres containers and wires both SESSION_STORE_URL and
MEMORY_STORE_URL into the agent env. Confirms the services don't
collide on name, port, or volume.

If a future optimization shares a single Postgres across both
(same connection string), this test's assertions on DISTINCT container
names would fail — and should be rewritten at that point to assert the
new shared-infra invariant instead.
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


COMBINED_YAML = """\
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
  - name: smagent
    model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
      - {name: ANTHROPIC_API_URL}
    sessions:
      name: sessions-db
      type: postgres
      provider:
        name: docker
        type: docker
    memory:
      name: memory-db
      type: postgres
      provider:
        name: docker
        type: docker
"""


def test_sessions_and_memory_postgres(postgres_clean, project):
    (project / "vystak.yaml").write_text(COMBINED_YAML)

    assert_plan_ok(
        cwd=project,
        expect_sections=["EnvFiles:", "smagent-agent"],
        absent_sections=["Vault:"],
    )

    assert_apply_ok(cwd=project)
    assert docker_running("vystak-smagent")

    from subprocess import run
    ps = run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()

    # Two distinct Postgres services
    sessions_containers = [n for n in ps if "session" in n.lower()]
    memory_containers = [n for n in ps if "memory" in n.lower()]
    assert sessions_containers, f"no sessions Postgres: {ps}"
    assert memory_containers, f"no memory Postgres: {ps}"
    # They must be different containers (not aliased to one Postgres)
    assert set(sessions_containers).isdisjoint(set(memory_containers)), (
        f"sessions + memory resolved to overlapping containers: "
        f"sessions={sessions_containers} memory={memory_containers}"
    )

    # Agent env has BOTH URLs, and they differ (distinct containers)
    agent_env = docker_exec("vystak-smagent", "env")
    assert "SESSION_STORE_URL=" in agent_env
    assert "MEMORY_STORE_URL=" in agent_env

    session_url = next(
        line for line in agent_env.splitlines() if line.startswith("SESSION_STORE_URL=")
    )
    memory_url = next(
        line for line in agent_env.splitlines() if line.startswith("MEMORY_STORE_URL=")
    )
    assert session_url != memory_url, (
        "expected distinct connection strings for sessions vs memory"
    )

    assert_health("vystak-smagent")

    vystak(["destroy", "--include-resources"], cwd=project, check=False)
