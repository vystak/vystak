"""Routing table — maps channel events to agent endpoints."""

from dataclasses import dataclass, field


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


class Router:
    """Routes incoming channel events to the correct agent."""

    def __init__(self):
        self._routes: list[Route] = []

    def add_route(self, route: Route) -> None:
        self._routes.append(route)

    def remove_routes(self, agent_name: str) -> None:
        self._routes = [r for r in self._routes if r.agent_name != agent_name]

    def resolve(self, provider_name: str, channel: str | None, is_dm: bool) -> Route | None:
        for route in self._routes:
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
        return list(self._routes)
