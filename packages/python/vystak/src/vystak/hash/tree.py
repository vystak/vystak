"""Hash tree composition for agent and channel definitions."""

import hashlib
import json
from dataclasses import dataclass

from vystak.hash.hasher import hash_dict, hash_model
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
    # Compaction policy
    compaction: str
    # Heartbeat scheduler config (schedule, target_channel, prompt, enabled, etc.)
    heartbeat: str
    # Template digest. Captures the framework template's identity
    # (``_vystak/manifest.json`` ``template.{name, version}``) so a template
    # version bump triggers redeploy even when the Agent schema hasn't moved.
    # Defaults to "null" when callers don't have a manifest in hand at plan
    # time. Replaces the pre-Phase-9 ``codegen`` field which hashed emitted
    # server.py / Dockerfile strings.
    template: str
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
    # Build-artifact digest. Captures the channel plugin's emitted
    # ``Dockerfile`` / ``requirements.txt`` / ``channel_config.json`` so
    # changes to those build artifacts trigger redeploy even when the
    # channel schema hasn't moved. (Runnable channel code is the bundled
    # package itself, not emitted source.)
    codegen: str
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


def _hash_workspace_deploy(ws) -> str:
    """Hash the workspace minus fields that don't affect deploy identity.

    Volume.retention only governs destroy-time behavior.
    """
    if ws is None:
        return hashlib.sha256(b"null").hexdigest()
    data = ws.model_dump(mode="python")
    vol = data.get("volume")
    if isinstance(vol, dict):
        vol.pop("retention", None)
    return hash_dict(data)


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


def hash_generated_code(generated_code) -> str:
    """Hash the file contents of a FileBundle bundle.

    Order-stable across runs because we sort filenames before hashing.
    Empty / None bundles return the canonical "null" hash so the schema-
    only branch and the codegen-aware branch produce the same root when
    no generated code is in hand.

    Used by the channel hashing path. Agents now use
    :func:`hash_template_ref` instead — see :func:`hash_agent`.
    """
    if generated_code is None or not getattr(generated_code, "files", None):
        return _hash_str(None)
    items = sorted(generated_code.files.items())
    blob = "\n".join(f"{name}:{content}" for name, content in items)
    return hashlib.sha256(blob.encode()).hexdigest()


def hash_template_ref(template_ref: dict | None) -> str:
    """Hash a framework-template identity dict.

    ``template_ref`` should be the ``{"name": ..., "version": ...}`` block
    from ``_vystak/manifest.json``. Returns the canonical "null" hash when
    callers don't have a manifest in hand. Replaces the pre-Phase-9
    :func:`hash_generated_code` path for agents — instead of hashing the
    emitted server.py source, we now hash just the template version, since
    the user's project files are owned by the user (no longer regenerated
    on every apply).
    """
    if not template_ref:
        return _hash_str(None)
    name = template_ref.get("name")
    version = template_ref.get("version")
    if name is None and version is None:
        return _hash_str(None)
    blob = json.dumps({"name": name, "version": version}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def extract_template_ref(generated_code) -> dict | None:
    """Pull the ``{name, version}`` template-ref out of a bundled project.

    Looks for ``_vystak/manifest.json`` in the bundle's files and returns
    its ``template`` block. Returns ``None`` when the manifest is absent or
    malformed — callers should fall through to the canonical "null" hash
    via :func:`hash_template_ref(None)`.
    """
    if generated_code is None or not getattr(generated_code, "files", None):
        return None
    raw = generated_code.files.get("_vystak/manifest.json")
    if not raw:
        return None
    try:
        manifest = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    template = manifest.get("template") if isinstance(manifest, dict) else None
    if not isinstance(template, dict):
        return None
    return template


def hash_agent(agent: Agent, *, template_hash: str | None = None) -> AgentHashTree:
    """Compute the full hash tree for an agent definition.

    When ``template_hash`` is provided, it contributes to the root so a
    template version bump (e.g. ``langchain-python 0.1.0 → 0.2.0``) triggers
    redeploy even when the Agent schema hasn't moved. Callers in providers'
    ``plan()`` should pass ``hash_template_ref(template_ref)`` derived from
    the project's ``_vystak/manifest.json``. Defaults to the canonical
    "null" hash when no manifest is in hand.
    """
    # Sort by hash (consistent with _hash_list) so any reordering of
    # `agent.models` produces the same brain hash.
    brain_default = hash_model(agent.default_model)
    brain_models = sorted(hash_model(m) for m in agent.models)
    brain = hashlib.sha256(
        "|".join([brain_default, *brain_models]).encode()
    ).hexdigest()
    framework = _hash_str(agent.framework)
    skills = _hash_list(agent.skills)
    mcp_servers = _hash_list(agent.mcp_servers)
    workspace = _hash_workspace_deploy(agent.workspace)
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
    compaction = _hash_optional(agent.compaction)
    heartbeat = _hash_optional(agent.heartbeat)
    template = template_hash if template_hash is not None else _hash_str(None)

    sections = "|".join(
        [
            brain,
            framework,
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
            compaction,
            heartbeat,
            template,
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
        compaction=compaction,
        heartbeat=heartbeat,
        template=template,
        root=root,
    )


def hash_channel(
    channel: Channel,
    *,
    codegen_hash: str | None = None,
) -> ChannelHashTree:
    """Compute the full hash tree for a channel definition.

    When ``codegen_hash`` is provided, it contributes to the root so changes
    to the channel plugin's emitted build artifacts (Dockerfile,
    requirements, config json) bump the deploy hash even when the channel
    schema hasn't moved.
    """
    config = hashlib.sha256(repr(sorted(channel.config.items())).encode()).hexdigest()
    routes = _hash_list(channel.agents)
    mode = channel.runtime_mode.value if channel.runtime_mode else "default"
    pkg_ver = channel.channel_package_version or "null"
    rt_ver = channel.channel_runtime_version or "null"
    runtime = _hash_str(f"{channel.type.value}|{mode}|{pkg_ver}|{rt_ver}")
    secrets = _hash_list(channel.secrets)
    codegen = codegen_hash if codegen_hash is not None else _hash_str(None)

    sections = "|".join([config, routes, runtime, secrets, codegen])
    root = hashlib.sha256(sections.encode()).hexdigest()

    return ChannelHashTree(
        config=config,
        routes=routes,
        runtime=runtime,
        secrets=secrets,
        codegen=codegen,
        root=root,
    )
