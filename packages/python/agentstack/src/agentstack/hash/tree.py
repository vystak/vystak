"""Hash tree composition for agent definitions."""

import hashlib
from dataclasses import dataclass

from agentstack.hash.hasher import hash_model
from agentstack.schema.agent import Agent


@dataclass
class AgentHashTree:
    """Per-section hashes for an agent, enabling partial deploy detection."""

    brain: str
    skills: str
    mcp_servers: str
    channels: str
    workspace: str
    resources: str
    secrets: str
    sessions: str
    memory: str
    services: str
    root: str


def _hash_list(items: list) -> str:
    if not items:
        return hashlib.sha256(b"[]").hexdigest()
    individual = sorted(hash_model(item) for item in items)
    combined = "|".join(individual)
    return hashlib.sha256(combined.encode()).hexdigest()


def _hash_optional(item) -> str:
    if item is None:
        return hashlib.sha256(b"null").hexdigest()
    return hash_model(item)


def hash_agent(agent: Agent) -> AgentHashTree:
    """Compute the full hash tree for an agent definition."""
    brain = hash_model(agent.model)
    skills = _hash_list(agent.skills)
    mcp_servers = _hash_list(agent.mcp_servers)
    channels = _hash_list(agent.channels)
    workspace = _hash_optional(agent.workspace)
    resources = _hash_list(agent.resources)
    secrets = _hash_list(agent.secrets)
    sessions = _hash_optional(agent.sessions)
    memory = _hash_optional(agent.memory)
    services = _hash_list(agent.services)

    sections = "|".join([
        brain, skills, mcp_servers, channels, workspace,
        resources, secrets, sessions, memory, services,
    ])
    root = hashlib.sha256(sections.encode()).hexdigest()

    return AgentHashTree(
        brain=brain, skills=skills, mcp_servers=mcp_servers, channels=channels,
        workspace=workspace, resources=resources, secrets=secrets,
        sessions=sessions, memory=memory, services=services, root=root,
    )
