"""Pytest configuration for vystak-template-langchain-python tests."""

from types import SimpleNamespace

import pytest


@pytest.fixture
def tmp_agent_dir(tmp_path):
    """Provides a tmp directory with a minimal vystak.yaml."""
    (tmp_path / "vystak.yaml").write_text(
        "name: test-agent\n"
        "framework: langchain-python\n"
        "model:\n"
        "  provider:\n"
        "    type: anthropic\n"
        "  model_name: claude-sonnet-4-6\n"
    )
    return tmp_path


@pytest.fixture
def fake_agent():
    """Lightweight stand-in for the Agent schema with only the attrs handlers read.

    Handlers reference `agent.name` for default model strings; future phases will
    add `agent.model`, `agent.skills`, etc. Tests can extend by writing to the
    returned namespace.
    """
    return SimpleNamespace(name="weather")
