"""Abstract base classes for framework adapters, platform providers, and channel plugins."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel

from vystak.schema.agent import Agent
from vystak.schema.channel import Channel
from vystak.schema.common import AgentProtocol, ChannelType, RuntimeMode
from vystak.schema.platform import Platform

if TYPE_CHECKING:
    from vystak.provisioning import Provisionable


@dataclass
class GeneratedCode:
    files: dict[str, str]
    entrypoint: str


@dataclass
class DeployPlan:
    agent_name: str
    actions: list[str]
    current_hash: str | None
    target_hash: str
    changes: dict[str, tuple[str | None, str]]


@dataclass
class DeployResult:
    agent_name: str
    success: bool
    hash: str
    message: str


@dataclass
class AgentStatus:
    agent_name: str
    running: bool
    hash: str | None
    info: dict = field(default_factory=dict)


@dataclass
class ValidationError:
    field: str
    message: str


class FrameworkAdapter(ABC):
    @abstractmethod
    def generate(self, agent: Agent) -> GeneratedCode: ...

    @abstractmethod
    def validate(self, agent: Agent) -> list[ValidationError]: ...


class PlatformProvider(ABC):
    @abstractmethod
    def plan(self, agent: Agent, current_hash: str | None) -> DeployPlan: ...

    @abstractmethod
    def apply(self, plan: DeployPlan) -> DeployResult: ...

    @abstractmethod
    def destroy(self, agent_name: str) -> None: ...

    @abstractmethod
    def status(self, agent_name: str) -> AgentStatus: ...

    @abstractmethod
    def get_hash(self, agent_name: str) -> str | None: ...

    def plan_channel(self, channel: Channel, current_hash: str | None) -> DeployPlan:
        raise NotImplementedError(
            f"{type(self).__name__} does not support channel provisioning yet"
        )

    def apply_channel(
        self,
        plan: DeployPlan,
        channel: Channel,
        resolved_routes: dict[str, str],
    ) -> DeployResult:
        raise NotImplementedError(
            f"{type(self).__name__} does not support channel provisioning yet"
        )

    def destroy_channel(self, channel: Channel) -> None:
        """Destroy a deployed channel. Implementations MUST read deployment
        context (subscription, resource group, etc.) from channel.platform —
        NOT from any provider-level state that was set for agent lifecycles."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support channel provisioning yet"
        )

    def channel_status(self, channel: Channel) -> AgentStatus:
        raise NotImplementedError(
            f"{type(self).__name__} does not support channel provisioning yet"
        )

    def get_channel_hash(self, channel: Channel) -> str | None:
        raise NotImplementedError(
            f"{type(self).__name__} does not support channel provisioning yet"
        )


class ChannelPlugin(ABC):
    """Contract for a channel type. Registered via entry point `vystak.channels`.

    Implementations produce channel-pod source code, provisioning DAG fragments,
    thread URNs, and health signals. Core knows nothing about Slack, voice, etc.
    """

    type: ChannelType
    default_runtime_mode: RuntimeMode
    agent_protocol: AgentProtocol
    config_schema: type[BaseModel]

    @abstractmethod
    def generate_code(
        self, channel: Channel, resolved_routes: dict[str, str]
    ) -> GeneratedCode:
        """Emit channel-pod source code.

        `resolved_routes` maps agent name → URL reachable from the channel
        container. The CLI computes this from the deployed agents at apply time.
        """
        ...

    @abstractmethod
    def provision_nodes(
        self, channel: Channel, platform: Platform
    ) -> list["Provisionable"]: ...

    @abstractmethod
    def thread_name(self, event: dict) -> str: ...

    @abstractmethod
    def health_check(self, deployment: dict) -> str: ...
