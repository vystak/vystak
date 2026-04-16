"""Gateway container provisioning for Docker."""

import json
from pathlib import Path

import docker
import docker.errors

GATEWAY_DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "server.py"]
"""

GATEWAY_REQUIREMENTS = """\
fastapi>=0.115
uvicorn>=0.34
httpx>=0.28
slack-bolt>=1.21
aiohttp>=3.9
aiosqlite>=0.20
"""


def _gateway_container_name(gateway_name: str) -> str:
    return f"vystak-gateway-{gateway_name}"


def write_gateway_source(gateway_dir: Path) -> None:
    """Write gateway server source files to a build directory."""
    gateway_dir.mkdir(parents=True, exist_ok=True)

    import vystak_gateway

    pkg_dir = Path(vystak_gateway.__file__).parent

    for filename in ["server.py", "router.py", "store.py", "__init__.py"]:
        src = pkg_dir / filename
        if src.exists():
            content = src.read_text()
            # Rewrite package imports to local imports for Docker deployment
            content = content.replace("from vystak_gateway.", "from ")
            content = content.replace(
                "from vystak.schema.openai import", "from openai_types import"
            )
            (gateway_dir / filename).write_text(content)

    # Bundle OpenAI-compatible schema types
    import vystak.schema.openai as _openai_schema

    _openai_src = Path(_openai_schema.__file__)
    if _openai_src.exists():
        (gateway_dir / "openai_types.py").write_text(_openai_src.read_text())

    providers_dir = gateway_dir / "providers"
    providers_dir.mkdir(parents=True, exist_ok=True)
    providers_src = pkg_dir / "providers"
    for filename in ["__init__.py", "base.py", "slack.py"]:
        src = providers_src / filename
        if src.exists():
            content = src.read_text()
            content = content.replace("from vystak_gateway.", "from ")
            (providers_dir / filename).write_text(content)

    (gateway_dir / "requirements.txt").write_text(GATEWAY_REQUIREMENTS)
    (gateway_dir / "Dockerfile").write_text(GATEWAY_DOCKERFILE)


def write_routes_file(routes_path: Path, providers_list: list, routes_list: list) -> None:
    """Write routes.json for the gateway."""
    routes_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"providers": providers_list, "routes": routes_list}
    routes_path.write_text(json.dumps(data, indent=2))


def build_gateway_image(client, gateway_name: str, gateway_dir: str) -> None:
    """Build a Docker image for the gateway."""
    image_tag = f"{_gateway_container_name(gateway_name)}:latest"
    client.images.build(path=gateway_dir, tag=image_tag)


def provision_gateway(
    client, gateway_name: str, network, routes_path: str, env: dict, port: int = 8080
) -> None:
    """Start or restart a gateway container."""
    container_name = _gateway_container_name(gateway_name)

    try:
        existing = client.containers.get(container_name)
        existing.stop()
        existing.remove()
    except docker.errors.NotFound:
        pass

    image_tag = f"{container_name}:latest"
    abs_routes = str(Path(routes_path).resolve())

    client.containers.run(
        image_tag,
        name=container_name,
        detach=True,
        ports={"8080/tcp": port},
        environment=env,
        volumes={abs_routes: {"bind": "/app/routes.json", "mode": "ro"}},
        network=network.name,
        labels={"vystak.gateway": gateway_name},
    )


def destroy_gateway(client, gateway_name: str) -> None:
    """Stop and remove a gateway container."""
    container_name = _gateway_container_name(gateway_name)
    try:
        container = client.containers.get(container_name)
        container.stop()
        container.remove()
    except docker.errors.NotFound:
        pass
