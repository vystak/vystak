"""YAML/JSON loading and dumping for agent definitions."""

import json
from pathlib import Path

import yaml

from vystak.schema.agent import Agent


def load_agent(path: str | Path) -> Agent:
    """Load an agent definition from a YAML or JSON file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Agent definition not found: {path}")

    text = path.read_text()
    suffix = path.suffix.lower()

    if suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Use .yaml, .yml, or .json")

    if isinstance(data, dict) and data.get("subagents"):
        raise ValueError(
            "subagents requires the multi-document YAML layout "
            "(top-level providers/platforms/models/agents/channels). "
            "See docs/concepts/multi-agent.md."
        )

    return Agent.model_validate(data)


def dump_agent(agent: Agent, path: str | Path, format: str = "yaml") -> None:
    """Serialize an agent definition to a YAML or JSON file."""
    path = Path(path)
    if format == "yaml":
        data = agent.model_dump(mode="json")
        text = yaml.dump(data, default_flow_style=False, sort_keys=False)
    elif format == "json":
        data = agent.model_dump(mode="python")
        text = json.dumps(data, indent=2, default=str)
    else:
        raise ValueError(f"Unsupported format: {format}. Use 'yaml' or 'json'")

    path.write_text(text)
