"""End-to-end test for --env overlay flag."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


def _write(dir_: Path, filename: str, content: str) -> Path:
    p = dir_ / filename
    p.write_text(textwrap.dedent(content).lstrip())
    return p


_VYSTAK_PY = """\
    from vystak.schema import Agent, Model, Platform, Provider
    agent = Agent(
        name="a",
        model=Model(
            name="m",
            provider=Provider(name="p", type="anthropic", api_key_env="K"),
            model_name="claude-sonnet-4-20250514",
        ),
        platform=Platform(
            name="main",
            type="docker",
            provider=Provider(name="docker", type="docker"),
        ),
    )
"""

_VYSTAK_PROD_PY = """\
    from vystak.schema import EnvironmentOverride, NatsConfig, Transport
    override = EnvironmentOverride(
        transports={
            "main": Transport(name="prod-bus", type="nats", config=NatsConfig()),
        },
    )
"""


def test_load_environment_override(tmp_path):
    """Loader resolves vystak.<env>.py overlay and returns the override."""
    from vystak_cli.loader import load_environment_override

    _write(tmp_path, "vystak.py", _VYSTAK_PY)
    _write(tmp_path, "vystak.prod.py", _VYSTAK_PROD_PY)

    override = load_environment_override(tmp_path / "vystak.py", env="prod")
    assert "main" in override.transports
    assert override.transports["main"].type == "nats"


def test_missing_overlay_file_raises(tmp_path):
    from vystak_cli.loader import load_environment_override

    _write(tmp_path, "vystak.py", "# empty")
    with pytest.raises(FileNotFoundError, match="vystak.nonexistent.py"):
        load_environment_override(tmp_path / "vystak.py", env="nonexistent")


def test_overlay_without_override_raises(tmp_path):
    from vystak_cli.loader import load_environment_override

    _write(tmp_path, "vystak.py", "# empty")
    _write(tmp_path, "vystak.bad.py", "# No `override` variable defined.\nx = 42\n")

    with pytest.raises(ValueError, match="must define"):
        load_environment_override(tmp_path / "vystak.py", env="bad")
