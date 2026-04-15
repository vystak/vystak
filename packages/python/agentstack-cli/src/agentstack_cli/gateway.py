"""Gateway deployment — builds routes from deployed agents and deploys the gateway."""

import json
from pathlib import Path

import click

from agentstack.providers.base import DeployPlan, GeneratedCode


def build_routes(deployed: list[dict]) -> dict:
    """Build routes.json data from deployment results."""
    routes = []
    for d in deployed:
        url = _extract_url(d)
        if not url or url == "(unchanged)":
            # For unchanged agents, try to get URL from provider status
            agent = d["agent"]
            try:
                from agentstack_cli.provider_factory import get_provider
                provider = get_provider(agent)
                provider.set_agent(agent)
                status = provider.status(agent.name)
                info = status.info or {}
                url = info.get("url") or info.get("fqdn")
                if not url and "ports" in info:
                    ports = info["ports"]
                    if "8000/tcp" in ports and ports["8000/tcp"]:
                        port = ports["8000/tcp"][0].get("HostPort", "8000")
                        url = f"http://localhost:{port}"
            except Exception:
                continue

        if not url:
            continue

        routes.append({
            "provider_name": "api",
            "agent_name": d["name"],
            "agent_url": url,
            "channels": [],
            "listen": "all",
            "threads": True,
            "dm": True,
        })

    return {"providers": [], "routes": routes}


def deploy_gateway(deployed: list[dict], gateway_name: str = "main") -> str | None:
    """Deploy a gateway for the deployed agents. Returns the gateway URL."""
    routes_data = build_routes(deployed)
    if not routes_data["routes"]:
        return None

    # Determine platform from first agent
    first_agent = next((d["agent"] for d in deployed if d["agent"].platform), None)
    if not first_agent:
        return None

    provider_type = first_agent.platform.provider.type if first_agent.platform else "docker"

    if provider_type == "docker":
        return _deploy_gateway_docker(routes_data, gateway_name)
    elif provider_type == "azure":
        return _deploy_gateway_azure(routes_data, gateway_name, first_agent)
    else:
        click.echo(f"  Gateway not supported for provider: {provider_type}", err=True)
        return None


def _deploy_gateway_docker(routes_data: dict, gateway_name: str) -> str | None:
    """Deploy gateway as a Docker container."""
    from agentstack_provider_docker.gateway import (
        build_gateway_image,
        provision_gateway,
        write_gateway_source,
        write_routes_file,
    )
    from agentstack_provider_docker.nodes.network import DockerNetworkNode
    import docker as docker_lib

    try:
        client = docker_lib.from_env()
    except docker_lib.errors.DockerException:
        from pathlib import Path as P
        desktop_socket = P.home() / ".docker" / "run" / "docker.sock"
        if desktop_socket.exists():
            client = docker_lib.DockerClient(base_url=f"unix://{desktop_socket}")
        else:
            raise

    gateway_dir = Path(".agentstack") / f"gateway-{gateway_name}"
    write_gateway_source(gateway_dir)

    routes_path = gateway_dir / "routes.json"
    write_routes_file(routes_path, routes_data["providers"], routes_data["routes"])

    build_gateway_image(client, gateway_name, str(gateway_dir))

    # Ensure network exists
    from agentstack_provider_docker.network import ensure_network
    network = ensure_network(client)

    # For Docker, rewrite agent URLs to use container names on internal network
    for route in routes_data["routes"]:
        agent_name = route["agent_name"]
        route["agent_url"] = f"http://agentstack-{agent_name}:8000"

    # Rewrite routes with internal URLs
    write_routes_file(routes_path, routes_data["providers"], routes_data["routes"])

    provision_gateway(client, gateway_name, network, routes_path=str(routes_path), env={}, port=8080)
    return "http://localhost:8080"


def _deploy_gateway_azure(routes_data: dict, gateway_name: str, ref_agent) -> str | None:
    """Deploy gateway as an Azure Container App."""
    import os
    import subprocess

    from agentstack_provider_docker.gateway import write_gateway_source
    from agentstack_provider_azure.auth import get_credential, get_location, get_subscription_id

    config = {}
    if ref_agent.platform:
        config.update(ref_agent.platform.provider.config)
        config.update(ref_agent.platform.config)

    credential = get_credential()
    subscription_id = get_subscription_id(config)
    location = get_location(config)

    rg_name = config.get("resource_group", f"agentstack-gateway-rg")
    app_name = f"agentstack-gateway-{gateway_name}"

    # Get ACR info from existing registry in the RG
    from azure.mgmt.containerregistry import ContainerRegistryManagementClient
    acr_client = ContainerRegistryManagementClient(credential, subscription_id)
    registries = list(acr_client.registries.list_by_resource_group(rg_name))
    if not registries:
        click.echo("  No ACR found in resource group, cannot deploy gateway", err=True)
        return None

    registry = registries[0]
    login_server = registry.login_server
    creds = acr_client.registries.list_credentials(rg_name, registry.name)
    acr_username = creds.username
    acr_password = creds.passwords[0].value

    # Get ACA environment from existing environments in the RG
    from azure.mgmt.appcontainers import ContainerAppsAPIClient
    aca_client = ContainerAppsAPIClient(credential, subscription_id)
    environments = list(aca_client.managed_environments.list_by_resource_group(rg_name))
    if not environments:
        click.echo("  No ACA environment found, cannot deploy gateway", err=True)
        return None

    env_id = environments[0].id

    # Build gateway source
    gateway_dir = Path(".agentstack") / f"gateway-{gateway_name}"
    write_gateway_source(gateway_dir)

    # Write routes.json into the build context
    routes_path = gateway_dir / "routes.json"
    routes_path.write_text(json.dumps(routes_data, indent=2))

    # Add COPY routes.json to Dockerfile
    dockerfile = gateway_dir / "Dockerfile"
    content = dockerfile.read_text()
    # The gateway Dockerfile already has COPY . . which includes routes.json

    # Build and push image
    image_tag = f"{login_server}/{app_name}:latest"

    subprocess.run(
        ["docker", "login", login_server, "--username", acr_username, "--password-stdin"],
        input=acr_password, text=True, check=True, capture_output=True,
    )
    result = subprocess.run(
        ["docker", "buildx", "build", "--platform", "linux/amd64",
         "--tag", image_tag, "--push", str(gateway_dir)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        click.echo(f"  Gateway build failed: {result.stderr}", err=True)
        return None

    # Deploy as Container App
    from azure.mgmt.appcontainers.models import (
        Configuration, Container, ContainerApp, ContainerResources,
        Ingress, RegistryCredentials, Scale, Secret, Template,
    )

    aca_secrets = [Secret(name="acr-password", value=acr_password)]

    try:
        app = aca_client.container_apps.begin_create_or_update(
            rg_name,
            app_name,
            ContainerApp(
                location=location,
                tags={
                    "agentstack:managed": "true",
                    "agentstack:gateway": gateway_name,
                },
                managed_environment_id=env_id,
                configuration=Configuration(
                    ingress=Ingress(external=True, target_port=8080),
                    secrets=aca_secrets,
                    registries=[
                        RegistryCredentials(
                            server=login_server,
                            username=acr_username,
                            password_secret_ref="acr-password",
                        ),
                    ],
                ),
                template=Template(
                    containers=[
                        Container(
                            name=app_name,
                            image=image_tag,
                            resources=ContainerResources(cpu=0.25, memory="0.5Gi"),
                        ),
                    ],
                    scale=Scale(min_replicas=0, max_replicas=1),
                ),
            ),
        ).result()

        fqdn = app.configuration.ingress.fqdn
        return f"https://{fqdn}"

    except Exception as e:
        click.echo(f"  Gateway deploy failed: {e}", err=True)
        return None


def _extract_url(d: dict) -> str | None:
    """Extract URL from a deployed entry."""
    result = d.get("result")
    if result and hasattr(result, "message") and " at " in result.message:
        return result.message.split(" at ", 1)[1]
    url = d.get("url")
    return url if url and url != "(unchanged)" else None
