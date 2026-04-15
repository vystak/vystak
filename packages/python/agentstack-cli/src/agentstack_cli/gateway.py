"""Gateway deployment and agent registration."""

import json
import time
from pathlib import Path

import click
import httpx


def deploy_gateway(deployed: list[dict], gateway_name: str = "main") -> str | None:
    """Deploy a gateway for the deployed agents. Returns the gateway URL."""
    first_agent = next((d["agent"] for d in deployed if d["agent"].platform), None)
    if not first_agent:
        return None

    provider_type = first_agent.platform.provider.type if first_agent.platform else "docker"

    if provider_type == "docker":
        return _deploy_gateway_docker(gateway_name)
    elif provider_type == "azure":
        return _deploy_gateway_azure(gateway_name, first_agent)
    else:
        click.echo(f"  Gateway not supported for provider: {provider_type}", err=True)
        return None


def inject_gateway_env(gateway_url: str, deployed: list[dict]) -> None:
    """Inject AGENTSTACK_GATEWAY_URL env var into deployed agents."""
    for d in deployed:
        agent = d["agent"]
        if not agent.platform or agent.platform.provider.type != "azure":
            # Docker agents would need container restart — skip for now
            continue

        try:
            from agentstack_provider_azure.auth import get_credential, get_subscription_id
            config = {}
            config.update(agent.platform.provider.config)
            config.update(agent.platform.config)

            credential = get_credential()
            subscription_id = get_subscription_id(config)
            rg_name = config.get("resource_group", f"agentstack-{agent.name}-rg")

            from azure.mgmt.appcontainers import ContainerAppsAPIClient
            aca_client = ContainerAppsAPIClient(credential, subscription_id)

            # Get current app
            app = aca_client.container_apps.get(rg_name, agent.name)

            # Check if env var already set
            container = app.template.containers[0]
            existing_env = {e.name: e for e in (container.env or [])}
            if "AGENTSTACK_GATEWAY_URL" in existing_env:
                click.echo(f"  {agent.name}: already configured")
                continue

            # Add gateway URL env var
            from azure.mgmt.appcontainers.models import EnvironmentVar
            new_env = list(container.env or [])
            new_env.append(EnvironmentVar(name="AGENTSTACK_GATEWAY_URL", value=gateway_url))
            container.env = new_env

            # Update the app
            aca_client.container_apps.begin_create_or_update(
                rg_name, agent.name, app,
            ).result()
            click.echo(f"  {agent.name}: updated")

        except Exception as e:
            click.echo(f"  {agent.name}: failed ({e})")


def register_agents(gateway_url: str, deployed: list[dict]) -> None:
    """Register all deployed agents with the gateway via POST /register."""
    # Wait for gateway to be healthy
    for attempt in range(15):
        try:
            resp = httpx.get(f"{gateway_url}/health", timeout=5)
            if resp.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(2)

    for d in deployed:
        agent_name = d["name"]
        url = _resolve_agent_url(d)
        if not url:
            click.echo(f"  {agent_name}: skipped (no URL)")
            continue

        try:
            resp = httpx.post(
                f"{gateway_url}/register",
                json={"name": agent_name, "url": url},
                timeout=10,
            )
            if resp.status_code == 200:
                click.echo(f"  {agent_name}: registered ({url})")
            else:
                click.echo(f"  {agent_name}: failed ({resp.status_code})")
        except Exception as e:
            click.echo(f"  {agent_name}: failed ({e})")


def _resolve_agent_url(d: dict) -> str | None:
    """Get the agent URL reachable by the gateway (internal network URL)."""
    agent = d["agent"]
    provider_type = "docker"
    if agent.platform and agent.platform.provider:
        provider_type = agent.platform.provider.type

    if provider_type == "docker":
        # Docker: gateway reaches agents via container name on shared network
        return f"http://agentstack-{agent.name}:8000"

    # Azure/other: use the external URL from deploy result
    result = d.get("result")
    if result and hasattr(result, "message") and " at " in result.message:
        return result.message.split(" at ", 1)[1]

    url = d.get("url")
    if url and url != "(unchanged)":
        return url

    # Query provider status for URL
    try:
        from agentstack_cli.provider_factory import get_provider
        provider = get_provider(agent)
        provider.set_agent(agent)
        status = provider.status(agent.name)
        info = status.info or {}

        if info.get("url"):
            return info["url"]
        if info.get("fqdn"):
            return f"https://{info['fqdn']}"
    except Exception:
        pass

    return None


def _deploy_gateway_docker(gateway_name: str) -> str | None:
    """Deploy gateway as a Docker container."""
    import docker as docker_lib
    from agentstack_provider_docker.gateway import (
        build_gateway_image,
        provision_gateway,
        write_gateway_source,
        write_routes_file,
    )
    from agentstack_provider_docker.network import ensure_network

    try:
        client = docker_lib.from_env()
    except docker_lib.errors.DockerException:
        desktop_socket = Path.home() / ".docker" / "run" / "docker.sock"
        if desktop_socket.exists():
            client = docker_lib.DockerClient(base_url=f"unix://{desktop_socket}")
        else:
            raise

    gateway_dir = Path(".agentstack") / f"gateway-{gateway_name}"
    write_gateway_source(gateway_dir)

    # Empty routes — agents will be registered by CLI after deploy
    routes_path = gateway_dir / "routes.json"
    write_routes_file(routes_path, [], [])

    build_gateway_image(client, gateway_name, str(gateway_dir))
    network = ensure_network(client)
    provision_gateway(client, gateway_name, network, routes_path=str(routes_path), env={}, port=8080)

    return "http://localhost:8080"


def _deploy_gateway_azure(gateway_name: str, ref_agent) -> str | None:
    """Deploy gateway as an Azure Container App."""
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
    rg_name = config.get("resource_group", "agentstack-gateway-rg")
    app_name = f"agentstack-gateway-{gateway_name}"

    # Get ACR from existing resources
    from azure.mgmt.containerregistry import ContainerRegistryManagementClient
    acr_client = ContainerRegistryManagementClient(credential, subscription_id)
    registries = list(acr_client.registries.list_by_resource_group(rg_name))
    if not registries:
        click.echo("  No ACR found, cannot deploy gateway", err=True)
        return None

    registry = registries[0]
    login_server = registry.login_server
    creds = acr_client.registries.list_credentials(rg_name, registry.name)
    acr_username = creds.username
    acr_password = creds.passwords[0].value

    # Get ACA environment
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

    # Empty routes.json — agents registered by CLI
    (gateway_dir / "routes.json").write_text(json.dumps({"providers": [], "routes": []}))

    # Build and push
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
        click.echo(f"  Build failed: {result.stderr}", err=True)
        return None

    # Deploy
    from azure.mgmt.appcontainers.models import (
        Configuration, Container, ContainerApp, ContainerResources,
        Ingress, RegistryCredentials, Scale, Secret, Template,
    )

    try:
        app = aca_client.container_apps.begin_create_or_update(
            rg_name, app_name,
            ContainerApp(
                location=location,
                tags={"agentstack:managed": "true", "agentstack:gateway": gateway_name},
                managed_environment_id=env_id,
                configuration=Configuration(
                    ingress=Ingress(external=True, target_port=8080),
                    secrets=[Secret(name="acr-password", value=acr_password)],
                    registries=[RegistryCredentials(
                        server=login_server, username=acr_username,
                        password_secret_ref="acr-password",
                    )],
                ),
                template=Template(
                    containers=[Container(
                        name=app_name, image=image_tag,
                        resources=ContainerResources(cpu=0.25, memory="0.5Gi"),
                    )],
                    scale=Scale(min_replicas=1, max_replicas=1),
                ),
            ),
        ).result()

        fqdn = app.configuration.ingress.fqdn
        return f"https://{fqdn}"
    except Exception as e:
        click.echo(f"  Deploy failed: {e}", err=True)
        return None
