"""End-to-end smoke test: real Docker, real containers, real HTTP.

Opt-in: run with `uv run pytest -m docker`. Default test runs skip it.

Flow:
1. `vystak apply` on a minimal definition (agent + chat channel)
2. Verify agent container + chat channel container are running
3. curl chat `/health` and `/v1/models` endpoints
4. `vystak destroy` and verify containers removed

The agent will boot without a valid ANTHROPIC_API_KEY; we don't exercise
the LLM path — that requires real credentials and eats tokens. Scope is
container lifecycle + routing + plugin code emission + channel runtime.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

AGENT_NAME = "smoke-agent"
CHANNEL_NAME = "smoke-chat"
CHANNEL_HOST_PORT = 18080  # not 8080 to avoid colliding with a user-run dev gateway


def _docker_available() -> bool:
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


VYSTAK_PY = f'''\
"""Minimal smoke-test definition — one agent + one chat channel."""

import vystak as ast

docker = ast.Provider(name="docker", type="docker")
anthropic = ast.Provider(name="anthropic", type="anthropic")

platform = ast.Platform(name="local", type="docker", provider=docker, namespace="smoke")

sonnet = ast.Model(
    name="sonnet",
    provider=anthropic,
    model_name="claude-sonnet-4-20250514",
    api_keys=ast.Secret(name="ANTHROPIC_API_KEY"),
)

{AGENT_NAME.replace("-", "_")} = ast.Agent(
    name="{AGENT_NAME}",
    instructions="You answer concisely.",
    model=sonnet,
    platform=platform,
    skills=[ast.Skill(name="noop", tools=[])],
)

{CHANNEL_NAME.replace("-", "_")} = ast.Channel(
    name="{CHANNEL_NAME}",
    type=ast.ChannelType.CHAT,
    platform=platform,
    config={{"port": {CHANNEL_HOST_PORT}}},
    routes=[ast.RouteRule(match={{}}, agent="{AGENT_NAME}")],
)
'''


def _run_vystak(project_dir: Path, *args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-for-smoke-test")
    return subprocess.run(
        [sys.executable, "-m", "vystak_cli", *args],
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _cleanup_known_containers() -> None:
    import docker

    client = docker.from_env()
    for name in (f"vystak-{AGENT_NAME}", f"vystak-channel-{CHANNEL_NAME}"):
        try:
            c = client.containers.get(name)
            c.stop()
            c.remove()
        except Exception:
            pass


@pytest.mark.docker
@pytest.mark.skipif(not _docker_available(), reason="Docker not reachable")
def test_chat_channel_end_to_end(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "vystak.py").write_text(VYSTAK_PY)

    _cleanup_known_containers()

    import docker

    docker_client = docker.from_env()

    try:
        apply_result = _run_vystak(project, "apply", timeout=600)
        assert apply_result.returncode == 0, (
            f"apply failed (rc={apply_result.returncode})\n"
            f"STDOUT:\n{apply_result.stdout}\n"
            f"STDERR:\n{apply_result.stderr}"
        )
        assert "Loaded 1 agent(s), 1 channel(s)" in apply_result.stdout

        agent_container = docker_client.containers.get(f"vystak-{AGENT_NAME}")
        assert agent_container.status == "running"
        assert agent_container.labels.get("vystak.hash")

        channel_container = docker_client.containers.get(f"vystak-channel-{CHANNEL_NAME}")
        assert channel_container.status == "running"
        assert channel_container.labels.get("vystak.channel.hash")
        assert channel_container.labels.get("vystak.channel.type") == "chat"

        deadline = time.time() + 30
        last_err: Exception | None = None
        while time.time() < deadline:
            try:
                r = httpx.get(f"http://localhost:{CHANNEL_HOST_PORT}/health", timeout=2)
                if r.status_code == 200:
                    break
            except Exception as e:
                last_err = e
            time.sleep(1)
        else:
            pytest.fail(f"chat /health did not respond within 30s; last error: {last_err}")

        body = r.json()
        assert body["status"] == "ok"
        assert AGENT_NAME in body["agents"]

        models = httpx.get(f"http://localhost:{CHANNEL_HOST_PORT}/v1/models", timeout=5).json()
        ids = {m["id"] for m in models["data"]}
        assert f"vystak/{AGENT_NAME}" in ids

        unknown = httpx.post(
            f"http://localhost:{CHANNEL_HOST_PORT}/v1/chat/completions",
            json={
                "model": "vystak/does-not-exist",
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=10,
        )
        assert unknown.status_code == 404

        # Streaming path should also honor the unknown-model guard (returns 404
        # synchronously, not a streaming error body).
        unknown_stream = httpx.post(
            f"http://localhost:{CHANNEL_HOST_PORT}/v1/chat/completions",
            json={
                "model": "vystak/does-not-exist",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
            timeout=10,
        )
        assert unknown_stream.status_code == 404
        assert unknown_stream.json()["error"]["code"] == "model_not_found"

    finally:
        destroy_result = _run_vystak(project, "destroy", timeout=120)
        if destroy_result.returncode != 0:
            # Fall back to direct cleanup
            _cleanup_known_containers()
        for name in (f"vystak-{AGENT_NAME}", f"vystak-channel-{CHANNEL_NAME}"):
            try:
                docker_client.containers.get(name)
                pytest.fail(f"{name} still present after destroy")
            except docker.errors.NotFound:
                pass
