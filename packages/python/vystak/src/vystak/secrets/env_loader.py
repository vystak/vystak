"""Minimal .env file parser for apply-time secret bootstrap."""

from pathlib import Path


class EnvFileMissingError(FileNotFoundError):
    """Raised when a required .env file is missing."""


def load_env_file(path: Path, *, optional: bool = False) -> dict[str, str]:
    """Parse a .env file into a dict.

    Supports: KEY=value, KEY="value", KEY='value'.
    Ignores: blank lines, lines starting with '#'.
    First '=' is the separator; subsequent '='s are part of the value.
    """
    if not path.exists():
        if optional:
            return {}
        raise EnvFileMissingError(f".env file not found: {path}")

    result: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        result[key] = value
    return result


__all__ = ["EnvFileMissingError", "load_env_file"]
