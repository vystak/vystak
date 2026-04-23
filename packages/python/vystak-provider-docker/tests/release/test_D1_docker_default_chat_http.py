"""Cell D1 — docker × default × chat × http.

Smoke tier. Reference implementation — every other smoke cell delta
is expressed as "same as D1, plus/minus X" in test_plan.md.

Exercises V1 (plan), V2 (apply), V3 (isolation), V4 (health),
V5 (agent card), V6 (A2A accepts task), V9 (destroy). V7 (transport
inspection) is trivial for HTTP — request succeeds = transport works;
we don't grep container logs. V8 (rotation) is worth testing once per
tier — deferred to a companion test.
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_a2a_accepts_task,
    assert_agent_card,
    assert_apply_ok,
    assert_destroy_ok,
    assert_health,
    assert_isolation,
    assert_plan_ok,
    docker_running,
)

pytestmark = [pytest.mark.release_smoke, pytest.mark.docker]


D1_YAML = """\
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
  - name: smokeagent
    model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
      - {name: ANTHROPIC_API_URL}
"""


def test_D1_full_cycle(project):
    """V1 → V9 in one pass. Running the stages as separate tests would
    mean 7× `vystak apply` per cell — unacceptable wall time.
    """
    (project / "vystak.yaml").write_text(D1_YAML)

    # V1 — plan: default-path EnvFiles section, no Vault sections,
    # no orphan warnings (clean worktree).
    assert_plan_ok(
        cwd=project,
        expect_sections=["EnvFiles:", "smokeagent-agent"],
        absent_sections=["Vault:", "Identities:", "Grants:", "Orphan resources"],
    )

    # V2 — apply
    assert_apply_ok(cwd=project)
    assert docker_running("vystak-smokeagent"), "agent container not running"
    assert docker_running("vystak-channel-chat"), "chat channel container not running"

    # V3 — per-container env isolation
    assert_isolation(
        containers_to_secrets={
            "vystak-smokeagent": {"ANTHROPIC_API_KEY", "ANTHROPIC_API_URL"},
        },
        forbidden_per_container={
            # Nothing declared as forbidden on D1 — chat channel has no
            # secrets of its own. Left here as a slot future cells (D3,
            # A3) will populate with cross-principal forbidden lists.
            "vystak-smokeagent": set(),
        },
    )

    # V4 — /health responds
    assert_health("vystak-smokeagent")

    # V5 — agent card advertises a name (no explicit skills declared,
    # so just assert the card shape)
    card = assert_agent_card("vystak-smokeagent", expected_skills=None)
    assert card["name"] == "smokeagent"

    # V6 — A2A /a2a accepts a tasks/send request
    assert_a2a_accepts_task("vystak-smokeagent")

    # V7 — http transport: if V6 succeeded, transport works. Nothing
    # additional to verify (contrast D4 / D6 / D7 / D8 which verify
    # NATS subjects).

    # V9 — destroy cleans up
    assert_destroy_ok(cwd=project)
    assert not docker_running("vystak-smokeagent")
    assert not docker_running("vystak-channel-chat")
