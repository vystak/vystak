"""Release-tier regression for the shared turn core's memory persistence.

Deploys docker-slack-multi-agent, fires a save_memory trigger via A2A
one-shot (the same path the Slack channel uses at runtime), then
inspects the agent's sqlite sessions store to confirm the row landed.
Tears down on exit regardless of test outcome.

Catches regression of either:
  - turn_core dropping handle_memory_actions
  - protocol layer regressing back to inlined ainvoke without a memory call

Refs: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import textwrap
import time
from pathlib import Path

import httpx
import pytest

pytestmark = [pytest.mark.release_smoke, pytest.mark.docker]

# Test file path: packages/python/vystak-channel-slack/tests/release/test_thread_memory_a2a.py
# Repo root is parents[5].
EXAMPLE = Path(__file__).resolve().parents[5] / "examples" / "docker-slack-multi-agent"


def _docker_available() -> bool:
    try:
        out = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=5,
        )
        return out.returncode == 0
    except Exception:
        return False


def _repo_root() -> Path:
    """Return the main repo root (works in both worktrees and normal checkouts)."""
    # `git rev-parse --git-common-dir` returns the common .git dir shared
    # across worktrees; its parent is the main repo root.
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True, text=True, check=True,
        cwd=str(Path(__file__).parent),
    )
    git_common = Path(result.stdout.strip()).resolve()
    # git-common-dir is either ".git" (main) or "../.git/worktrees/<name>"
    # Walk up until we're out of a .git subtree.
    candidate = git_common
    while candidate.name in (".git", "worktrees") or candidate.parent.name == "worktrees":
        candidate = candidate.parent
    return candidate


def _vystak(args: list[str], cwd: Path):
    """Run a vystak CLI subcommand inside ``cwd``. Ensures .env is present."""
    env_path = cwd / ".env"
    if not env_path.exists():
        # Try worktree root first, then the main repo root (handles worktrees
        # where examples/.env is a symlink into the main repo root .env).
        for candidate in (
            Path(__file__).resolve().parents[5] / ".env",
            _repo_root() / ".env",
        ):
            if candidate.exists():
                shutil.copy(candidate, env_path)
                break
    return subprocess.run(
        ["uv", "run", "vystak", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _agent_port(name: str) -> int:
    out = subprocess.check_output(
        ["docker", "port", name, "8000"], text=True,
    ).strip()
    return int(out.splitlines()[0].split(":")[-1])


def _store_rows() -> int:
    code = textwrap.dedent("""
        import sqlite3
        n = sqlite3.connect("/data/sessions_store.db").execute(
            "SELECT count(*) FROM store"
        ).fetchone()[0]
        print(n)
    """)
    out = subprocess.check_output(
        ["docker", "exec", "vystak-assistant-agent", "python", "-c", code],
        text=True,
    )
    return int(out.strip())


@pytest.mark.skipif(
    not EXAMPLE.exists(),
    reason="examples/docker-slack-multi-agent not present",
)
@pytest.mark.skipif(
    not _docker_available(),
    reason="Docker daemon not reachable",
)
def test_a2a_one_shot_persists_save_memory():
    """A save_memory call made via the A2A one-shot path must persist to the store."""
    # Idempotent destroy in case a prior test left state behind.
    with contextlib.suppress(subprocess.CalledProcessError):
        _vystak(["destroy"], EXAMPLE)

    _vystak(["apply"], EXAMPLE)
    try:
        port = _agent_port("vystak-assistant-agent")

        baseline = _store_rows()

        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"http://localhost:{port}/a2a",
                json={
                    "jsonrpc": "2.0",
                    "id": "regression",
                    "method": "tasks/send",
                    "params": {
                        "id": "regression",
                        "message": {
                            "role": "user",
                            "parts": [
                                {
                                    "text": (
                                        "My name is RegressionTester. "
                                        "Save this fact using save_memory."
                                    )
                                }
                            ],
                        },
                        "metadata": {
                            "sessionId": "regression",
                            "user_id": "slack:URELEASE",
                        },
                    },
                },
            )
            resp.raise_for_status()

        # Allow async memory writes to land. Poll up to 10 seconds.
        deadline = time.time() + 10
        while time.time() < deadline:
            if _store_rows() > baseline:
                break
            time.sleep(0.5)

        assert _store_rows() > baseline, (
            "save_memory did not persist via A2A one-shot path; the shared "
            "turn core may be missing handle_memory_actions or a protocol "
            "layer may be bypassing it."
        )
    finally:
        with contextlib.suppress(Exception):
            _vystak(["destroy"], EXAMPLE)
