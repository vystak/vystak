from pathlib import Path

import pytest
from vystak.secrets.env_loader import EnvFileMissingError, load_env_file


def test_load_env_file_basic(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("FOO=bar\nBAZ=qux\n")
    result = load_env_file(p)
    assert result == {"FOO": "bar", "BAZ": "qux"}


def test_load_env_file_skips_comments_and_blank_lines(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("# comment\n\nFOO=bar\n\n# another\nBAZ=qux\n")
    result = load_env_file(p)
    assert result == {"FOO": "bar", "BAZ": "qux"}


def test_load_env_file_strips_quotes(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text('FOO="bar"\nBAZ=\'qux\'\n')
    result = load_env_file(p)
    assert result == {"FOO": "bar", "BAZ": "qux"}


def test_load_env_file_preserves_equals_in_value(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("URL=postgresql://u:p=w@h/db\n")
    result = load_env_file(p)
    assert result == {"URL": "postgresql://u:p=w@h/db"}


def test_load_env_file_missing_raises(tmp_path: Path):
    with pytest.raises(EnvFileMissingError):
        load_env_file(tmp_path / "does-not-exist.env")


def test_load_env_file_optional_returns_empty(tmp_path: Path):
    result = load_env_file(tmp_path / "nope.env", optional=True)
    assert result == {}
