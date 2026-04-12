"""Docker network management for AgentStack."""

import docker

NETWORK_NAME = "agentstack-net"


def ensure_network(client, name: str = NETWORK_NAME):
    """Create the AgentStack Docker network if it doesn't exist."""
    existing = client.networks.list(names=[name])
    if existing:
        return existing[0]
    return client.networks.create(name, driver="bridge")
