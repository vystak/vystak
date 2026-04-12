"""Abstract base classes for framework adapters, platform providers, and channel adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from agentstack.schema.agent import Agent
from agentstack.schema.channel import Channel


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


class ChannelAdapter(ABC):
    @abstractmethod
    def setup(self, agent: Agent, channel: Channel) -> None: ...

    @abstractmethod
    def teardown(self, channel: Channel) -> None: ...
