"""Client configuration — saved agents, sessions, and user identity."""

import uuid
from pathlib import Path

import yaml

CONFIG_DIR = Path.home() / ".agentstack"
CONFIG_FILE = CONFIG_DIR / "client.yaml"

# Hardcoded user ID for now — will be replaced with auth later
DEFAULT_USER_ID = "user-00000000-0000-0000-0000-000000000001"


def _ensure_config() -> dict:
    """Load or create the config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        return yaml.safe_load(CONFIG_FILE.read_text()) or {}
    return {}


def _save_config(config: dict) -> None:
    """Save config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))


def get_user_id() -> str:
    """Get the current user ID."""
    config = _ensure_config()
    if "user_id" not in config:
        config["user_id"] = DEFAULT_USER_ID
        _save_config(config)
    return config["user_id"]


def list_agents() -> list[dict]:
    """List saved agents."""
    config = _ensure_config()
    return config.get("agents", [])


def add_agent(name: str, url: str) -> None:
    """Add or update a saved agent."""
    config = _ensure_config()
    agents = config.setdefault("agents", [])
    for agent in agents:
        if agent["name"] == name:
            agent["url"] = url
            _save_config(config)
            return
    agents.append({"name": name, "url": url})
    _save_config(config)


def get_agent(name: str) -> dict | None:
    """Get a saved agent by name."""
    for agent in list_agents():
        if agent["name"] == name:
            return agent
    return None


def remove_agent(name: str) -> bool:
    """Remove a saved agent."""
    config = _ensure_config()
    agents = config.get("agents", [])
    before = len(agents)
    config["agents"] = [a for a in agents if a["name"] != name]
    if len(config["agents"]) < before:
        _save_config(config)
        return True
    return False


def list_sessions() -> list[dict]:
    """List saved sessions."""
    config = _ensure_config()
    return config.get("sessions", [])


def create_session(agent_name: str, agent_url: str) -> dict:
    """Create a new session."""
    config = _ensure_config()
    sessions = config.setdefault("sessions", [])
    session = {
        "id": str(uuid.uuid4()),
        "agent_name": agent_name,
        "agent_url": agent_url,
        "user_id": get_user_id(),
    }
    sessions.append(session)
    _save_config(config)
    return session


def get_session(session_id: str) -> dict | None:
    """Get a session by ID."""
    for session in list_sessions():
        if session["id"] == session_id:
            return session
    return None


def get_sessions_for_agent(agent_name: str) -> list[dict]:
    """Get all sessions for a specific agent."""
    return [s for s in list_sessions() if s["agent_name"] == agent_name]
