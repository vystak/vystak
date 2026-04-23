"""Cell D2 — docker × vault × chat × http.

Smoke tier. Same as D1 + a `vault:` block. Verifies the HashiCorp
Vault path still works end-to-end: Vault server boots, unseals,
per-principal AppRole + Vault Agent sidecars render secrets, agent
container reads from /shared/secrets.env via the entrypoint shim.
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_a2a_accepts_task,
    assert_agent_card,
    assert_apply_ok,
    assert_health,
    assert_plan_ok,
    docker_exec,
    docker_running,
    vystak,
)

pytestmark = [pytest.mark.release_smoke, pytest.mark.docker]


D2_YAML = """\
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
  - name: chat
    type: chat
    platform: local
agents:
  - name: vaultagent
    model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
      - {name: ANTHROPIC_API_URL}
"""


def test_D2_full_cycle(project):
    (project / "vystak.yaml").write_text(D2_YAML)

    # V1 — plan: Vault/AppRoles/Secrets/Policies sections present,
    # no EnvFiles section.
    assert_plan_ok(
        cwd=project,
        expect_sections=["Vault:", "AppRoles:", "Secrets:", "Policies:", "vaultagent-agent"],
        absent_sections=["EnvFiles:"],
    )

    # V2 — apply; Vault stack stands up (server, unseal, KV setup,
    # AppRole, sidecar, agent container).
    assert_apply_ok(cwd=project)
    assert docker_running("vystak-vault"), "Vault server not running"
    assert docker_running("vystak-vaultagent"), "agent container not running"
    assert docker_running("vystak-vaultagent-agent-vault-agent"), "sidecar not running"

    # init.json materialized with 0600
    init_json = project / ".vystak" / "vault" / "init.json"
    assert init_json.exists(), "init.json not written"
    assert init_json.stat().st_mode & 0o777 == 0o600, "init.json perms != 600"

    # V3 — secrets delivered via /shared/secrets.env (Vault path);
    # inspecting env of the agent container should show both keys
    # after the entrypoint shim has sourced the file.
    env = docker_exec("vystak-vaultagent", "env")
    assert "ANTHROPIC_API_KEY=" in env
    assert "ANTHROPIC_API_URL=" in env

    # V4, V5, V6
    assert_health("vystak-vaultagent")
    assert_agent_card("vystak-vaultagent")
    assert_a2a_accepts_task("vystak-vaultagent")

    # V9 — destroy preserves Vault + init.json by default; we want to
    # verify the agent is gone and init.json still present (the design
    # explicitly avoids nuking unseal keys on accident).
    vystak(["destroy"], cwd=project)
    assert not docker_running("vystak-vaultagent")
    assert init_json.exists(), "init.json should be preserved by default"
    # Cleanup: also tear down Vault so we don't pollute other tests
    vystak(["destroy", "--delete-vault"], cwd=project, check=False)
    assert not init_json.exists(), "--delete-vault should remove init.json"
