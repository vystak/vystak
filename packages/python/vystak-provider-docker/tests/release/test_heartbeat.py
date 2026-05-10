"""Release integration cell — heartbeat + chat channel.

Cycle: deploy ops-bot with schedule "* * * * *" and a custom prompt
that always returns HEARTBEAT_OK. Observe the channel container's logs
to confirm heartbeat.fired + heartbeat.acked events.

Marked release_integration: requires Docker daemon. Skipped by default.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from .conftest import (
    assert_apply_ok,
    docker_running,
)

pytestmark = [pytest.mark.release_integration, pytest.mark.docker]


HEARTBEAT_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker, namespace: dev}
models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-4-20250514
agents:
  - name: hbagent
    framework: langchain-python
    instructions: "Reply only with HEARTBEAT_OK and nothing else."
    default_model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
      - {name: ANTHROPIC_API_URL}
    heartbeat:
      schedule: "* * * * *"
      target_channel: hbchat.channels.dev
      target_thread: hb-test-thread
      ack_max_chars: 300
      prompt: "Reply only HEARTBEAT_OK"
channels:
  - name: hbchat
    type: chat
    platform: local
    agents: [hbagent]
    default_agent: hbagent
"""


def _container_logs(name: str) -> str:
    """Read combined stdout+stderr from a docker container."""
    result = subprocess.run(
        ["docker", "logs", name],
        capture_output=True, text=True, check=False,
    )
    return (result.stdout or "") + (result.stderr or "")


def _wait_for_log(name: str, needle: str, timeout_s: int = 90) -> bool:
    """Poll the container's logs every 2s for `needle`. Return True if found."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if needle in _container_logs(name):
            return True
        time.sleep(2)
    return False


def test_heartbeat_fires_and_acks(project: Path):
    """Deploy a heartbeat agent with a per-minute schedule + HEARTBEAT_OK
    prompt. Confirm via channel-container logs that the runtime fires
    and acks at least once."""
    (project / "vystak.yaml").write_text(HEARTBEAT_YAML)
    assert_apply_ok(cwd=project)

    # Channel container name: vystak-channel-<channel-name> per docker provider.
    channel_container = "vystak-channel-hbchat"
    assert docker_running(channel_container), \
        f"channel container {channel_container} not running"

    # Wait up to ~90s for the first fire (schedule fires at the next
    # minute boundary; allow generous slack).
    assert _wait_for_log(channel_container, "heartbeat.fired", timeout_s=90), (
        "heartbeat.fired never appeared in channel logs:\n"
        + _container_logs(channel_container)[-2000:]
    )
    assert _wait_for_log(channel_container, "heartbeat.acked", timeout_s=90), (
        "heartbeat.acked never appeared in channel logs:\n"
        + _container_logs(channel_container)[-2000:]
    )
