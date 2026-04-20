"""Agent and channel definition discovery and loading."""

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vystak.schema.overrides import EnvironmentOverride

import yaml

# Ensure the real vystak package (not a local vystak.py) is imported
# first by temporarily stripping the cwd sentinel from sys.path.
_cwd_entries = [p for p in sys.path if p in ("", ".")]
for _e in _cwd_entries:
    sys.path.remove(_e)
try:
    from vystak.schema.agent import Agent
    from vystak.schema.channel import Channel
    from vystak.schema.config_loader import load_base_config, merge_configs
    from vystak.schema.loader import load_agent
    from vystak.schema.multi_loader import load_multi_yaml
    from vystak.schema.vault import Vault
finally:
    sys.path = _cwd_entries + sys.path

CONVENTION_FILES = ["vystak.yaml", "vystak.yml", "vystak.py"]


@dataclass
class Definitions:
    """Loaded top-level deployables."""

    agents: list[Agent] = field(default_factory=list)
    channels: list[Channel] = field(default_factory=list)
    vault: Vault | None = None

    def extend(self, other: "Definitions") -> None:
        self.agents.extend(other.agents)
        self.channels.extend(other.channels)
        # Last-wins on vault — callers that merge multiple files with
        # conflicting vaults should expect the trailing declaration to stick.
        if other.vault is not None:
            self.vault = other.vault


def find_agent_file(file: str | None = None, search_dir: Path | None = None) -> Path:
    """Find the agent definition file."""
    if file is not None:
        path = Path(file)
        if not path.exists():
            raise FileNotFoundError(f"Agent definition not found: {path}")
        return path

    search_dir = search_dir or Path.cwd()
    for name in CONVENTION_FILES:
        path = search_dir / name
        if path.exists():
            return path

    raise FileNotFoundError(
        f"No agent definition found. Create vystak.yaml or specify --file. Searched: {search_dir}"
    )


def load_agent_from_file(path: Path) -> Agent:
    """Load a single Agent from a YAML/JSON or Python file."""
    path = Path(path)

    if path.suffix in (".yaml", ".yml", ".json"):
        return load_agent(path)

    if path.suffix == ".py":
        module = _exec_python_file(path)

        if not hasattr(module, "agent"):
            raise ValueError(f"Python file {path} must define an 'agent' variable of type Agent")

        agent = module.agent
        if not isinstance(agent, Agent):
            raise ValueError(
                f"'agent' variable in {path} must be an Agent instance, got {type(agent)}"
            )
        return agent

    raise ValueError(f"Unsupported file type: {path.suffix}")


def load_definitions(paths: list[Path], base_dir: Path | None = None) -> Definitions:
    """Load agents and channels from one or more files/directories."""
    if base_dir is None and paths:
        first = paths[0]
        base_dir = (
            first.parent if first.is_file() else first.parent if first.is_dir() else Path.cwd()
        )
    base_config = load_base_config(base_dir) if base_dir else {}

    defs = Definitions()

    for path in paths:
        path = Path(path)

        if path.is_dir():
            found = None
            for conv in CONVENTION_FILES:
                candidate = path / conv
                if candidate.exists():
                    found = candidate
                    break
            if found is None:
                raise FileNotFoundError(f"No agent definition found in {path}")
            path = found

        if path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(path.read_text()) or {}

            if "agents" in data or "channels" in data:
                merged = merge_configs(base_config, data) if base_config else data
                agents, channels, vault = load_multi_yaml(merged)
                defs.agents.extend(agents)
                defs.channels.extend(channels)
                if vault is not None:
                    defs.vault = vault
            elif isinstance(data.get("model"), str) or isinstance(data.get("platform"), str):
                merged = dict(base_config)
                if "agents" not in merged:
                    merged["agents"] = []
                merged["agents"].append(data)
                agents, channels, vault = load_multi_yaml(merged)
                defs.agents.extend(agents)
                defs.channels.extend(channels)
                if vault is not None:
                    defs.vault = vault
            else:
                defs.agents.append(load_agent(path))

        elif path.suffix == ".py":
            defs.extend(_load_definitions_from_python(path))
        else:
            raise ValueError(f"Unsupported file type: {path.suffix}")

    return defs


def _load_definitions_from_python(path: Path) -> Definitions:
    """Load all Agent and Channel instances from a Python file."""
    module = _exec_python_file(path)

    defs = Definitions()
    for name in dir(module):
        if name.startswith("_"):
            continue
        obj = getattr(module, name)
        if isinstance(obj, Agent):
            defs.agents.append(obj)
        elif isinstance(obj, Channel):
            defs.channels.append(obj)

    if not defs.agents and hasattr(module, "agent") and isinstance(module.agent, Agent):
        defs.agents.append(module.agent)

    if not defs.agents and not defs.channels:
        raise ValueError(f"No Agent or Channel instances found in {path}")

    return defs


def load_environment_override(base_path: Path, env: str) -> "EnvironmentOverride":
    """Look for vystak.<env>.py next to base_path; return its `override`.

    Raises FileNotFoundError if no overlay file exists and `env` is set.
    """
    from vystak.schema.overrides import EnvironmentOverride

    overlay_path = base_path.parent / f"vystak.{env}.py"
    if not overlay_path.exists():
        raise FileNotFoundError(
            f"env={env!r} requested but no {overlay_path.name} next to {base_path}"
        )
    module = _exec_python_file(overlay_path)
    override = getattr(module, "override", None)
    if not isinstance(override, EnvironmentOverride):
        raise ValueError(
            f"{overlay_path} must define `override: EnvironmentOverride`; "
            f"got {type(override).__name__ if override else 'None'}"
        )
    return override


def _exec_python_file(path: Path):
    spec = importlib.util.spec_from_file_location("_vystak_def", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules["_vystak_def"] = module

    file_dir = str(path.parent.resolve())
    removed = file_dir in sys.path
    if removed:
        sys.path.remove(file_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        if removed:
            sys.path.insert(0, file_dir)
    del sys.modules["_vystak_def"]
    return module
