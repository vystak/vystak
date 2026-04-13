"""DockerGatewayNode — provisions a gateway container."""

from agentstack.provisioning.health import HealthCheck, NoopHealthCheck
from agentstack.provisioning.node import Provisionable, ProvisionResult
from agentstack_provider_docker.gateway import (
    build_gateway_image,
    destroy_gateway,
    provision_gateway,
    write_gateway_source,
    write_routes_file,
)


class DockerGatewayNode(Provisionable):
    """Provisions a gateway container for agent channel routing."""

    def __init__(self, client, gw_name: str, gw_info: dict, agent_name: str):
        self._client = client
        self._gw_name = gw_name
        self._gw_info = gw_info
        self._agent_name = agent_name

    @property
    def name(self) -> str:
        return f"gateway:{self._gw_name}"

    @property
    def depends_on(self) -> list[str]:
        return [f"agent:{self._agent_name}"]

    def provision(self, context: dict) -> ProvisionResult:
        try:
            from pathlib import Path

            network = context["network"].info["network"]
            gateway = self._gw_info.get("gateway")
            gateway_dir = Path(".agentstack") / f"gateway-{self._gw_name}"

            write_gateway_source(gateway_dir)

            routes_path = gateway_dir / "routes.json"
            write_routes_file(
                routes_path,
                list(self._gw_info.get("providers", {}).values()),
                self._gw_info.get("routes", []),
            )

            build_gateway_image(self._client, self._gw_name, str(gateway_dir))

            env = {}
            for prov in self._gw_info.get("providers", {}).values():
                for key, value in prov.get("config", {}).items():
                    if isinstance(value, str) and value:
                        env_key = f"{prov['name'].upper().replace('-', '_')}_{key.upper()}"
                        env[env_key] = value

            port = gateway.config.get("port", 8080) if gateway else 8080
            provision_gateway(
                self._client,
                self._gw_name,
                network,
                routes_path=str(routes_path),
                env=env,
                port=port,
            )

            return ProvisionResult(
                name=self.name,
                success=True,
                info={"gateway_name": self._gw_name, "port": port},
            )
        except Exception as e:
            return ProvisionResult(
                name=self.name,
                success=False,
                error=str(e),
            )

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        destroy_gateway(self._client, self._gw_name)
