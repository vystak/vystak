"""Cell D4 — docker × default × chat × stream (NATS).

Smoke tier. Same as D1 plus `platform.transport: {type: nats}`. The
provider auto-provisions a `vystak-nats` broker container and threads
the URL into the agent + channel env.

V7 (transport inspection) has a stream-specific assertion here:
`docker exec vystak-nats nats-server --version` confirms the broker
is alive and `VYSTAK_TRANSPORT_TYPE=nats` is wired into the agent env.
A stronger test would subscribe to `vystak.>` and send a message
through the channel, but the cleanest way to exercise that is through
the channel server, which we don't drive in smoke. Integration tier
(D6) would add that.
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_a2a_accepts_task,
    assert_apply_ok,
    assert_destroy_ok,
    assert_health,
    assert_plan_ok,
    docker_exec,
    docker_running,
)

pytestmark = [pytest.mark.release_smoke, pytest.mark.docker]


D4_YAML = """\
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
  - name: chat
    type: chat
    platform: local
agents:
  - name: streamagent
    model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
      - {name: ANTHROPIC_API_URL}
"""


def test_D4_full_cycle(project):
    (project / "vystak.yaml").write_text(D4_YAML)

    # V1 — plan
    assert_plan_ok(
        cwd=project,
        expect_sections=["EnvFiles:", "streamagent-agent"],
        absent_sections=["Vault:", "Orphan resources"],
    )

    # V2 — apply; expect NATS broker in addition to agent + channel
    assert_apply_ok(cwd=project)
    assert docker_running("vystak-streamagent")
    assert docker_running("vystak-channel-chat")
    assert docker_running("vystak-nats"), "NATS broker not running"

    # V3 (abbreviated — full coverage via D1)
    env = docker_exec("vystak-streamagent", "env")
    assert "ANTHROPIC_API_KEY=" in env

    # V7 — transport: agent env is wired for NATS; broker is reachable.
    assert "VYSTAK_TRANSPORT_TYPE=nats" in env, (
        f"expected VYSTAK_TRANSPORT_TYPE=nats, got:\n{env}"
    )
    assert "VYSTAK_NATS_URL=nats://vystak-nats:4222" in env
    # Channel also gets the same wiring
    channel_env = docker_exec("vystak-channel-chat", "env")
    assert "VYSTAK_TRANSPORT_TYPE=nats" in channel_env

    # V4 + V6 still work over the exposed /health and /a2a HTTP
    # surfaces even when the channel↔agent hop uses NATS.
    assert_health("vystak-streamagent")
    assert_a2a_accepts_task("vystak-streamagent")

    # V9
    assert_destroy_ok(cwd=project)
    assert not docker_running("vystak-streamagent")
    # vystak-nats is shared infra — not destroyed per-agent.
