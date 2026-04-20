"""Channel model — top-level deployable I/O adapter for agent communication."""

from pydantic import BaseModel

from vystak.schema.common import ChannelType, NamedModel, RuntimeMode
from vystak.schema.platform import Platform
from vystak.schema.secret import Secret


class RouteRule(BaseModel):
    """Deploy-time routing policy: match channel-native criteria, dispatch to agent by name.

    `match` is opaque at the core level — each channel plugin defines its own shape
    (e.g. {"slack_channel": "C0123"} or {"phone_number": "+15551234"}). The agent
    name is resolved via DNS at runtime using Agent.canonical_name.
    """

    match: dict = {}
    agent: str


class Channel(NamedModel):
    """A top-level channel deployable — sibling of Agent.

    Channels own their own platform, runtime, and routing policy. Agents do not
    declare channels; channels declare which agents they route to via `routes`.
    """

    type: ChannelType
    platform: Platform
    config: dict = {}
    runtime_mode: RuntimeMode | None = None
    routes: list[RouteRule] = []
    secrets: list[Secret] = []

    @property
    def canonical_name(self) -> str:
        return f"{self.name}.channels.{self.platform.namespace}"
