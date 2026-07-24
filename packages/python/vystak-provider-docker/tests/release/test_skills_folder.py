"""Release cell: folder skills — example resolves, skill tools build, app loads.

Load-only smoke modeled on test_template_smoke.py: verifies the
examples/docker-skills project resolves its folder skill (description +
content digest), produces the load_skill / read_skill_file tools, renders
the prompt section, and constructs the FastAPI app. Full Docker lifecycle
coverage comes from the existing D-cells; this cell gates the skills
surface itself.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.release_smoke


def _repo_root() -> Path:
    # packages/python/vystak-provider-docker/tests/release/test_skills_folder.py
    return Path(__file__).resolve().parents[5]


def test_docker_skills_example_loads_and_builds_skill_tools():
    example = _repo_root() / "examples" / "docker-skills"
    smoke = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "sys.path.insert(0, '.')\n"
                "from pathlib import Path\n"
                "from vystak_cli.loader import load_definitions\n"
                "from _vystak.runtime.skills import build_skill_tools, skills_prompt_section\n"
                "from _vystak.runtime.app_factory import build_agent_app\n"
                "defs = load_definitions([Path('vystak.yaml')])\n"
                "agent = defs.agents[0]\n"
                "assert agent.skills[0].content_digest, 'folder skill not resolved'\n"
                "tools = build_skill_tools(agent, Path('.'))\n"
                "print(sorted(t.name for t in tools))\n"
                "section = skills_prompt_section(agent)\n"
                "assert 'research' in section and 'load_skill' in section\n"
                "app = build_agent_app(agent)\n"
                "print(len(app.routes))\n"
            ),
        ],
        cwd=example,
        capture_output=True,
        text=True,
    )
    if smoke.returncode != 0:
        pytest.fail(
            f"Skills smoke failed: STDOUT={smoke.stdout!r}\nSTDERR={smoke.stderr!r}"
        )
    lines = smoke.stdout.strip().splitlines()
    assert "['load_skill', 'read_skill_file']" in lines[0]
    assert int(lines[-1]) >= 7
