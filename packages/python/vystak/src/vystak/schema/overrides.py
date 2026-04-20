"""EnvironmentOverride — per-environment configuration swap.

Applied to a list of agents loaded from vystak.py; typically used to swap
the transport on a named platform for a specific environment (dev/prod).

Future expansion: more fields (e.g., model overrides, channel overrides)
can be added to EnvironmentOverride without breaking the apply() contract.
"""

from __future__ import annotations

from copy import deepcopy

from pydantic import BaseModel, Field

from vystak.schema.agent import Agent
from vystak.schema.transport import Transport


class EnvironmentOverride(BaseModel):
    """Overlay applied to a list of agents at load time.

    Attributes:
        transports: Maps platform name -> replacement Transport. Every
            agent whose platform.name matches has its transport swapped
            for the override.
    """

    transports: dict[str, Transport] = Field(default_factory=dict)

    def apply(self, agents: list[Agent]) -> list[Agent]:
        """Return a new list of agents with overrides applied.

        The input `agents` list and its elements are not mutated.
        Raises ValueError if any override key references a platform name
        not present in the agents' platforms.
        """
        if not self.transports:
            return list(agents)

        known_platform_names = {
            a.platform.name for a in agents if a.platform is not None
        }
        unknown = set(self.transports) - known_platform_names
        if unknown:
            raise ValueError(
                f"EnvironmentOverride references unknown platform(s): "
                f"{sorted(unknown)}; known: {sorted(known_platform_names)}"
            )

        merged = deepcopy(agents)
        for agent in merged:
            if agent.platform is None:
                continue
            if agent.platform.name in self.transports:
                # Reconstruct Platform with the replacement transport to avoid
                # needing validate_assignment=True on NamedModel/Platform.
                from vystak.schema.platform import Platform

                platform_dump = agent.platform.model_dump()
                platform_dump["transport"] = self.transports[agent.platform.name].model_dump()
                agent.platform = Platform.model_validate(platform_dump)
        return merged
