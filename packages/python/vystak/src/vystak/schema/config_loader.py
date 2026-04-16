"""Base + env config loading with deep merge."""

import os
from pathlib import Path

import yaml


def merge_configs(base: dict, override: dict) -> dict:
    """Deep merge override into base. Override values win for leaf keys."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result


def resolve_env_file(directory: Path, env: str | None = None) -> Path | None:
    """Find the env config file by convention."""
    if env is None:
        env = os.environ.get("VYSTAK_ENV")

    path = directory / f"vystak.env.{env}.yaml" if env else directory / "vystak.env.yaml"

    return path if path.exists() else None


def load_base_config(directory: Path) -> dict:
    """Load vystak.base.yaml + vystak.env[.name].yaml, merged."""
    base_path = directory / "vystak.base.yaml"
    if not base_path.exists():
        return {}

    base = yaml.safe_load(base_path.read_text()) or {}

    env_path = resolve_env_file(directory)
    if env_path:
        env_data = yaml.safe_load(env_path.read_text()) or {}
        base = merge_configs(base, env_data)

    return base
