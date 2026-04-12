"""Gateway and ChannelProvider models."""

from agentstack.schema.common import NamedModel
from agentstack.schema.provider import Provider


class Gateway(NamedModel):
    """A running service that manages channel provider connections."""

    provider: Provider
    config: dict = {}


class ChannelProvider(NamedModel):
    """A bot connection managed by a gateway."""

    type: str
    gateway: Gateway
    config: dict = {}
