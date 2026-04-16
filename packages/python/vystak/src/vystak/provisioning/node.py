"""Provisionable protocol — a node in the dependency graph."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from vystak.provisioning.health import HealthCheck, NoopHealthCheck


@dataclass
class ProvisionResult:
    name: str
    success: bool
    info: dict = field(default_factory=dict)
    error: str | None = None


class Provisionable(ABC):
    _listener = None

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

    def destroy(self) -> None:  # noqa: B027 — default no-op; subclasses may override
        pass

    def set_listener(self, listener) -> None:
        """Set the event listener for sub-step progress."""
        self._listener = listener

    def emit(self, message: str, detail: str = "") -> None:
        """Emit a sub-step event during provisioning."""
        if self._listener:
            from vystak.provisioning.listener import ProvisionEvent

            self._listener.on_step(
                ProvisionEvent(
                    node_name=self.name,
                    event_type="step",
                    message=message,
                    detail=detail,
                )
            )
