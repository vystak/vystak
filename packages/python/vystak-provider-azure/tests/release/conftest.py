"""Shared fixtures for the Smoke-tier Azure release cells (A1, A2, ...).

Azure smoke cells differ from Docker smoke cells in three ways:
1. Prereqs: AZURE_SUBSCRIPTION_ID + `az login` (auto-skip when missing).
2. Timing: `vystak apply` on ACA takes 3–5 minutes (RG + Log Analytics +
   ACR + ACA environment + image build/push + app creation). Tests use
   minute-range timeouts.
3. Verification: `az containerapp exec` instead of `docker exec`; HTTPS
   FQDNs instead of local ports.

Each cell uses its own disposable resource group keyed by test name so
concurrent runs on the same subscription don't collide. Teardown runs
`az group delete` even on failure.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest


# ----- Prereq detection -------------------------------------------------


def _az_cli_available() -> bool:
    try:
        result = subprocess.run(
            ["az", "version", "--output", "none"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _az_logged_in() -> bool:
    try:
        result = subprocess.run(
            ["az", "account", "show", "--output", "none"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.fixture(scope="session")
def azure_required():
    if not _az_cli_available():
        pytest.skip("Azure CLI not installed — skipping Azure release smoke")
    if not _az_logged_in():
        pytest.skip("Not logged into Azure (run `az login`) — skipping Azure smoke")
    if not os.environ.get("AZURE_SUBSCRIPTION_ID"):
        pytest.skip("AZURE_SUBSCRIPTION_ID env var not set — skipping Azure smoke")


# ----- Process helpers --------------------------------------------------


def run(cmd: list[str], cwd: Path | None = None, check: bool = True, timeout: int | None = None, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, check=check, cwd=cwd,
        timeout=timeout, **kw,
    )


def vystak(args: list[str], cwd: Path, check: bool = True, timeout: int = 600) -> subprocess.CompletedProcess:
    return run(["uv", "run", "vystak", *args], cwd=cwd, check=check, timeout=timeout)


def az_exec(app: str, rg: str, command: str) -> str:
    """`az containerapp exec`'s sibling — actually invokes `az` CLI,
    returns stdout."""
    result = run(
        ["az", "containerapp", "exec", "-n", app, "-g", rg, "--command", command],
        check=True, timeout=60,
    )
    return result.stdout


def app_fqdn(app: str, rg: str) -> str:
    """Return the ingress FQDN for a Container App."""
    result = run(
        ["az", "containerapp", "show", "-n", app, "-g", rg,
         "--query", "properties.configuration.ingress.fqdn", "-o", "tsv"],
        check=True, timeout=30,
    )
    return result.stdout.strip()


def app_exists(app: str, rg: str) -> bool:
    result = run(
        ["az", "containerapp", "show", "-n", app, "-g", rg, "--output", "none"],
        check=False, timeout=30,
    )
    return result.returncode == 0


def rg_exists(rg: str) -> bool:
    result = run(["az", "group", "exists", "-n", rg], check=False, timeout=30)
    return result.stdout.strip().lower() == "true"


def wait_for_https(url: str, timeout: int = 120, interval: float = 5.0) -> None:
    """Poll an HTTPS URL for 200 — longer defaults than Docker since ACA
    ingress propagation takes a minute or two after app creation."""
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError) as e:
            last_err = e
        time.sleep(interval)
    raise TimeoutError(f"{url} did not respond 200 within {timeout}s: {last_err}")


def https_get_json(url: str, timeout: int = 30) -> dict:
    import urllib.request

    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ----- Project fixture --------------------------------------------------


@pytest.fixture
def azure_project(tmp_path, monkeypatch, azure_required, request):
    """Per-test disposable Azure project with unique resource group.

    Naming: vystak-smoke-<test-name-short>-<random>. Teardown runs
    `az group delete --yes` non-interactively, even on failure.
    """
    import uuid

    test_name = request.node.name.lower().replace("_", "-")[:40]
    rg_suffix = uuid.uuid4().hex[:6]
    rg_name = f"vystak-smoke-{test_name}-{rg_suffix}"[:60]

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "ANTHROPIC_API_KEY=sk-release-smoke-sentinel\n"
        "ANTHROPIC_API_URL=https://api.anthropic.com\n"
    )
    (tmp_path / "tools").mkdir()

    # Expose rg_name for the test body to interpolate into vystak.yaml
    setattr(request.node, "rg_name", rg_name)

    yield tmp_path, rg_name

    # Teardown — aggressive, tolerant. Don't block the test run on slow
    # Azure deletion; use --no-wait and trust async GC.
    try:
        vystak(["destroy", "--include-resources", "--no-wait"], cwd=tmp_path, check=False)
    except Exception:
        pass
    # Belt-and-braces: nuke the whole RG. Safe because it's a unique
    # disposable name owned by this test only.
    try:
        run(
            ["az", "group", "delete", "-n", rg_name, "--yes", "--no-wait"],
            check=False, timeout=30,
        )
    except Exception:
        pass
    # Local state cleanup
    for d in (tmp_path / ".vystak",):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


# ----- Verification primitives ----------------------------------------


def assert_plan_ok(cwd: Path, expect_sections: list[str], absent_sections: list[str]) -> str:
    result = vystak(["plan"], cwd=cwd)
    out = result.stdout
    for s in expect_sections:
        assert s in out, f"plan missing section {s!r}:\n{out}"
    for s in absent_sections:
        assert s not in out, f"plan had unexpected section {s!r}:\n{out}"
    return out


def assert_apply_ok(cwd: Path, timeout: int = 900) -> subprocess.CompletedProcess:
    """Azure apply takes 3–5 minutes in practice. 15 min ceiling."""
    return vystak(["apply"], cwd=cwd, timeout=timeout)


def assert_health_azure(app: str, rg: str, timeout: int = 180) -> None:
    """V4 for Azure: fetch /health via HTTPS FQDN. Account for ingress
    propagation delay after app creation."""
    fqdn = app_fqdn(app, rg)
    assert fqdn, f"no fqdn found for {app}"
    wait_for_https(f"https://{fqdn}/health", timeout=timeout)
    body = https_get_json(f"https://{fqdn}/health")
    assert body.get("status") == "ok", f"unexpected /health body: {body}"


def assert_agent_card_azure(app: str, rg: str) -> dict:
    fqdn = app_fqdn(app, rg)
    body = https_get_json(f"https://{fqdn}/.well-known/agent.json")
    assert "name" in body and "skills" in body, f"invalid agent card: {body}"
    return body


def assert_env_contains(app: str, rg: str, key: str) -> None:
    """V3 for Azure: `az containerapp exec -- env | grep KEY`."""
    env = az_exec(app, rg, "env")
    assert f"{key}=" in env, (
        f"{app} env missing {key}. Got first 400 chars:\n{env[:400]}"
    )


def assert_env_absent(app: str, rg: str, key: str) -> None:
    env = az_exec(app, rg, "env")
    assert f"{key}=" not in env, (
        f"{app} env leaked forbidden key {key}. Got first 400 chars:\n{env[:400]}"
    )
