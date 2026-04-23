"""Dependency graph for provisioning resources."""

from dataclasses import dataclass, field

from vystak.provisioning.listener import NullListener, ProvisionEvent, ProvisionListener
from vystak.provisioning.node import Provisionable, ProvisionResult


class CycleError(Exception):
    pass


class ProvisionError(Exception):
    pass


@dataclass
class ProvisionGraph:
    _nodes: dict[str, Provisionable] = field(default_factory=dict)
    _implicit_deps: dict[str, list[str]] = field(default_factory=dict)
    _listener: ProvisionListener = field(default_factory=NullListener)

    def set_listener(self, listener: ProvisionListener) -> None:
        """Set the event listener for provision progress."""
        self._listener = listener

    def add(self, node: Provisionable) -> None:
        self._nodes[node.name] = node

    def nodes(self) -> list[Provisionable]:
        """Return a list of all nodes in the graph (no ordering guarantees)."""
        return list(self._nodes.values())

    def add_dependency(self, name: str, depends_on: str) -> None:
        self._implicit_deps.setdefault(name, []).append(depends_on)

    def _all_deps(self, name: str) -> list[str]:
        node = self._nodes[name]
        all_deps = list(node.depends_on)
        all_deps.extend(self._implicit_deps.get(name, []))
        return [d for d in all_deps if d in self._nodes]

    def _resolve_order(self) -> list[str]:
        reverse: dict[str, list[str]] = {name: [] for name in self._nodes}
        in_degree: dict[str, int] = {name: 0 for name in self._nodes}

        for name in self._nodes:
            deps = self._all_deps(name)
            in_degree[name] = len(deps)
            for dep in deps:
                reverse[dep].append(name)

        queue = [n for n, d in in_degree.items() if d == 0]
        order: list[str] = []

        while queue:
            node = queue.pop(0)
            order.append(node)
            for dependent in reverse[node]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(order) != len(self._nodes):
            raise CycleError("Dependency cycle detected in provision graph")

        return order

    def execute(self) -> dict[str, ProvisionResult]:
        order = self._resolve_order()
        results: dict[str, ProvisionResult] = {}

        for name in order:
            node = self._nodes[name]

            self._listener.on_start(
                ProvisionEvent(
                    node_name=name,
                    event_type="start",
                    message=name,
                )
            )

            # Pass listener to node if it supports it
            if hasattr(node, "set_listener"):
                node.set_listener(self._listener)

            result = node.provision(context=results)
            results[name] = result

            if not result.success:
                self._listener.on_error(
                    ProvisionEvent(
                        node_name=name,
                        event_type="error",
                        message=name,
                        detail=result.error or "",
                    )
                )
                raise ProvisionError(f"Failed to provision {name}: {result.error}")

            self._listener.on_complete(
                ProvisionEvent(
                    node_name=name,
                    event_type="complete",
                    message=name,
                    detail=result.info.get("detail", ""),
                )
            )

            check = node.health_check()
            self._listener.on_health_check(
                ProvisionEvent(
                    node_name=name,
                    event_type="health_check",
                    message=f"Waiting for {name}",
                )
            )
            check.wait()

        return results

    def destroy_all(self) -> None:
        order = self._resolve_order()
        for name in reversed(order):
            self._nodes[name].destroy()
