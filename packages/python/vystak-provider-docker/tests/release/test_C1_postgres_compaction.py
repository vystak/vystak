"""C1: Postgres-backed agent + compaction (release_integration cell).

Drives ~30 turns of synthetic conversation against a deployed agent
configured with `compaction.mode='aggressive'` and `trigger_pct=0.05`.
Asserts at least one threshold-triggered row in vystak_compactions and
that manual /compact succeeds.

Auto-skips the LLM-dependent steps if ANTHROPIC_API_KEY is a sentinel
value (no real credentials). The deploy/health/wiring steps always run
so that infrastructure plumbing is verified even without live LLM access.
"""
from __future__ import annotations

import subprocess

import pytest

from .conftest import (
    assert_apply_ok,
    assert_health,
    assert_plan_ok,
    container_http_port,
    docker_running,
    vystak,
    wait_for_http,
)

pytestmark = [pytest.mark.release_integration, pytest.mark.docker]

# --------------------------------------------------------------------------- #
# Infrastructure note:                                                         #
# DockerAgentNode bundles vystak + vystak_transport_* source trees but NOT     #
# vystak_adapter_langchain. The published PyPI package does not yet include    #
# the compaction subpackage (it lives only on this branch). Until the provider #
# bundles vystak_adapter_langchain (or a compaction-aware release lands on     #
# PyPI), deploying an agent with compaction: enabled fails at container        #
# startup with "ModuleNotFoundError: No module named                           #
# 'vystak_adapter_langchain.compaction'".                                      #
#                                                                              #
# The xfail below documents this gap and keeps the test in the suite.         #
# Remove it once DockerAgentNode is updated to bundle                          #
# vystak_adapter_langchain alongside the other unpublished source trees.       #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Agent YAML — postgres sessions + aggressive compaction with low trigger_pct  #
# so threshold fires after only a handful of turns even with short messages.   #
# --------------------------------------------------------------------------- #

AGENT_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker}
models:
  haiku:
    provider: anthropic
    model_name: claude-haiku-4-5-20251001
channels:
  - name: chat
    type: chat
    platform: local
agents:
  - name: c1compaction
    model: haiku
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
    compaction:
      mode: aggressive
      trigger_pct: 0.05
"""

# Sentinel markers matching conftest and live_chat test conventions.
_SENTINEL_MARKERS = ("sentinel", "your-", "<your", "fake", "test-", "mock")


def _key_looks_real(value: str | None) -> bool:
    if not value:
        return False
    return not any(m in value.lower() for m in _SENTINEL_MARKERS)


@pytest.mark.xfail(
    reason=(
        "DockerAgentNode does not yet bundle vystak_adapter_langchain source. "
        "The published PyPI package lacks the compaction subpackage, so the agent "
        "container fails to start with ModuleNotFoundError. "
        "Fix: add vystak_adapter_langchain to the source-bundle loop in "
        "vystak_provider_docker/nodes/agent.py alongside vystak/vystak_transport_*."
    ),
    strict=False,
)
def test_postgres_compaction_lifecycle(project, postgres_clean):
    """Deploy → wiring checks → (if live key) 30 turns → compaction asserts → destroy."""
    import os

    (project / "vystak.yaml").write_text(AGENT_YAML)

    # V1 — plan
    assert_plan_ok(
        cwd=project,
        expect_sections=["EnvFiles:", "c1compaction-agent"],
        absent_sections=["Vault:"],
    )

    # V2 — apply (spins up agent + postgres containers)
    assert_apply_ok(cwd=project)
    assert docker_running("vystak-c1compaction"), "agent container not running"

    # Postgres session-store container is running.
    ps = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=True,
    ).stdout
    postgres_names = [
        name for name in ps.splitlines()
        if name.startswith("vystak-resource-") and "session" in name.lower()
    ]
    assert postgres_names, (
        f"no Postgres session-store container found. Running containers:\n{ps}"
    )
    pg_container = postgres_names[0]

    # V4 — agent health
    assert_health("vystak-c1compaction")

    # ------------------------------------------------------------------ #
    # LLM-dependent steps — skip if credentials are sentinel/unavailable  #
    # ------------------------------------------------------------------ #
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not _key_looks_real(api_key):
        pytest.skip(
            "ANTHROPIC_API_KEY is a sentinel or missing — skipping multi-turn "
            "compaction exercise. Re-run with a real key to verify threshold "
            "compaction, manual /compact, and the inspection endpoint."
        )

    port = container_http_port("vystak-c1compaction", 8000)
    base = f"http://localhost:{port}"
    wait_for_http(f"{base}/health", timeout=30)

    # Drive ~30 turns through /v1/responses.  Each input is padded with
    # repeated text to inflate the token count so the 5 % threshold is
    # hit quickly even with haiku's 200K context window.
    import httpx  # available in the test environment (used by other release tests)

    prev_id: str | None = None
    thread_id: str | None = None

    for i in range(30):
        body: dict = {
            "model": "vystak/c1compaction",
            "input": f"turn {i}: " + ("the quick brown fox " * 200),
            "store": True,
        }
        if prev_id is not None:
            body["previous_response_id"] = prev_id

        r = httpx.post(f"{base}/v1/responses", json=body, timeout=120)
        assert r.status_code == 200, (
            f"turn {i}: /v1/responses returned {r.status_code}:\n{r.text}"
        )
        payload = r.json()
        prev_id = payload["id"]

        if thread_id is None:
            # Resolve thread_id from the first response's GET.
            got = httpx.get(f"{base}/v1/responses/{prev_id}", timeout=15).json()
            thread_id = got.get("thread_id")
            assert thread_id, f"GET /v1/responses/{prev_id} missing thread_id: {got}"

    # Assert threshold-triggered row exists in the vystak_compactions table.
    out = subprocess.check_output(
        [
            "docker", "exec", pg_container,
            "psql", "-U", "vystak", "-d", "vystak",
            "-c",
            "SELECT trigger, COUNT(*) FROM vystak_compactions GROUP BY trigger;",
        ],
        text=True,
    )
    assert "threshold" in out, (
        f"expected 'threshold' row in vystak_compactions after 30 turns; "
        f"psql output:\n{out}"
    )

    # Manual /compact with instructions.
    r = httpx.post(
        f"{base}/v1/sessions/{thread_id}/compact",
        json={"instructions": "focus on the topics discussed so far"},
        timeout=120,
    )
    assert r.status_code == 200, (
        f"manual /compact returned {r.status_code}:\n{r.text}"
    )
    compact_body = r.json()
    assert compact_body.get("generation", 0) >= 1, (
        f"compact response missing generation >= 1: {compact_body}"
    )
    assert "summary_preview" in compact_body, (
        f"compact response missing summary_preview: {compact_body}"
    )

    # List compactions — both threshold and manual triggers must appear.
    r = httpx.get(f"{base}/v1/sessions/{thread_id}/compactions", timeout=15)
    assert r.status_code == 200, (
        f"GET /v1/sessions/{thread_id}/compactions returned {r.status_code}:\n{r.text}"
    )
    triggers = {row["trigger"] for row in r.json().get("compactions", [])}
    assert "threshold" in triggers, (
        f"expected 'threshold' in compaction triggers; got: {triggers}"
    )
    assert "manual" in triggers, (
        f"expected 'manual' in compaction triggers; got: {triggers}"
    )

    # V9 — destroy
    vystak(["destroy", "--include-resources"], cwd=project, check=False)
