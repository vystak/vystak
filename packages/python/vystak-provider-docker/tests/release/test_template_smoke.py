"""Release cell: template-scaffolded agent — scaffold + load-only smoke.

Phase 7 of the framework-template migration. The actual `vystak apply` Docker
path is deferred until Phase 9 (when the codegen path is deleted and the
Docker provider switches to using the user dir as build context). This cell
verifies that the new `vystak init --framework langchain-python` produces a
valid project tree that loads without error.

Covers V1 (plan-equivalent: scaffold succeeds + manifest written) and a
load-only V2 (build_agent_app constructs FastAPI routes). Skips V3-V9
(Docker lifecycle dimensions) — those will land with Phase 9.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.release_smoke


def _repo_root() -> Path:
    # packages/python/vystak-provider-docker/tests/release/test_template_smoke.py
    return Path(__file__).resolve().parents[5]


def test_template_scaffold_and_load(tmp_path):
    """V1-V2 scaffold + load-only. Skips V3-V9 (Docker lifecycle)."""
    target = tmp_path / "tpl-agent"
    repo_root = _repo_root()

    # Scaffold via the CLI exactly as a user would.
    subprocess.run(
        [
            "uv",
            "run",
            "vystak",
            "init",
            str(target),
            "--framework",
            "langchain-python",
        ],
        check=True,
        cwd=repo_root,
    )

    # Verify scaffold produced the expected structure.
    assert (target / "_vystak" / "manifest.json").exists()
    assert (target / "_vystak" / "runtime" / "app_factory.py").exists()
    assert (target / "server.py").exists()
    assert (target / "Dockerfile").exists()

    manifest = json.loads((target / "_vystak" / "manifest.json").read_text())
    assert manifest["template"]["name"] == "langchain-python"

    # Replace the starter vystak.yaml with a minimal valid one for the
    # load-only test. The starter is name=example-agent which is fine,
    # but we want explicit framework + a model definition.
    yaml_path = target / "vystak.yaml"
    yaml_path.write_text(
        "name: tpl-agent\n"
        "framework: langchain-python\n"
        "instructions: A test agent.\n"
        "model:\n"
        "  name: m\n"
        "  provider:\n"
        "    name: anthropic\n"
        "    type: anthropic\n"
        "  model_name: claude-sonnet-4-6\n"
    )

    # Load-only smoke: import config + app_factory inside the scaffolded
    # project. sys.executable runs in the workspace venv which already has
    # framework deps (fastapi, langchain, etc.) installed via the workspace.
    smoke = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "sys.path.insert(0, '.')\n"
                "from _vystak.runtime.config import load_agent\n"
                "from _vystak.runtime.app_factory import build_agent_app\n"
                "agent = load_agent('vystak.yaml')\n"
                "app = build_agent_app(agent)\n"
                "print(len(app.routes))\n"
            ),
        ],
        cwd=target,
        capture_output=True,
        text=True,
    )

    if smoke.returncode != 0:
        pytest.fail(
            f"Load smoke failed: STDOUT={smoke.stdout!r}\nSTDERR={smoke.stderr!r}"
        )

    route_count = int(smoke.stdout.strip().splitlines()[-1])
    assert route_count >= 7, f"Expected >=7 routes, got {route_count}"


def test_migrated_hello_agent_loads():
    """The migrated hello-agent in examples/ must load with its real YAML.

    The synthetic-YAML smoke above doesn't exercise sessions, skills, or
    tool wiring. This loads the actual migrated example end-to-end so any
    bug in build_agent_app's handling of real-world fields (sessions,
    secrets, parameters) trips here, not when the user runs vystak apply.
    """
    repo_root = _repo_root()
    hello = repo_root / "examples" / "hello-agent"
    if not (hello / "_vystak" / "manifest.json").exists():
        pytest.skip("hello-agent not yet migrated")

    smoke = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "sys.path.insert(0, '.')\n"
                "from _vystak.runtime.config import load_agent\n"
                "from _vystak.runtime.app_factory import build_agent_app\n"
                "agent = load_agent('vystak.yaml')\n"
                "app = build_agent_app(agent)\n"
                "print(len(app.routes))\n"
            ),
        ],
        cwd=hello,
        capture_output=True,
        text=True,
    )

    if smoke.returncode != 0:
        pytest.fail(
            f"Migrated hello-agent failed to load:\n"
            f"STDOUT={smoke.stdout!r}\nSTDERR={smoke.stderr!r}"
        )

    route_count = int(smoke.stdout.strip().splitlines()[-1])
    assert route_count >= 7
