"""Pytest configuration for vystak-template-langchain-python tests."""

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
