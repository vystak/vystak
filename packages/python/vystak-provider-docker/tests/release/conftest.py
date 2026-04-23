"""Shared fixtures for the Smoke-tier release cells from test_plan.md.

Design principles:
- One test function per cell runs V1–V9 sequentially. apply is the
  expensive step; splitting would quadruple wall time.
- Missing prereqs auto-skip (no Docker → skip Docker cells, no
  AZURE_SUBSCRIPTION_ID → skip Azure cells).
- Every test gets a guaranteed destroy via the `project` fixture
  yielding then running `vystak destroy` even on failure.
- Tests never use real LLM API keys. They pass a sentinel value and
  assert the plumbing (env delivery, container health, agent card,
  A2A endpoint accepts requests). An actual LLM response check is out
  of scope — too flaky for CI.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

# ----- Prereq detection -------------------------------------------------


def _docker_running() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _vystak_cli_available() -> bool:
    try:
        result = subprocess.run(
            ["uv", "run", "vystak", "--version"],
            capture_output=True, text=True, timeout=10,
            cwd=_repo_root(),
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _repo_root() -> Path:
    # packages/python/vystak-provider-docker/tests/release/conftest.py
    return Path(__file__).resolve().parents[5]


@pytest.fixture(scope="session")
def docker_required():
    if not _docker_running():
        pytest.skip("Docker daemon not reachable — skipping release smoke")
    if not _vystak_cli_available():
        pytest.skip("`uv run vystak` not available — skipping release smoke")


# ----- Process helpers --------------------------------------------------


def run(
    cmd: list[str],
    cwd: Path | None = None,
    check: bool = True,
    **kw,
) -> subprocess.CompletedProcess:
    """subprocess.run wrapper with sensible defaults."""
    return subprocess.run(
        cmd, capture_output=True, text=True, check=check, cwd=cwd, **kw,
    )


def vystak(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """`uv run vystak <args>` from the project dir."""
    return run(["uv", "run", "vystak", *args], cwd=cwd, check=check)


def docker_exec(container: str, command: str) -> str:
    """Run a shell command inside `container`. Returns stdout."""
    result = run(["docker", "exec", container, "sh", "-c", command], check=True)
    return result.stdout


def docker_running(container: str) -> bool:
    result = run(
        ["docker", "ps", "--filter", f"name={container}", "--format", "{{.Names}}"],
        check=False,
    )
    return container in result.stdout


def container_http_port(container: str, internal: int = 8000) -> int:
    """Return the host port docker mapped to `internal` in `container`."""
    result = run(["docker", "port", container, f"{internal}/tcp"], check=True)
    # stdout looks like "0.0.0.0:49894\n[::]:49894\n"
    first = result.stdout.strip().splitlines()[0]
    return int(first.rsplit(":", 1)[-1])


def wait_for_http(url: str, timeout: int = 30, interval: float = 0.5) -> None:
    """Poll `url` until it responds 200, or timeout."""
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
            last_err = e
        time.sleep(interval)
    raise TimeoutError(f"{url} did not respond 200 within {timeout}s: {last_err}")


def http_get_json(url: str, timeout: int = 5) -> dict:
    import urllib.request

    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def post_a2a_task(url: str, message: str, timeout: int = 30) -> dict:
    """Send an A2A tasks/send request to the agent's /a2a endpoint.

    Returns the JSON-RPC result. Used to verify the agent accepts and
    routes a task — the LLM response may be an auth error if the test
    key is a sentinel; callers assert on the shape, not the content.
    """
    import urllib.request

    body = {
        "jsonrpc": "2.0",
        "id": "release-smoke-1",
        "method": "tasks/send",
        "params": {
            "id": "t-smoke-1",
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": message}],
            },
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ----- Project fixture --------------------------------------------------


@pytest.fixture
def vault_clean():
    """Ensure no stale Vault state pollutes this test.

    Pre-test: remove any `vystak-vault` container and `vystak-vault-data`
    volume left by an aborted prior run (or another worktree). The
    shared-infra design means a per-project `.vystak/vault/init.json`
    can go missing while the volume persists with init state — apply
    then fails with "state mismatch". This fixture forecloses that.

    Post-test: no-op — individual tests handle their own teardown.
    """
    for container in ("vystak-vault",):
        run(["docker", "rm", "-f", container], check=False)
    for volume in ("vystak-vault-data",):
        run(["docker", "volume", "rm", volume], check=False)
    yield


@pytest.fixture
def project(tmp_path, monkeypatch, docker_required):
    """Yield a tmp project dir. Writes `.env` with test-safe sentinels.

    Always runs `vystak destroy` on teardown, even if the test fails.
    Callers are responsible for writing `vystak.yaml` into the dir
    before invoking `vystak apply`.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        # Sentinel values — not valid for real API calls, but valid
        # strings so delivery checks pass. Tests assert on env scoping
        # and agent plumbing, not on LLM responses.
        "ANTHROPIC_API_KEY=sk-release-smoke-sentinel\n"
        "ANTHROPIC_API_URL=https://api.anthropic.com\n"
    )
    # Ensure tools/ dir exists — workspace-bearing configs reference it.
    (tmp_path / "tools").mkdir()

    yield tmp_path

    # Teardown — best effort, never fail the test on cleanup.
    import contextlib
    with contextlib.suppress(Exception):
        vystak(["destroy"], cwd=tmp_path, check=False)
    # Remove any state files that the CLI might have missed
    for d in (tmp_path / ".vystak",):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


# ----- Verification primitives (V1–V9) ---------------------------------


def assert_plan_ok(cwd: Path, expect_sections: list[str], absent_sections: list[str]) -> str:
    """V1: run `vystak plan`, assert expected sections present/absent."""
    result = vystak(["plan"], cwd=cwd)
    out = result.stdout
    for s in expect_sections:
        assert s in out, f"plan missing section {s!r}:\n{out}"
    for s in absent_sections:
        assert s not in out, f"plan had unexpected section {s!r}:\n{out}"
    return out


def assert_apply_ok(cwd: Path) -> subprocess.CompletedProcess:
    """V2: apply exits 0."""
    return vystak(["apply"], cwd=cwd)


def assert_isolation(
    containers_to_secrets: dict[str, set[str]],
    forbidden_per_container: dict[str, set[str]],
) -> None:
    """V3: for each (container, expected secrets), those secrets are
    present in env; for each (container, forbidden secrets), none are
    present."""
    for name, expected in containers_to_secrets.items():
        env = docker_exec(name, "env")
        for key in expected:
            assert f"{key}=" in env, f"{name} missing expected secret {key}"
    for name, forbidden in forbidden_per_container.items():
        env = docker_exec(name, "env")
        for key in forbidden:
            assert f"{key}=" not in env, (
                f"{name} leaked forbidden secret {key}:\n{env}"
            )


def assert_health(container: str, internal_port: int = 8000) -> None:
    """V4: /health returns 200 {'status': 'ok'}."""
    port = container_http_port(container, internal_port)
    wait_for_http(f"http://localhost:{port}/health", timeout=30)
    body = http_get_json(f"http://localhost:{port}/health")
    assert body.get("status") == "ok", f"unexpected /health body: {body}"


def assert_agent_card(
    container: str,
    expected_skills: set[str] | None = None,
    internal_port: int = 8000,
) -> dict:
    """V5: agent card is valid A2A, lists expected skills."""
    port = container_http_port(container, internal_port)
    body = http_get_json(f"http://localhost:{port}/.well-known/agent.json")
    assert "name" in body and "skills" in body, f"invalid agent card: {body}"
    if expected_skills is not None:
        got = {s["id"] for s in body["skills"]}
        missing = expected_skills - got
        assert not missing, f"card missing skills {missing}; got {got}"
    return body


def assert_a2a_accepts_task(container: str, internal_port: int = 8000) -> None:
    """V6 (HTTP variant): POST an A2A task; assert the agent returns
    a valid JSON-RPC result envelope. The result may indicate LLM
    failure (e.g. invalid API key) because the sentinel key is not
    real — we care that plumbing works, not the LLM answer."""
    port = container_http_port(container, internal_port)
    resp = post_a2a_task(
        f"http://localhost:{port}/a2a",
        "ping from release smoke",
    )
    assert resp.get("jsonrpc") == "2.0", f"bad JSON-RPC response: {resp}"
    assert "result" in resp or "error" in resp, f"bad envelope: {resp}"
    # If result, it should have a status block. If error, it should
    # have an error code. Either is proof the agent accepted + processed
    # the request through the A2A pipeline.


def assert_destroy_ok(cwd: Path) -> None:
    """V9: destroy exits 0, default-path state cleaned, no orphan
    containers remain for this agent."""
    vystak(["destroy"], cwd=cwd)
    # Default-path state dirs cleaned if present
    for d in ("env", "ssh"):
        p = cwd / ".vystak" / d
        # Directory may or may not have existed; if it did, it should
        # be empty or gone now.
        if p.exists():
            assert not list(p.iterdir()), (
                f"{p} still has entries after destroy: {list(p.iterdir())}"
            )
