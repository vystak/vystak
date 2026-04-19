"""Platform model — deployment target for agents."""

from typing import Self

from pydantic import model_validator

from vystak.schema.common import NamedModel
from vystak.schema.provider import Provider
from vystak.schema.transport import Transport


class Platform(NamedModel):
    """A deployment target where agents run."""

    type: str
    provider: Provider
    namespace: str = "default"
    config: dict = {}
    transport: Transport | None = None

    @model_validator(mode="after")
    def _default_transport(self) -> Self:
        if self.transport is None:
            self.transport = Transport(name="default-http", type="http")
        return self
