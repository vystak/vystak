"""Hash tree composition for agent and channel definitions."""

import hashlib
import json
from dataclasses import dataclass

from vystak.hash.hasher import hash_model
from vystak.schema.agent import Agent
from vystak.schema.channel import Channel


@dataclass
class AgentHashTree:
    """Per-section hashes for an agent, enabling partial deploy detection."""

    brain: str
    skills: str
    mcp_servers: str
    workspace: str
    resources: str
    secrets: str
    sessions: str
    memory: str
    services: str
    transport: str
    root: str


@dataclass
class ChannelHashTree:
    """Per-section hashes for a channel, enabling partial deploy detection."""

    config: str
    routes: str
    runtime: str
    secrets: str
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


def _hash_str(value: str | None) -> str:
    if value is None:
        return hashlib.sha256(b"null").hexdigest()
    return hashlib.sha256(value.encode()).hexdigest()


def _hash_transport(agent: Agent) -> str:
    """Contribute transport identity (type + config) to the agent hash.

    `connection` is excluded — BYO URLs/credentials are portable across
    environments without triggering redeploy. `name` is also excluded —
    it's an identity field for cross-resource references, not config.
    """
    if agent.platform is None or agent.platform.transport is None:
        return _hash_str(None)
    transport = agent.platform.transport
    payload = {
        "type": transport.type,
        "config": transport.config.model_dump() if transport.config else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def hash_agent(agent: Agent) -> AgentHashTree:
    """Compute the full hash tree for an agent definition."""
    brain = hash_model(agent.model)
    skills = _hash_list(agent.skills)
    mcp_servers = _hash_list(agent.mcp_servers)
    workspace = _hash_optional(agent.workspace)
    resources = _hash_list(agent.resources)
    secrets = _hash_list(agent.secrets)
    sessions = _hash_optional(agent.sessions)
    memory = _hash_optional(agent.memory)
    services = _hash_list(agent.services)
    transport = _hash_transport(agent)

    sections = "|".join(
        [
            brain,
            skills,
            mcp_servers,
            workspace,
            resources,
            secrets,
            sessions,
            memory,
            services,
            transport,
        ]
    )
    root = hashlib.sha256(sections.encode()).hexdigest()

    return AgentHashTree(
        brain=brain,
        skills=skills,
        mcp_servers=mcp_servers,
        workspace=workspace,
        resources=resources,
        secrets=secrets,
        sessions=sessions,
        memory=memory,
        services=services,
        transport=transport,
        root=root,
    )


def hash_channel(channel: Channel) -> ChannelHashTree:
    """Compute the full hash tree for a channel definition."""
    config = hashlib.sha256(repr(sorted(channel.config.items())).encode()).hexdigest()
    routes = _hash_list(channel.routes)
    mode = channel.runtime_mode.value if channel.runtime_mode else "default"
    runtime = _hash_str(f"{channel.type.value}|{mode}")
    secrets = _hash_list(channel.secrets)

    sections = "|".join([config, routes, runtime, secrets])
    root = hashlib.sha256(sections.encode()).hexdigest()

    return ChannelHashTree(
        config=config,
        routes=routes,
        runtime=runtime,
        secrets=secrets,
        root=root,
    )
