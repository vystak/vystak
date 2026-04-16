"""Docker network management for Vystak."""

import docker

NETWORK_NAME = "vystak-net"


def ensure_network(client, name: str = NETWORK_NAME):
    """Create the Vystak Docker network if it doesn't exist."""
    existing = client.networks.list(names=[name])
    if existing:
        return existing[0]
    return client.networks.create(name, driver="bridge")
