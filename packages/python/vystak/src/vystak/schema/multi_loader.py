"""Multi-agent YAML loader with named references."""

from vystak.schema.agent import Agent
from vystak.schema.channel import Channel
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.vault import Vault
from vystak.schema.volume import Volume


def _validate_vault_provider_pairing(vault: Vault) -> None:
    """Enforce Vault.type ↔ Provider.type coupling at load time."""
    from vystak.schema.common import VaultType

    provider_type = vault.provider.type
    if vault.type is VaultType.KEY_VAULT and provider_type != "azure":
        raise ValueError(
            f"Vault '{vault.name}' has type='key-vault' requires "
            f"provider.type='azure'. Current: provider.type='{provider_type}'."
        )
    if vault.type is VaultType.VAULT and provider_type != "docker":
        raise ValueError(
            f"Vault '{vault.name}' has type='vault' requires "
            f"provider.type='docker'. Current: provider.type='{provider_type}'."
        )


def _validate_schedule_targets(
    agents: list[Agent], channels: list[Channel],
) -> None:
    """Cross-deployable check: every agent.heartbeat.target_channel and
    every agent.schedules[*].target_channel must name a real channel that
    routes this agent; any explicit model name must be in the agent's
    model pool. Unlike heartbeat, a schedule's target_channel may be None
    (log-only delivery)."""
    channels_by_canonical = {c.canonical_name: c for c in channels}
    for agent in agents:
        if agent.heartbeat is None:
            continue
        target = agent.heartbeat.target_channel
        channel = channels_by_canonical.get(target)
        if channel is None:
            raise ValueError(
                f"agent '{agent.name}' heartbeat.target_channel "
                f"'{target}' does not match any declared channel "
                f"(have: {sorted(channels_by_canonical)})"
            )
        routed = {a.name for a in channel.agents}
        if agent.name not in routed:
            raise ValueError(
                f"channel '{target}' does not route agent '{agent.name}' "
                f"named in its heartbeat.target_channel"
            )
        if agent.heartbeat.model is not None:
            pool = {agent.default_model.name, *(m.name for m in agent.models)}
            if agent.heartbeat.model not in pool:
                raise ValueError(
                    f"agent '{agent.name}' heartbeat.model "
                    f"'{agent.heartbeat.model}' not in agent's model pool "
                    f"(have: {sorted(pool)})"
                )

    for agent in agents:
        pool = {agent.default_model.name} | {m.name for m in agent.models}
        for t in agent.schedules:
            if t.target_channel is not None:
                target = t.target_channel
                channel = channels_by_canonical.get(target)
                if channel is None:
                    raise ValueError(
                        f"agent '{agent.name}' schedules[{t.name}].target_channel "
                        f"'{target}' does not match any declared channel "
                        f"(have: {sorted(channels_by_canonical)})"
                    )
                routed = {a.name for a in channel.agents}
                if agent.name not in routed:
                    raise ValueError(
                        f"channel '{target}' does not route agent '{agent.name}' "
                        f"named in its schedules[{t.name}].target_channel"
                    )
            if t.model is not None and t.model not in pool:
                raise ValueError(
                    f"agent '{agent.name}' schedules[{t.name}].model "
                    f"'{t.model}' not in agent's model pool {sorted(pool)}"
                )


def _validate_workspace_platform_volume(agent: Agent) -> None:
    """Reject volume modes unsupported by the target platform.

    ACA (container-apps) has no host filesystem — mode='bind' is
    fundamentally unserviceable. Catch it at load time with an actionable
    message so users aren't debugging a failed deploy later.
    """
    ws = agent.workspace
    if ws is None:
        return
    vol = ws.effective_volume
    if vol.mode == "bind" and agent.platform.type == "container-apps":
        raise ValueError(
            f"Agent '{agent.name}': workspace volume '{vol.name}' has "
            f"mode='bind', which is not supported on Azure Container Apps "
            f"(no host filesystem). Use mode='persistent' (Azure Files) "
            f"or 'ephemeral'."
        )


def _lookup_agent(by_name: dict, name: str, field: str, ctx: str) -> object:
    if name not in by_name:
        raise KeyError(
            f"Unknown agent '{name}' in channel '{ctx}' field '{field}'. "
            f"Defined agents: {', '.join(sorted(by_name))}"
        )
    return by_name[name]


def _resolve_channel_agent_refs(
    channel_data: dict,
    agents_by_name: dict,
) -> dict:
    """Resolve string agent references in a channel block.

    Applies to any channel type that uses the unified `agents` /
    `channel_overrides` / `default_agent` fields (Slack, chat, Discord, etc.).
    """
    if channel_data.get("type") not in ("slack", "chat", "discord"):
        return channel_data
    data = dict(channel_data)
    if "agents" in data:
        data["agents"] = [
            _lookup_agent(agents_by_name, name, "agents", channel_data["name"])
            for name in data["agents"]
        ]
    if "default_agent" in data and isinstance(data["default_agent"], str):
        data["default_agent"] = _lookup_agent(
            agents_by_name, data["default_agent"],
            "default_agent", channel_data["name"],
        )
    if "channel_overrides" in data:
        new_ov = {}
        for cid, ov in data["channel_overrides"].items():
            ov = dict(ov)
            if isinstance(ov.get("agent"), str):
                ov["agent"] = _lookup_agent(
                    agents_by_name, ov["agent"],
                    f"channel_overrides[{cid}].agent",
                    channel_data["name"],
                )
            new_ov[cid] = ov
        data["channel_overrides"] = new_ov
    return data


def _resolve_agent_subagent_refs(
    agent_data: dict,
    agents_by_name: dict,
) -> dict:
    """Resolve string subagent references on an agent block to Agent objects."""
    if "subagents" not in agent_data:
        return agent_data
    data = dict(agent_data)
    resolved = []
    for ref in data["subagents"]:
        if isinstance(ref, str):
            if ref not in agents_by_name:
                raise KeyError(
                    f"Unknown subagent '{ref}' in agent "
                    f"'{agent_data.get('name')}' field 'subagents'. "
                    f"Defined agents: {', '.join(sorted(agents_by_name))}"
                )
            resolved.append(agents_by_name[ref])
        else:
            resolved.append(ref)
    data["subagents"] = resolved
    return data


def load_multi_yaml(
    data: dict,
) -> tuple[list[Agent], list[Channel], Vault | None]:
    """Load multi-agent/multi-channel YAML with named providers, platforms, models, vault.

    String references in agents/channels are resolved to shared Python objects,
    so items referencing the same platform name get the same object (id).

    Returns (agents, channels, vault). Vault is None when not declared.
    """
    providers: dict[str, Provider] = {}
    for name, cfg in data.get("providers", {}).items():
        providers[name] = Provider(name=name, **cfg)

    platforms: dict[str, Platform] = {}
    for name, cfg in data.get("platforms", {}).items():
        cfg = dict(cfg)
        provider_ref = cfg.pop("provider")
        if provider_ref not in providers:
            raise KeyError(
                f"Unknown provider '{provider_ref}' in platform '{name}'. "
                f"Defined providers: {', '.join(providers.keys())}"
            )
        platforms[name] = Platform(name=name, provider=providers[provider_ref], **cfg)

    vault: Vault | None = None
    vault_cfg = data.get("vault")
    if vault_cfg is not None:
        vault_cfg = dict(vault_cfg)
        provider_ref = vault_cfg.pop("provider")
        if provider_ref not in providers:
            raise KeyError(
                f"Unknown provider '{provider_ref}' in vault "
                f"'{vault_cfg.get('name')}'. "
                f"Defined providers: {', '.join(providers.keys())}"
            )
        vault = Vault(provider=providers[provider_ref], **vault_cfg)

    if vault is not None:
        _validate_vault_provider_pairing(vault)

    models: dict[str, Model] = {}
    for name, cfg in data.get("models", {}).items():
        cfg = dict(cfg)
        provider_ref = cfg.pop("provider")
        if provider_ref not in providers:
            raise KeyError(
                f"Unknown provider '{provider_ref}' in model '{name}'. "
                f"Defined providers: {', '.join(providers.keys())}"
            )
        models[name] = Model(name=name, provider=providers[provider_ref], **cfg)

    volumes: dict[str, Volume] = {}
    for name, cfg in data.get("volumes", {}).items():
        volumes[name] = Volume(name=name, **cfg)

    # Phase 1: build all agents without their `subagents` field so we have a
    # name → Agent map for cross-resolution.
    agent_data_list: list[dict] = []
    raw_subagents: dict[str, list] = {}
    for agent_data in data.get("agents", []):
        agent_data = dict(agent_data)

        model_ref = agent_data.get("default_model")
        if isinstance(model_ref, str):
            if model_ref not in models:
                raise KeyError(
                    f"Unknown model '{model_ref}' in agent '{agent_data.get('name')}'. "
                    f"Defined models: {', '.join(models.keys())}"
                )
            agent_data["default_model"] = models[model_ref]

        platform_ref = agent_data.get("platform")
        if isinstance(platform_ref, str):
            if platform_ref not in platforms:
                raise KeyError(
                    f"Unknown platform '{platform_ref}' in agent "
                    f"'{agent_data.get('name')}'. "
                    f"Defined platforms: {', '.join(platforms.keys())}"
                )
            agent_data["platform"] = platforms[platform_ref]

        if "models" in agent_data and isinstance(agent_data["models"], list):
            resolved_models = []
            for model_ref in agent_data["models"]:
                if isinstance(model_ref, str):
                    if model_ref not in models:
                        raise KeyError(
                            f"Unknown model '{model_ref}' in agent "
                            f"'{agent_data.get('name')}' models pool. "
                            f"Defined models: {', '.join(models.keys())}"
                        )
                    resolved_models.append(models[model_ref])
                else:
                    resolved_models.append(model_ref)
            agent_data["models"] = resolved_models

        ws_data = agent_data.get("workspace")
        if isinstance(ws_data, dict) and isinstance(ws_data.get("volume"), str):
            vol_ref = ws_data["volume"]
            if vol_ref not in volumes:
                raise KeyError(
                    f"Unknown volume '{vol_ref}' in agent "
                    f"'{agent_data.get('name')}' workspace. "
                    f"Defined volumes: {', '.join(sorted(volumes))}"
                )
            ws_data = dict(ws_data)
            ws_data["volume"] = volumes[vol_ref]
            agent_data["workspace"] = ws_data

        # Stash subagents for phase 2, build agent without them so model_validate works.
        if "subagents" in agent_data:
            raw_subagents[agent_data["name"]] = agent_data.pop("subagents")
        agent_data_list.append(agent_data)

    agents: list[Agent] = [Agent.model_validate(d) for d in agent_data_list]
    for agent in agents:
        _validate_workspace_platform_volume(agent)
    agents_by_name = {a.name: a for a in agents}

    # Phase 2: re-attach subagents now that all agents exist.
    for agent in agents:
        if agent.name not in raw_subagents:
            continue
        resolved_payload = _resolve_agent_subagent_refs(
            {"name": agent.name, "subagents": raw_subagents[agent.name]},
            agents_by_name,
        )
        agent.subagents = resolved_payload["subagents"]
        # Re-run after-validators (self-reference + duplicate-name checks)
        Agent.model_validate(agent.model_dump())

    channels: list[Channel] = []
    for channel_data in data.get("channels", []):
        channel_data = dict(channel_data)

        platform_ref = channel_data.get("platform")
        if isinstance(platform_ref, str):
            if platform_ref not in platforms:
                raise KeyError(
                    f"Unknown platform '{platform_ref}' in channel "
                    f"'{channel_data.get('name')}'. "
                    f"Defined platforms: {', '.join(platforms.keys())}"
                )
            channel_data["platform"] = platforms[platform_ref]

        channel_data = _resolve_channel_agent_refs(channel_data, agents_by_name)
        channels.append(Channel.model_validate(channel_data))

    _validate_schedule_targets(agents, channels)

    return agents, channels, vault
