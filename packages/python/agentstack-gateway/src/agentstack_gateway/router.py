"""Routing table — maps channel events to agent endpoints with health tracking."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Route:
    """A mapping from a channel provider + channel to an agent."""

    provider_name: str
    agent_name: str
    agent_url: str
    channels: list[str] = field(default_factory=list)
    listen: str = "mentions"
    threads: bool = True
    dm: bool = True
    status: str = "online"
    registered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_seen: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    error_count: int = 0


class Router:
    """Routes incoming channel events to the correct agent."""

    def __init__(self):
        self._routes: dict[str, Route] = {}

    def add_route(self, route: Route) -> None:
        self._routes[route.agent_name] = route

    def remove_routes(self, agent_name: str) -> None:
        self._routes.pop(agent_name, None)

    def get_route(self, agent_name: str) -> Route | None:
        return self._routes.get(agent_name)

    def mark_online(self, agent_name: str) -> None:
        route = self._routes.get(agent_name)
        if route:
            route.status = "online"
            route.last_seen = datetime.now(UTC).isoformat()
            route.error_count = 0

    def mark_offline(self, agent_name: str, error: str = "") -> None:
        route = self._routes.get(agent_name)
        if route:
            route.error_count += 1
            if route.error_count >= 3:
                route.status = "offline"

    def resolve(self, provider_name: str, channel: str | None, is_dm: bool) -> Route | None:
        for route in self._routes.values():
            if route.provider_name != provider_name:
                continue
            if is_dm:
                if route.dm:
                    return route
                continue
            if channel in route.channels:
                return route
        return None

    def list_routes(self) -> list[Route]:
        return list(self._routes.values())
