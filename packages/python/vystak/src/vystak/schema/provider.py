"""Provider model — who provisions infrastructure."""

from vystak.schema.common import NamedModel


class Provider(NamedModel):
    """A provider that provisions infrastructure or services."""

    type: str
    config: dict = {}
