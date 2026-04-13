"""DockerNetworkNode — creates the shared Docker network."""

from agentstack.provisioning.health import HealthCheck, NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult

NETWORK_NAME = "agentstack-net"


class DockerNetworkNode(Provisionable):
    """Ensures the agentstack-net Docker network exists."""

    def __init__(self, client):
        self._client = client

    @property
    def name(self) -> str:
        return "network"

    @property
    def depends_on(self) -> list[str]:
        return []

    def provision(self, context: dict) -> ProvisionResult:
        existing = self._client.networks.list(names=[NETWORK_NAME])
        if existing:
            network = existing[0]
        else:
            network = self._client.networks.create(NETWORK_NAME, driver="bridge")

        return ProvisionResult(
            name=self.name,
            success=True,
            info={"network_name": network.name, "network": network},
        )

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        pass  # Networks persist across deployments
