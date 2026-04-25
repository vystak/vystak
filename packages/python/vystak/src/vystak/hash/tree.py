"""Hash tree composition for agent and channel definitions."""

import hashlib
import json
from dataclasses import dataclass

from vystak.hash.hasher import hash_model
from vystak.schema.agent import Agent
from vystak.schema.channel import Channel
from vystak.schema.workspace import Workspace


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
    subagents: str
    # v1 Secret Manager additions
    workspace_identity: str
    grants: str
    root: str


@dataclass
class WorkspaceHashTree:
    """Per-section hashes for a workspace — identity + secret grant set."""

    identity: str
    secrets: str
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


def hash_workspace(ws: Workspace) -> WorkspaceHashTree:
    """Compute the hash tree for a workspace (identity + secret declarations)."""
    identity = _hash_str(ws.identity)
    secrets = _hash_list(ws.secrets)
    root = hashlib.sha256(f"{identity}|{secrets}".encode()).hexdigest()
    return WorkspaceHashTree(identity=identity, secrets=secrets, root=root)


def compute_grants_hash(agent: Agent) -> str:
    """Compute a deterministic hash of the (role, secret_name) grant set
    derived from the agent tree (agent-level secrets + workspace secrets)."""
    pairs: list[tuple[str, str]] = []
    pairs.extend(("agent", s.name) for s in agent.secrets)
    if agent.workspace:
        pairs.extend(("workspace", s.name) for s in agent.workspace.secrets)
    pairs.sort()
    blob = "|".join(f"{role}:{name}" for role, name in pairs)
    return hashlib.sha256(blob.encode()).hexdigest()


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


def _hash_subagents(agent: Agent) -> str:
    """Contribute declared subagent identities to the agent hash.

    Order-insensitive (sorted) — declaring [weather, time] and [time, weather]
    produces the same hash. Uses canonical_name so namespace changes propagate.
    """
    if not agent.subagents:
        return _hash_str(None)
    names = sorted(peer.canonical_name for peer in agent.subagents)
    return hashlib.sha256("|".join(names).encode()).hexdigest()


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
    subagents = _hash_subagents(agent)

    workspace_identity = (
        hash_workspace(agent.workspace).identity
        if agent.workspace
        else _hash_str(None)
    )
    grants = compute_grants_hash(agent)

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
            subagents,
            workspace_identity,
            grants,
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
        subagents=subagents,
        workspace_identity=workspace_identity,
        grants=grants,
        root=root,
    )


def hash_channel(channel: Channel) -> ChannelHashTree:
    """Compute the full hash tree for a channel definition."""
    config = hashlib.sha256(repr(sorted(channel.config.items())).encode()).hexdigest()
    routes = _hash_list(channel.agents)
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
