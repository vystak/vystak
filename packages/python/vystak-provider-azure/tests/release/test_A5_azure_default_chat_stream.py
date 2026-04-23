"""Cell A5 — azure × default × chat × stream (NATS).

Integration tier. A1 + NATS transport. Unlike Docker where the
provider auto-provisions a `vystak-nats` container, Azure requires an
**external NATS endpoint** — declare it via `transport.connection.url_env`
pointing to a secret holding the connection URL.

**Prereq beyond A1:** a NATS server reachable from the ACA egress,
URL in VYSTAK_TEST_NATS_URL env var. Skip if not set.

This cell is the thinnest "we haven't broken NATS on Azure" smoke —
real end-to-end message flow requires the external NATS host to be
reachable and a test harness that subscribes to subjects. We verify
that the provider threads the NATS URL into agent env, the ACA app
starts, and /health returns 200. Sending a message through NATS is
a manual check (or a future integration harness).
"""

from __future__ import annotations

import os

import pytest

from .conftest import (
    app_exists,
    assert_apply_ok,
    assert_env_contains,
    assert_health_azure,
    assert_plan_ok,
    vystak,
)

pytestmark = [pytest.mark.release_integration]


A5_YAML_TEMPLATE = """\
providers:
  azure:
    type: azure
    config:
      location: eastus2
      resource_group: {rg_name}
  anthropic: {{type: anthropic}}
platforms:
  aca:
    type: container-apps
    provider: azure
    transport:
      name: nats-transport
      type: nats
      connection:
        url_env: VYSTAK_TEST_NATS_URL
      config:
        type: nats
        subject_prefix: "vystak"
models:
  sonnet: {{provider: anthropic, model_name: claude-sonnet-4-20250514}}
channels:
  - name: chat
    type: chat
    platform: aca
agents:
  - name: a5agent
    model: sonnet
    platform: aca
    secrets:
      - {{name: ANTHROPIC_API_KEY}}
      - {{name: ANTHROPIC_API_URL}}
      - {{name: VYSTAK_TEST_NATS_URL}}
"""


@pytest.fixture
def nats_env(azure_project):
    url = os.environ.get("VYSTAK_TEST_NATS_URL")
    if not url:
        pytest.skip(
            "VYSTAK_TEST_NATS_URL env var not set — A5 needs an external "
            "NATS endpoint reachable from ACA egress"
        )
    project, rg = azure_project
    with (project / ".env").open("a") as f:
        f.write(f"VYSTAK_TEST_NATS_URL={url}\n")
    return project, rg


def test_A5_full_cycle(nats_env):
    project, rg_name = nats_env
    (project / "vystak.yaml").write_text(A5_YAML_TEMPLATE.format(rg_name=rg_name))

    assert_plan_ok(
        cwd=project,
        expect_sections=["EnvFiles:", "a5agent-agent"],
        absent_sections=["Vault:"],
    )

    assert_apply_ok(cwd=project, timeout=1200)
    assert app_exists("a5agent", rg_name)

    # V3 — ANTHROPIC_* in env
    assert_env_contains("a5agent", rg_name, "ANTHROPIC_API_KEY")
    # V7 — NATS URL wired (secretRef → value resolved at runtime)
    assert_env_contains("a5agent", rg_name, "VYSTAK_TEST_NATS_URL")

    # V4 — /health OK
    assert_health_azure("a5agent", rg_name)

    vystak(
        ["destroy", "--include-resources", "--no-wait"],
        cwd=project, check=False,
    )
