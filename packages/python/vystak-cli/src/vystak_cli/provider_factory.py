"""Provider factory — selects the right PlatformProvider based on agent definition."""

from vystak.providers.base import PlatformProvider
from vystak.schema.agent import Agent


def get_provider(agent: Agent) -> PlatformProvider:
    """Return the appropriate PlatformProvider for the given agent."""
    if agent.platform is None or agent.platform.provider.type == "docker":
        from vystak_provider_docker import DockerProvider

        return DockerProvider()

    if agent.platform.provider.type == "azure":
        from vystak_provider_azure import AzureProvider

        return AzureProvider()

    raise ValueError(
        f"Unknown provider type: '{agent.platform.provider.type}'. "
        "Supported: docker, azure"
    )
