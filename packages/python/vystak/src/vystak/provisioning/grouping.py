"""Group agents by platform fingerprint for shared infrastructure."""

import hashlib
import json

from vystak.schema.agent import Agent


def platform_fingerprint(agent: Agent) -> str:
    if agent.platform is None:
        return "docker:default"
    key = {
        "provider_type": agent.platform.provider.type,
        "provider_config": agent.platform.provider.config,
        "platform_type": agent.platform.type,
    }
    canonical = json.dumps(key, sort_keys=True, default=str)
    return hashlib.md5(canonical.encode()).hexdigest()


def group_agents_by_platform(agents: list[Agent]) -> dict[str, list[Agent]]:
    groups: dict[str, list[Agent]] = {}
    for agent in agents:
        fp = platform_fingerprint(agent)
        groups.setdefault(fp, []).append(agent)
    return groups
