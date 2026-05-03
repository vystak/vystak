"""Release-cell fixtures for vystak-channel-discord."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def discord_token():
    tok = os.environ.get("DISCORD_BOT_TOKEN")
    if not tok:
        pytest.skip("DISCORD_BOT_TOKEN not set")
    return tok


@pytest.fixture
def project(tmp_path: Path):
    """A tmp project dir with a sentinel .env and guaranteed teardown."""
    proj = tmp_path / "discord-cell"
    proj.mkdir()
    (proj / ".env").write_text(
        "ANTHROPIC_API_KEY=test-key\nANTHROPIC_API_URL=https://invalid.local\n"
    )
    yield proj
    if shutil.which("vystak"):
        subprocess.run(["vystak", "destroy", "-y"], cwd=proj, check=False)
