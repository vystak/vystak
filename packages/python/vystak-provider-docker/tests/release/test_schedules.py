"""Release integration cells — declarative + runtime scheduled tasks.

Exercises the vystak-heartbeat scheduler REST API (127.0.0.1:9797) end to
end: a declarative `schedules:` entry firing on its own, a runtime one-shot
task created via POST /tasks, and a runtime cron task surviving a
`vystak-heartbeat` container restart.

Sentinel API keys throughout — no real LLM call is needed. The agent's
LangGraph node raises on the 401 from api.anthropic.com, but
`LangGraphExecutor.execute()` catches that and calls `updater.failed()`
with an "Error: ..." message rather than letting the exception escape, so
the A2A `/a2a` endpoint still returns a normal 200 JSON-RPC envelope.
`TaskScheduler._fire_one` calls `record_fire()` on that reply regardless of
its text, so `last_fire_at` (and, for one-shots, `status="completed"`) gets
set even though the reply itself is an auth-error string. Verified manually
against a live deploy before writing these assertions.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from .conftest import assert_apply_ok, docker_running, run, vystak, wait_for_http

pytestmark = [pytest.mark.release_integration, pytest.mark.docker]


SCHEDULER_URL = "http://127.0.0.1:9797"
AGENT_CANONICAL = "sched-bot.agents.dev"

SCHED_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker, namespace: dev}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: sched-bot
    framework: langchain-python
    instructions: "Reply with the word TICK when asked to."
    default_model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
      - {name: ANTHROPIC_API_URL}
    schedules:
      - name: tick
        every: 30s
        prompt: "Reply with the word TICK."
        target_channel: schedchat.channels.dev
        target_thread: sched-room
channels:
  - name: schedchat
    type: chat
    platform: local
    agents: [sched-bot]
    default_agent: sched-bot
"""


def _deploy(project: Path) -> None:
    """Scaffold + apply the shared schedules project.

    `vystak apply` requires a scaffolded `_vystak/` tree (the no-codegen
    pivot's apply-time validation) — init first, matching the real user
    workflow documented in CLAUDE.md, then overwrite the template's default
    vystak.yaml with ours. --force is required because the `project`
    fixture pre-creates `.env` + `tools/`, making the target dir non-empty.
    (D1's and heartbeat_v2's bare-yaml-then-apply pattern predates this
    validation and is stale against current main — see
    test_workspace_tools_v11.py's comment on the same issue.)
    """
    vystak(["init", "--framework", "langchain-python", "--force", "."], cwd=project)
    (project / "vystak.yaml").write_text(SCHED_YAML)
    assert_apply_ok(cwd=project)
    assert docker_running("vystak-heartbeat"), "vystak-heartbeat not running"
    assert docker_running("vystak-sched-bot"), "sched-bot agent container not running"
    assert docker_running("vystak-channel-schedchat"), "chat channel container not running"
    # `docker ps` shows the container as running the instant the process
    # starts, but uvicorn takes a beat to bind port 8081 — poll /healthz
    # rather than racing the very first /tasks request against that gap.
    wait_for_http(f"{SCHEDULER_URL}/healthz", timeout=30)


def _get_json(url: str, timeout: int = 5) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post_json(url: str, body: dict, timeout: int = 10) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def _tasks_for_agent(agent: str) -> list[dict]:
    qs = urllib.parse.urlencode({"agent": agent})
    return _get_json(f"{SCHEDULER_URL}/tasks?{qs}")["tasks"]


def _find(tasks: list[dict], name: str) -> dict | None:
    for t in tasks:
        if t["name"] == name:
            return t
    return None


def test_declarative_schedule_fires(project: Path, docker_required, scheduler_clean):
    """The declarative `tick` schedule (every 30s) fires within 90s of apply."""
    _deploy(project)

    deadline = time.monotonic() + 90
    fired = None
    while time.monotonic() < deadline:
        tasks = _tasks_for_agent(AGENT_CANONICAL)
        task = _find(tasks, "tick")
        assert task is not None, f"'tick' task missing from /tasks: {tasks}"
        if task.get("last_fire_at"):
            fired = task
            break
        time.sleep(3)

    assert fired is not None, (
        "declarative 'tick' schedule never fired within 90s: "
        f"{_tasks_for_agent(AGENT_CANONICAL)}"
    )
    assert fired["source"] == "declarative"
    assert fired["status"] == "active"  # recurring — never "completed"


def test_runtime_oneshot_fires_and_completes(project: Path, docker_required, scheduler_clean):
    """A runtime one-shot task (POST /tasks with `at`) fires and completes."""
    _deploy(project)

    at = (datetime.now(UTC) + timedelta(seconds=10)).isoformat()
    status, body = _post_json(
        f"{SCHEDULER_URL}/tasks",
        {
            "agent": AGENT_CANONICAL,
            "name": "once",
            "at": at,
            "prompt": "Reply DONE.",
            "created_by": "release-test",
        },
    )
    assert status == 201, f"POST /tasks failed: {status} {body}"
    task_id = body["id"]

    deadline = time.monotonic() + 60
    final = None
    while time.monotonic() < deadline:
        rec = _get_json(f"{SCHEDULER_URL}/tasks/{task_id}")
        if rec["status"] == "completed" and rec.get("last_fire_at"):
            final = rec
            break
        time.sleep(2)

    assert final is not None, (
        f"one-shot task never completed within 60s: "
        f"{_get_json(f'{SCHEDULER_URL}/tasks/{task_id}')}"
    )
    assert final["source"] == "runtime"


def test_runtime_task_survives_scheduler_restart(project: Path, docker_required, scheduler_clean):
    """A runtime cron task persists across a `vystak-heartbeat` restart."""
    _deploy(project)

    status, body = _post_json(
        f"{SCHEDULER_URL}/tasks",
        {
            "agent": AGENT_CANONICAL,
            "name": "weekly",
            "cron": "0 9 * * 1",
            "prompt": "Weekly nudge.",
            "created_by": "release-test",
        },
    )
    assert status == 201, f"POST /tasks failed: {status} {body}"
    task_id = body["id"]

    run(["docker", "restart", "vystak-heartbeat"], check=True)
    wait_for_http(f"{SCHEDULER_URL}/healthz", timeout=60)

    rec = _get_json(f"{SCHEDULER_URL}/tasks/{task_id}")
    assert rec["source"] == "runtime"
    assert rec["status"] == "active"
