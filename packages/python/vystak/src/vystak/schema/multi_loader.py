"""Multi-agent YAML loader with named references."""

from vystak.schema.agent import Agent
from vystak.schema.channel import Channel
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider


def load_multi_yaml(data: dict) -> tuple[list[Agent], list[Channel]]:
    """Load multi-agent/multi-channel YAML with named providers, platforms, and models.

    String references in agents/channels are resolved to shared Python objects,
    so items referencing the same platform name get the same object (id).
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

    agents: list[Agent] = []
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
                    f"Unknown platform '{platform_ref}' in agent '{agent_data.get('name')}'. "
                    f"Defined platforms: {', '.join(platforms.keys())}"
                )
            agent_data["platform"] = platforms[platform_ref]

        agents.append(Agent.model_validate(agent_data))

    channels: list[Channel] = []
    for channel_data in data.get("channels", []):
        channel_data = dict(channel_data)

        platform_ref = channel_data.get("platform")
        if isinstance(platform_ref, str):
            if platform_ref not in platforms:
                raise KeyError(
                    f"Unknown platform '{platform_ref}' in channel '{channel_data.get('name')}'. "
                    f"Defined platforms: {', '.join(platforms.keys())}"
                )
            channel_data["platform"] = platforms[platform_ref]

        channels.append(Channel.model_validate(channel_data))

    return agents, channels
