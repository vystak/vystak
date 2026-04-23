"""Docker-marked end-to-end test: deploy agent+workspace+secrets without
a Vault, verify per-container isolation.

Run with `pytest -m docker` from the vystak-provider-docker package.
"""

import subprocess
import time

import pytest

pytestmark = pytest.mark.docker


def _run(cmd: list[str], check: bool = True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check, **kw)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Minimal project directory with a workspace-declaring agent, no Vault."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vystak.yaml").write_text(
        """
providers:
  docker:
    type: docker
  anthropic:
    type: anthropic
platforms:
  docker:
    provider: docker
    type: docker
models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-4-6
agents:
  - name: isolation-test
    model: sonnet
    platform: docker
    secrets:
      - name: ANTHROPIC_API_KEY
    workspace:
      name: ws
      image: python:3.12-slim
      persistence: ephemeral
      secrets:
        - name: STRIPE_API_KEY
""".strip()
    )
    (tmp_path / ".env").write_text(
        "ANTHROPIC_API_KEY=sk-agent-sentinel\n"
        "STRIPE_API_KEY=sk-workspace-sentinel\n"
    )
    (tmp_path / "tools").mkdir()
    yield tmp_path
    # Best-effort cleanup
    _run(["uv", "run", "vystak", "destroy"], check=False, cwd=str(tmp_path))


def test_default_path_isolates_workspace_secret_from_agent(project):
    """Apply the config; exec into the agent container; assert the workspace
    secret is NOT present in its env."""
    # Apply
    result = _run(
        ["uv", "run", "vystak", "apply"], check=False, cwd=str(project)
    )
    assert result.returncode == 0, (
        f"apply failed: stdout={result.stdout}\nstderr={result.stderr}"
    )

    # Wait past the Vault-path workspace shim's 30s timeout to catch the
    # false-positive case where the workspace appears up briefly but exits
    # with "/shared/secrets.env never populated".
    time.sleep(35)

    ps = _run(
        [
            "docker",
            "ps",
            "--filter",
            "name=vystak-isolation-test",
            "--format",
            "{{.Names}}",
        ],
        check=True,
    ).stdout
    assert "vystak-isolation-test" in ps, f"agent container not running: {ps!r}"
    assert "vystak-isolation-test-workspace" in ps, (
        f"workspace container not running (likely shim-wait timeout): {ps!r}"
    )

    # Agent container env does NOT contain STRIPE_API_KEY
    agent_env = _run(
        ["docker", "exec", "vystak-isolation-test", "env"], check=True
    ).stdout
    assert "STRIPE_API_KEY" not in agent_env, (
        f"Agent container env leaked STRIPE_API_KEY!\n{agent_env}"
    )
    assert "ANTHROPIC_API_KEY=sk-agent-sentinel" in agent_env

    # Workspace container env DOES contain STRIPE_API_KEY and NOT ANTHROPIC_API_KEY
    ws_env = _run(
        ["docker", "exec", "vystak-isolation-test-workspace", "env"], check=True
    ).stdout
    assert "STRIPE_API_KEY=sk-workspace-sentinel" in ws_env
    assert "ANTHROPIC_API_KEY" not in ws_env, (
        f"Workspace container env leaked ANTHROPIC_API_KEY!\n{ws_env}"
    )
