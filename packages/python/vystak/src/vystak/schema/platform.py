"""Platform model — deployment target for agents."""

from vystak.schema.common import NamedModel
from vystak.schema.provider import Provider


class Platform(NamedModel):
    """A deployment target where agents run."""

    type: str
    provider: Provider
    config: dict = {}
