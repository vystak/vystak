"""D1-shape + Postgres session storage.

Integration tier. Default-path deploy + `sessions: {type: postgres,
provider: docker}` adds a DockerServiceNode for Postgres. The provider
threads the generated connection string into the agent container's
`SESSION_STORE_URL` env var.

Verifies deploy-level wiring:
- Postgres container is running.
- Agent env has SESSION_STORE_URL pointing at the Postgres service.
- Agent /health is responsive (database connectivity is agent's
  concern; this test doesn't verify session persistence end-to-end —
  that requires multi-turn state, which the live_chat test doesn't
  currently cover but could be extended to).
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


SESSIONS_YAML = """\
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
  - name: sessionsagent
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
"""


def test_sessions_postgres(postgres_clean, project):
    (project / "vystak.yaml").write_text(SESSIONS_YAML)

    assert_plan_ok(
        cwd=project,
        expect_sections=["EnvFiles:", "sessionsagent-agent"],
        absent_sections=["Vault:"],
    )

    assert_apply_ok(cwd=project)
    assert docker_running("vystak-sessionsagent"), "agent container missing"

    # Postgres service container is running. Naming depends on the
    # DockerServiceNode — typically `vystak-<service-name>` or
    # `vystak-<service-canonical-name>`. Discover by listing.
    from subprocess import run
    ps = run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=True,
    ).stdout
    postgres_names = [
        name for name in ps.splitlines()
        if name.startswith("vystak-") and "session" in name.lower()
    ]
    assert postgres_names, (
        f"no Postgres session-store container found. Running containers:\n{ps}"
    )

    # Agent env has SESSION_STORE_URL wired.
    agent_env = docker_exec("vystak-sessionsagent", "env")
    assert "SESSION_STORE_URL=" in agent_env, (
        f"agent env missing SESSION_STORE_URL:\n{agent_env}"
    )
    # The URL should point at the Postgres service (internal DNS).
    assert "postgresql://" in agent_env or "postgres://" in agent_env, (
        "SESSION_STORE_URL doesn't look like a Postgres URL"
    )

    # V4 — agent still healthy with Postgres in the mix.
    assert_health("vystak-sessionsagent")

    vystak(["destroy", "--include-resources"], cwd=project, check=False)
