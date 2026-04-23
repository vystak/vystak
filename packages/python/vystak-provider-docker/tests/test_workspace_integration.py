"""End-to-end: deploy an agent with a workspace, RPC in and out.

Opt-in: ``uv run pytest -m docker``. Requires a reachable Docker daemon
and network access (builds images from public bases). Not executed in
the default ``just test-python`` run.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

AGENT_NAME = "ws-test-agent"


def _docker_available() -> bool:
    try:
        import docker as _docker

        _docker.from_env().ping()
        return True
    except Exception:
        return False


VYSTAK_YAML = f"""\
providers:
  docker: {{type: docker}}
  anthropic: {{type: anthropic}}
platforms:
  local: {{type: docker, provider: docker}}
vault:
  name: v
  provider: docker
  type: vault
  mode: deploy
  config: {{}}
models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-4-20250514
agents:
  - name: {AGENT_NAME}
    model: sonnet
    platform: local
    secrets: [{{name: ANTHROPIC_API_KEY}}]
    skills:
      - name: edit
        tools: [fs.readFile, fs.writeFile, fs.listDir]
    workspace:
      name: dev
      image: python:3.12-slim
      provision:
        - apt-get update && apt-get install -y --no-install-recommends git
"""


def _run_vystak(project_dir: Path, *args: str, timeout: int = 600):
    env = os.environ.copy()
    env.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-for-test")
    return subprocess.run(
        [sys.executable, "-m", "vystak_cli", *args],
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _cleanup() -> None:
    import docker as _docker

    client = _docker.from_env()
    names = [
        f"vystak-{AGENT_NAME}",
        f"vystak-{AGENT_NAME}-workspace",
        f"vystak-{AGENT_NAME}-agent-vault-agent",
        f"vystak-{AGENT_NAME}-workspace-vault-agent",
        "vystak-vault",
    ]
    for n in names:
        try:
            c = client.containers.get(n)
            c.stop()
            c.remove()
        except _docker.errors.NotFound:
            pass
    for vol in (
        "vystak-vault-data",
        f"vystak-{AGENT_NAME}-agent-secrets",
        f"vystak-{AGENT_NAME}-agent-approle",
        f"vystak-{AGENT_NAME}-workspace-secrets",
        f"vystak-{AGENT_NAME}-workspace-approle",
        f"vystak-{AGENT_NAME}-workspace-data",
    ):
        try:
            v = client.volumes.get(vol)
            v.remove()
        except _docker.errors.NotFound:
            pass


@pytest.mark.docker
@pytest.mark.skipif(not _docker_available(), reason="Docker not reachable")
def test_workspace_deploy_and_rpc(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "vystak.yaml").write_text(VYSTAK_YAML)
    (project / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-fake\n")

    _cleanup()
    try:
        result = _run_vystak(project, "apply", "--file", "vystak.yaml")
        assert result.returncode == 0, (
            f"apply failed:\nSTDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

        import docker as _docker

        client = _docker.from_env()

        ws = client.containers.get(f"vystak-{AGENT_NAME}-workspace")
        assert ws.status == "running"

        ag = client.containers.get(f"vystak-{AGENT_NAME}")
        assert ag.status == "running"

        exec_result = ag.exec_run(["sh", "-c", "ls -la /vystak/ssh/ 2>&1"])
        out = exec_result.output.decode()
        assert "id_ed25519" in out
        assert "known_hosts" in out

        exec_result = ws.exec_run(["sh", "-c", "ls -la /shared/ 2>&1"])
        out = exec_result.output.decode()
        assert "ssh_host_ed25519_key" in out
        assert "authorized_keys_vystak-agent" in out

        exec_result = ws.exec_run(["sh", "-c", "which vystak-workspace-rpc"])
        out = exec_result.output.decode()
        assert "/usr/local/bin/vystak-workspace-rpc" in out

    finally:
        _cleanup()
