"""Platform model — deployment target for agents."""

from typing import Self

from pydantic import BaseModel, model_validator

from vystak.schema.common import NamedModel
from vystak.schema.provider import Provider
from vystak.schema.telemetry import Telemetry
from vystak.schema.transport import Transport


class SchedulerConfig(BaseModel):
    """Toggle for auto-provisioning the scheduler (vystak-heartbeat)
    container even when no agent on the platform declares a schedule."""

    enabled: bool = False


class Platform(NamedModel):
    """A deployment target where agents run."""

    type: str
    provider: Provider
    namespace: str = "default"
    config: dict = {}
    transport: Transport | None = None
    telemetry: Telemetry | None = None
    scheduler: SchedulerConfig | None = None

    @model_validator(mode="after")
    def _default_transport(self) -> Self:
        if self.transport is None:
            self.transport = Transport(name="default-http", type="http")
        return self
