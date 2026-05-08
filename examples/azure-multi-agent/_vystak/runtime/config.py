"""Agent config loader — dispatches by extension to vystak.schema.loader."""

from pathlib import Path

from vystak.schema.agent import Agent
from vystak.schema.loader import load_agent as _load_yaml


def load_agent(path: str | Path) -> Agent:
    p = Path(path)
    if p.suffix in {".yaml", ".yml"}:
        return _load_yaml(p)
    if p.suffix == ".py":
        return _load_py(p)
    raise ValueError(f"Unsupported agent definition: {p}")


def _load_py(path: Path) -> Agent:
    import importlib.util
    spec = importlib.util.spec_from_file_location("_vystak_user_agent", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    agent = getattr(module, "agent", None)
    if agent is None:
        raise ValueError(f"{path} does not define a module-level `agent` binding")
    return agent
