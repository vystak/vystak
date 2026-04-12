"""Agent definition discovery and loading."""

import importlib.util
import sys
from pathlib import Path

from agentstack.schema.agent import Agent
from agentstack.schema.loader import load_agent

CONVENTION_FILES = ["agentstack.yaml", "agentstack.yml", "agentstack.py"]


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
        f"No agent definition found. Create agentstack.yaml or specify --file. "
        f"Searched: {search_dir}"
    )


def load_agent_from_file(path: Path) -> Agent:
    """Load an Agent from a YAML/JSON or Python file."""
    path = Path(path)

    if path.suffix in (".yaml", ".yml", ".json"):
        return load_agent(path)

    if path.suffix == ".py":
        spec = importlib.util.spec_from_file_location("_agentstack_def", str(path))
        module = importlib.util.module_from_spec(spec)
        sys.modules["_agentstack_def"] = module
        spec.loader.exec_module(module)
        del sys.modules["_agentstack_def"]

        if not hasattr(module, "agent"):
            raise ValueError(
                f"Python file {path} must define an 'agent' variable of type Agent"
            )

        agent = module.agent
        if not isinstance(agent, Agent):
            raise ValueError(
                f"'agent' variable in {path} must be an Agent instance, got {type(agent)}"
            )
        return agent

    raise ValueError(f"Unsupported file type: {path.suffix}")
