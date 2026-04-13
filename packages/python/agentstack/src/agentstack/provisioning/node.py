"""Provisionable protocol — a node in the dependency graph."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from agentstack.provisioning.health import HealthCheck, NoopHealthCheck


@dataclass
class ProvisionResult:
    name: str
    success: bool
    info: dict = field(default_factory=dict)
    error: str | None = None


class Provisionable(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def depends_on(self) -> list[str]:
        return []

    @abstractmethod
    def provision(self, context: dict) -> ProvisionResult: ...

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        pass
