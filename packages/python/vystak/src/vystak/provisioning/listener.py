"""Provision event listener — callbacks for graph execution progress."""

from dataclasses import dataclass


@dataclass
class ProvisionEvent:
    """An event emitted during provisioning."""

    node_name: str
    event_type: str  # "start", "step", "complete", "error", "health_check"
    message: str = ""
    detail: str = ""


class ProvisionListener:
    """Base listener for provision graph events. Override methods to handle events."""

    def on_start(self, event: ProvisionEvent) -> None:
        """Called before a node starts provisioning."""

    def on_step(self, event: ProvisionEvent) -> None:
        """Called during provisioning for sub-step progress (build, push, etc.)."""

    def on_complete(self, event: ProvisionEvent) -> None:
        """Called after a node finishes provisioning successfully."""

    def on_error(self, event: ProvisionEvent) -> None:
        """Called when a node fails to provision."""

    def on_health_check(self, event: ProvisionEvent) -> None:
        """Called when waiting for a health check."""


class PrintListener(ProvisionListener):
    """Prints provision events to stdout with indentation."""

    def __init__(self, indent: str = "    "):
        self._indent = indent

    def on_start(self, event: ProvisionEvent) -> None:
        print(f"{self._indent}{event.message}... ", end="", flush=True)

    def on_step(self, event: ProvisionEvent) -> None:
        if event.detail:
            print(f"\n{self._indent}{event.message}: {event.detail}... ", end="", flush=True)
        else:
            print(f"\n{self._indent}{event.message}... ", end="", flush=True)

    def on_complete(self, event: ProvisionEvent) -> None:
        if event.detail:
            print(f"OK ({event.detail})")
        else:
            print("OK")

    def on_error(self, event: ProvisionEvent) -> None:
        print("FAILED")
        if event.detail:
            print(f"{self._indent}  Error: {event.detail}")

    def on_health_check(self, event: ProvisionEvent) -> None:
        pass  # silent by default


class NullListener(ProvisionListener):
    """Does nothing. Used when no listener is provided."""

    pass
