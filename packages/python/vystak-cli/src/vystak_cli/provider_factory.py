"""Provider factory — selects the right PlatformProvider based on a deployable's platform."""

from vystak.providers.base import PlatformProvider
from vystak.schema.agent import Agent
from vystak.schema.channel import Channel


def get_provider(deployable: Agent | Channel) -> PlatformProvider:
    """Return the appropriate PlatformProvider for the given agent or channel."""
    platform = deployable.platform

    if platform is None or platform.provider.type == "docker":
        from vystak_provider_docker import DockerProvider

        return DockerProvider()

    if platform.provider.type == "azure":
        from vystak_provider_azure import AzureProvider

        return AzureProvider()

    raise ValueError(f"Unknown provider type: '{platform.provider.type}'. Supported: docker, azure")
