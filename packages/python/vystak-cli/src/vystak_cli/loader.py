"""Agent definition discovery and loading."""

import importlib.util
import sys
from pathlib import Path

import yaml

# Ensure the real vystak package (not a local vystak.py) is imported
# first by temporarily stripping the cwd sentinel from sys.path.
_cwd_entries = [p for p in sys.path if p in ("", ".")]
for _e in _cwd_entries:
    sys.path.remove(_e)
try:
    from vystak.schema.agent import Agent
    from vystak.schema.config_loader import load_base_config, merge_configs
    from vystak.schema.loader import load_agent
    from vystak.schema.multi_loader import load_multi_agent_yaml
finally:
    sys.path = _cwd_entries + sys.path

CONVENTION_FILES = ["vystak.yaml", "vystak.yml", "vystak.py"]


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
    """Load an Agent from a YAML/JSON or Python file."""
    path = Path(path)

    if path.suffix in (".yaml", ".yml", ".json"):
        return load_agent(path)

    if path.suffix == ".py":
        spec = importlib.util.spec_from_file_location("_vystak_def", str(path))
        module = importlib.util.module_from_spec(spec)
        sys.modules["_vystak_def"] = module
        # Temporarily remove the file's directory from sys.path so that a file
        # named vystak.py does not shadow the real vystak package.
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

        if not hasattr(module, "agent"):
            raise ValueError(f"Python file {path} must define an 'agent' variable of type Agent")

        agent = module.agent
        if not isinstance(agent, Agent):
            raise ValueError(
                f"'agent' variable in {path} must be an Agent instance, got {type(agent)}"
            )
        return agent

    raise ValueError(f"Unsupported file type: {path.suffix}")


def load_agents(paths: list[Path], base_dir: Path | None = None) -> list[Agent]:
    """Load agents from one or more files/directories."""
    if base_dir is None and paths:
        first = paths[0]
        base_dir = (
            first.parent if first.is_file() else first.parent if first.is_dir() else Path.cwd()
        )
    base_config = load_base_config(base_dir) if base_dir else {}

    all_agents: list[Agent] = []

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

            if "agents" in data:
                merged = merge_configs(base_config, data) if base_config else data
                all_agents.extend(load_multi_agent_yaml(merged))
            elif isinstance(data.get("model"), str) or isinstance(data.get("platform"), str):
                merged = dict(base_config)
                if "agents" not in merged:
                    merged["agents"] = []
                merged["agents"].append(data)
                all_agents.extend(load_multi_agent_yaml(merged))
            else:
                all_agents.append(load_agent(path))

        elif path.suffix == ".py":
            all_agents.extend(_load_agents_from_python(path))
        else:
            raise ValueError(f"Unsupported file type: {path.suffix}")

    return all_agents


def _load_agents_from_python(path: Path) -> list[Agent]:
    """Load all Agent instances from a Python file."""
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

    agents = []
    for name in dir(module):
        if name.startswith("_"):
            continue
        obj = getattr(module, name)
        if isinstance(obj, Agent):
            agents.append(obj)

    if not agents and hasattr(module, "agent") and isinstance(module.agent, Agent):
        agents.append(module.agent)

    if not agents:
        raise ValueError(f"No Agent instances found in {path}")

    return agents
