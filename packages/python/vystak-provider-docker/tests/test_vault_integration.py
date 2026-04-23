"""End-to-end Docker integration: Vault + per-principal sidecars + isolation.

Opt-in:
    uv run pytest -m docker \
        packages/python/vystak-provider-docker/tests/test_vault_integration.py

Exercises the full `vystak apply` flow with a Hashi Vault deployment,
verifies the per-container isolation property (agent cannot read
workspace secrets from its /shared/secrets.env or from Vault with its
own token).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

AGENT_NAME = "vault-test-agent"
VAULT_TEST_PORT = 18201  # test-only host port


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
  name: vystak-vault
  provider: docker
  type: vault
  mode: deploy
  config:
    host_port: {VAULT_TEST_PORT}
models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-4-20250514
agents:
  - name: {AGENT_NAME}
    model: sonnet
    secrets: [{{name: ANTHROPIC_API_KEY}}]
    workspace:
      name: tools
      type: persistent
      secrets: [{{name: STRIPE_API_KEY}}]
    platform: local
"""


def _run_vystak(project_dir: Path, *args: str, timeout: int = 600):
    env = os.environ.copy()
    env.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-for-test")
    env.setdefault("STRIPE_API_KEY", "sk_test_fake_for_test")
    return subprocess.run(
        [sys.executable, "-m", "vystak_cli", *args],
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _cleanup():
    import docker as _docker

    client = _docker.from_env()
    for name in (
        f"vystak-{AGENT_NAME}",
        f"vystak-{AGENT_NAME}-agent-vault-agent",
        f"vystak-{AGENT_NAME}-workspace-vault-agent",
        "vystak-vault",
    ):
        try:
            c = client.containers.get(name)
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
    ):
        try:
            v = client.volumes.get(vol)
            v.remove()
        except _docker.errors.NotFound:
            pass


@pytest.mark.docker
@pytest.mark.skipif(not _docker_available(), reason="Docker not reachable")
def test_vault_deploy_end_to_end(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "vystak.yaml").write_text(VYSTAK_YAML)
    env_file = project / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-ant-fake\nSTRIPE_API_KEY=sk_test_fake\n")

    _cleanup()

    try:
        apply_result = _run_vystak(project, "apply", "--file", "vystak.yaml")
        assert apply_result.returncode == 0, (
            f"apply failed\nSTDOUT:\n{apply_result.stdout}\n"
            f"STDERR:\n{apply_result.stderr}"
        )

        import docker as _docker

        client = _docker.from_env()

        # Vault server is running
        vault_container = client.containers.get("vystak-vault")
        assert vault_container.status == "running"

        # init.json was written chmod 600
        init_path = project / ".vystak/vault/init.json"
        assert init_path.exists()
        assert (init_path.stat().st_mode & 0o777) == 0o600
        init_data = json.loads(init_path.read_text())
        assert "root_token" in init_data
        assert len(init_data["unseal_keys_b64"]) == 5

        # Both vault-agent sidecars running
        client.containers.get(f"vystak-{AGENT_NAME}-agent-vault-agent")
        client.containers.get(f"vystak-{AGENT_NAME}-workspace-vault-agent")

        # Main containers running
        client.containers.get(f"vystak-{AGENT_NAME}")

        # Vault is unsealed
        status = httpx.get(
            f"http://localhost:{VAULT_TEST_PORT}/v1/sys/seal-status", timeout=5
        ).json()
        assert status["sealed"] is False

        # Agent container sees ANTHROPIC_API_KEY in env, NOT STRIPE_API_KEY.
        # exec_run with a list form avoids needing a shell for the pipeline.
        exec_result = client.containers.get(f"vystak-{AGENT_NAME}").exec_run(
            ["sh", "-c", "env | grep -E '^(ANTHROPIC|STRIPE)' | sort || true"]
        )
        out = exec_result.output.decode()
        assert "ANTHROPIC_API_KEY=sk-ant-fake" in out, (
            f"expected ANTHROPIC_API_KEY in agent env, got: {out!r}"
        )
        assert "STRIPE_API_KEY" not in out, (
            f"isolation breach: workspace secret leaked into agent env: {out!r}"
        )

    finally:
        _cleanup()
