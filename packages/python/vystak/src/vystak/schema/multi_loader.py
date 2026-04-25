"""Multi-agent YAML loader with named references."""

from vystak.schema.agent import Agent
from vystak.schema.channel import Channel
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.vault import Vault


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
    """Resolve string agent references in a Slack channel block."""
    if channel_data.get("type") != "slack":
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

    # Phase 1: build all agents without their `subagents` field so we have a
    # name → Agent map for cross-resolution.
    agent_data_list: list[dict] = []
    raw_subagents: dict[str, list] = {}
    for agent_data in data.get("agents", []):
        agent_data = dict(agent_data)

        model_ref = agent_data.get("model")
        if isinstance(model_ref, str):
            if model_ref not in models:
                raise KeyError(
                    f"Unknown model '{model_ref}' in agent '{agent_data.get('name')}'. "
                    f"Defined models: {', '.join(models.keys())}"
                )
            agent_data["model"] = models[model_ref]

        platform_ref = agent_data.get("platform")
        if isinstance(platform_ref, str):
            if platform_ref not in platforms:
                raise KeyError(
                    f"Unknown platform '{platform_ref}' in agent "
                    f"'{agent_data.get('name')}'. "
                    f"Defined platforms: {', '.join(platforms.keys())}"
                )
            agent_data["platform"] = platforms[platform_ref]

        # Stash subagents for phase 2, build agent without them so model_validate works.
        if "subagents" in agent_data:
            raw_subagents[agent_data["name"]] = agent_data.pop("subagents")
        agent_data_list.append(agent_data)

    agents: list[Agent] = [Agent.model_validate(d) for d in agent_data_list]
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

    return agents, channels, vault
