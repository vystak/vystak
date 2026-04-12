"""Platform model — deployment target for agents."""

from agentstack.schema.common import NamedModel
from agentstack.schema.provider import Provider


class Platform(NamedModel):
    """A deployment target where agents run."""

    type: str
    provider: Provider
    config: dict = {}
