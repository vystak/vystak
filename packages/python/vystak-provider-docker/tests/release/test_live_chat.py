"""Live chat — real LLM round-trip.

Auto-skips unless host env has a real ANTHROPIC_API_KEY (non-sentinel)
and ANTHROPIC_API_URL. Sends a deterministic prompt and asserts the
response contains the expected tag. Costs ~1–5 cents per run.

Separate from the smoke-tier V6 (which asserts only the A2A envelope
shape). This test answers "does chatting actually work?" — the smoke
tier answers "is the pipeline plumbed correctly?".

Run with: `uv run pytest ... -m release_live_chat`
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

import pytest

from .conftest import (
    assert_apply_ok,
    container_http_port,
    docker_running,
    vystak,
    wait_for_http,
)

pytestmark = [pytest.mark.release_live_chat, pytest.mark.docker]


_SENTINEL_MARKERS = ("sentinel", "your-", "<your", "fake", "test-")


def _looks_real(value: str | None) -> bool:
    if not value:
        return False
    low = value.lower()
    return not any(m in low for m in _SENTINEL_MARKERS)


LIVE_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker}
models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-4-20250514
channels:
  - name: chat
    type: chat
    platform: local
agents:
  - name: livechat
    instructions: |
      You are a test assistant. When you receive any user message,
      respond with EXACTLY the single word "pong" and nothing else.
      No punctuation, no quotes, no explanation.
    model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
      - {name: ANTHROPIC_API_URL}
"""


@pytest.fixture
def live_env(project):
    """Overwrite the sentinel .env with real credentials from the host."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    url = os.environ.get("ANTHROPIC_API_URL", "https://api.anthropic.com")
    if not _looks_real(key):
        pytest.skip(
            "ANTHROPIC_API_KEY not set or looks like a sentinel — live "
            "chat test requires real credentials"
        )
    (project / ".env").write_text(
        f"ANTHROPIC_API_KEY={key}\nANTHROPIC_API_URL={url}\n"
    )
    return project


def test_live_chat_round_trip(live_env):
    project = live_env
    (project / "vystak.yaml").write_text(LIVE_YAML)

    assert_apply_ok(cwd=project)
    assert docker_running("vystak-livechat"), "agent container not running"

    # Wait for the agent to be healthy before sending the prompt.
    port = container_http_port("vystak-livechat", 8000)
    wait_for_http(f"http://localhost:{port}/health", timeout=30)

    # Send the deterministic prompt via A2A.
    body = {
        "jsonrpc": "2.0",
        "id": "live-1",
        "method": "tasks/send",
        "params": {
            "id": "t-live-1",
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "respond now"}],
            },
        },
    }
    req = urllib.request.Request(
        f"http://localhost:{port}/a2a",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    # First LLM call can take a few seconds on cold start.
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode())
    dt = time.monotonic() - t0

    # The response must be a successful result — not an error envelope.
    assert "error" not in resp, (
        f"live chat returned error envelope "
        f"(likely credential issue): {resp.get('error')}"
    )
    result = resp.get("result", {})
    status = result.get("status", {})
    state = status.get("state")
    message = status.get("message", {})
    parts = message.get("parts", [])
    text = " ".join(p.get("text", "") for p in parts).strip().lower()

    assert state == "completed", (
        f"task did not complete (state={state!r}); full response: {resp}"
    )
    assert "pong" in text, (
        f"expected 'pong' in response, got {text!r} (full: {resp})"
    )

    # Informational — surfaces LLM round-trip latency in test output.
    print(f"\n  LLM round-trip: {dt:.2f}s; response snippet: {text[:80]!r}")

    vystak(["destroy"], cwd=project, check=False)
