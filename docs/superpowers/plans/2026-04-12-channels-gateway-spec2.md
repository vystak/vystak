# Channels & Gateway (Spec 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire gateway containers into the deployment pipeline — Docker provider provisions gateways, CLI generates routes.json, and the gateway server loads routes on startup.

**Architecture:** New `gateway.py` module in the Docker provider handles gateway image building and container lifecycle. CLI `apply` scans agent channels for SlackChannel instances, generates routes.json, and provisions the gateway. Gateway server loads routes.json on startup via a FastAPI lifespan handler.

**Tech Stack:** Python 3.11+, docker SDK, FastAPI, pytest, unittest.mock

---

### Task 1: Gateway Provisioning Module

**Files:**
- Create: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/gateway.py`
- Create: `packages/python/agentstack-provider-docker/tests/test_gateway_provision.py`

- [ ] **Step 1: Write tests**

`packages/python/agentstack-provider-docker/tests/test_gateway_provision.py`:
```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentstack_provider_docker.gateway import (
    build_gateway_image,
    destroy_gateway,
    provision_gateway,
    write_gateway_source,
    write_routes_file,
)


class TestWriteGatewaySource:
    def test_writes_files(self, tmp_path):
        gateway_dir = tmp_path / "gateway"
        write_gateway_source(gateway_dir)
        assert (gateway_dir / "server.py").exists()
        assert (gateway_dir / "router.py").exists()
        assert (gateway_dir / "providers" / "slack.py").exists()
        assert (gateway_dir / "providers" / "base.py").exists()
        assert (gateway_dir / "requirements.txt").exists()
        assert (gateway_dir / "Dockerfile").exists()

    def test_server_py_content(self, tmp_path):
        gateway_dir = tmp_path / "gateway"
        write_gateway_source(gateway_dir)
        content = (gateway_dir / "server.py").read_text()
        assert "FastAPI" in content
        assert "load_routes_file" in content or "routes.json" in content


class TestWriteRoutesFile:
    def test_writes_valid_json(self, tmp_path):
        routes_path = tmp_path / "routes.json"
        providers_list = [
            {"name": "internal-slack", "type": "slack", "config": {"bot_token": "xoxb-test", "app_token": "xapp-test"}},
        ]
        routes_list = [
            {
                "provider_name": "internal-slack",
                "agent_name": "support-bot",
                "agent_url": "http://agentstack-support-bot:8000",
                "channels": ["#support"],
                "listen": "mentions",
                "threads": True,
                "dm": True,
            },
        ]
        write_routes_file(routes_path, providers_list, routes_list)
        data = json.loads(routes_path.read_text())
        assert len(data["providers"]) == 1
        assert len(data["routes"]) == 1
        assert data["routes"][0]["agent_name"] == "support-bot"

    def test_overwrites_existing(self, tmp_path):
        routes_path = tmp_path / "routes.json"
        routes_path.write_text("{}")
        write_routes_file(routes_path, [], [{"agent_name": "bot"}])
        data = json.loads(routes_path.read_text())
        assert len(data["routes"]) == 1


class TestBuildGatewayImage:
    @patch("agentstack_provider_docker.gateway.docker")
    def test_builds_image(self, mock_docker):
        client = MagicMock()
        mock_docker.from_env.return_value = client
        client.images.build.return_value = (MagicMock(), [])

        build_gateway_image(client, "main-gateway", "/tmp/gateway")
        client.images.build.assert_called_once()
        call_kwargs = client.images.build.call_args
        assert "agentstack-gateway-main-gateway" in str(call_kwargs)


class TestProvisionGateway:
    @patch("agentstack_provider_docker.gateway.docker")
    def test_starts_new(self, mock_docker):
        client = MagicMock()
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        client.containers.get.side_effect = mock_docker.errors.NotFound("not found")
        network = MagicMock()
        network.name = "agentstack-net"

        provision_gateway(
            client, "main-gateway", network,
            routes_path="/tmp/routes.json",
            env={"SLACK_TOKEN": "test"},
            port=8080,
        )
        client.containers.run.assert_called_once()

    @patch("agentstack_provider_docker.gateway.docker")
    def test_restarts_existing(self, mock_docker):
        client = MagicMock()
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        existing = MagicMock()
        client.containers.get.return_value = existing
        network = MagicMock()
        network.name = "agentstack-net"

        provision_gateway(
            client, "main-gateway", network,
            routes_path="/tmp/routes.json",
            env={},
            port=8080,
        )
        existing.stop.assert_called_once()
        existing.remove.assert_called_once()
        client.containers.run.assert_called_once()


class TestDestroyGateway:
    @patch("agentstack_provider_docker.gateway.docker")
    def test_removes(self, mock_docker):
        client = MagicMock()
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        container = MagicMock()
        client.containers.get.return_value = container

        destroy_gateway(client, "main-gateway")
        container.stop.assert_called_once()
        container.remove.assert_called_once()

    @patch("agentstack_provider_docker.gateway.docker")
    def test_not_found(self, mock_docker):
        client = MagicMock()
        mock_docker.errors.NotFound = type("NotFound", (Exception,), {})
        client.containers.get.side_effect = mock_docker.errors.NotFound("not found")
        destroy_gateway(client, "main-gateway")  # should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Developer/work/AgentsStack && uv run pytest packages/python/agentstack-provider-docker/tests/test_gateway_provision.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement gateway.py**

`packages/python/agentstack-provider-docker/src/agentstack_provider_docker/gateway.py`:
```python
"""Gateway container provisioning for Docker."""

import importlib.resources
import json
import shutil
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
"""


def _gateway_container_name(gateway_name: str) -> str:
    return f"agentstack-gateway-{gateway_name}"


def write_gateway_source(gateway_dir: Path) -> None:
    """Write gateway server source files to a build directory."""
    gateway_dir.mkdir(parents=True, exist_ok=True)

    # Copy source files from the agentstack_gateway package
    import agentstack_gateway
    import agentstack_gateway.providers
    import agentstack_gateway.providers.slack
    import agentstack_gateway.providers.base

    pkg_dir = Path(agentstack_gateway.__file__).parent

    # Copy main modules
    for filename in ["server.py", "router.py", "__init__.py"]:
        src = pkg_dir / filename
        if src.exists():
            shutil.copy2(src, gateway_dir / filename)

    # Copy providers
    providers_dir = gateway_dir / "providers"
    providers_dir.mkdir(parents=True, exist_ok=True)
    providers_src = pkg_dir / "providers"
    for filename in ["__init__.py", "base.py", "slack.py"]:
        src = providers_src / filename
        if src.exists():
            shutil.copy2(src, providers_dir / filename)

    # Write requirements and Dockerfile
    (gateway_dir / "requirements.txt").write_text(GATEWAY_REQUIREMENTS)
    (gateway_dir / "Dockerfile").write_text(GATEWAY_DOCKERFILE)


def write_routes_file(routes_path: Path, providers_list: list, routes_list: list) -> None:
    """Write routes.json for the gateway."""
    routes_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "providers": providers_list,
        "routes": routes_list,
    }
    routes_path.write_text(json.dumps(data, indent=2))


def build_gateway_image(client, gateway_name: str, gateway_dir: str) -> None:
    """Build a Docker image for the gateway."""
    image_tag = f"{_gateway_container_name(gateway_name)}:latest"
    client.images.build(path=gateway_dir, tag=image_tag)


def provision_gateway(
    client,
    gateway_name: str,
    network,
    routes_path: str,
    env: dict,
    port: int = 8080,
) -> None:
    """Start or restart a gateway container."""
    container_name = _gateway_container_name(gateway_name)

    # Stop existing if present
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
        labels={
            "agentstack.gateway": gateway_name,
        },
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/test_gateway_provision.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-provider-docker/
git commit -m "feat: add gateway container provisioning module"
```

---

### Task 2: Gateway Server — Load Routes on Startup

**Files:**
- Modify: `packages/python/agentstack-gateway/src/agentstack_gateway/server.py`
- Modify: `packages/python/agentstack-gateway/tests/test_server.py`

- [ ] **Step 1: Add new tests to test_server.py**

Append to `packages/python/agentstack-gateway/tests/test_server.py`:

```python
import json


class TestLoadRoutesFile:
    def test_loads_providers_and_routes(self, tmp_path):
        from agentstack_gateway.server import load_routes_file, router, providers

        routes_file = tmp_path / "routes.json"
        routes_file.write_text(json.dumps({
            "providers": [],
            "routes": [
                {
                    "provider_name": "test-slack",
                    "agent_name": "support-bot",
                    "agent_url": "http://agent:8000",
                    "channels": ["#support"],
                    "listen": "mentions",
                    "threads": True,
                    "dm": True,
                }
            ],
        }))

        load_routes_file(str(routes_file))
        routes = router.list_routes()
        assert len(routes) == 1
        assert routes[0].agent_name == "support-bot"

    def test_missing_file_no_error(self):
        from agentstack_gateway.server import load_routes_file
        load_routes_file("/nonexistent/routes.json")  # should not raise
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest packages/python/agentstack-gateway/tests/test_server.py::TestLoadRoutesFile -v`

Expected: FAIL.

- [ ] **Step 3: Update server.py with load_routes_file and lifespan**

Update `packages/python/agentstack-gateway/src/agentstack_gateway/server.py` — add `load_routes_file` function and a lifespan handler:

Add these imports at the top:
```python
import json
from contextlib import asynccontextmanager
from pathlib import Path
```

Add the `load_routes_file` function:
```python
ROUTES_FILE = os.environ.get("ROUTES_FILE", "/app/routes.json")


def load_routes_file(path: str | None = None) -> None:
    """Load providers and routes from a JSON config file."""
    path = path or ROUTES_FILE
    routes_path = Path(path)
    if not routes_path.exists():
        return

    data = json.loads(routes_path.read_text())

    for route_data in data.get("routes", []):
        route = Route(
            provider_name=route_data["provider_name"],
            agent_name=route_data["agent_name"],
            agent_url=route_data["agent_url"],
            channels=route_data.get("channels", []),
            listen=route_data.get("listen", "mentions"),
            threads=route_data.get("threads", True),
            dm=route_data.get("dm", True),
        )
        router.add_route(route)

    for provider_data in data.get("providers", []):
        name = provider_data["name"]
        ptype = provider_data["type"]
        config = provider_data.get("config", {})

        if name not in providers and ptype == "slack":
            from agentstack_gateway.providers.slack import SlackProviderRunner
            runner = SlackProviderRunner(name=name, config=config, event_router=router)
            providers[name] = runner
```

Add the lifespan handler and update the app creation:
```python
@asynccontextmanager
async def lifespan(app_instance):
    load_routes_file()
    for runner in providers.values():
        asyncio.create_task(runner.start())
    yield
    for runner in providers.values():
        try:
            await runner.stop()
        except Exception:
            pass


app = FastAPI(title="agentstack-gateway", lifespan=lifespan)
```

Remove the old `app = FastAPI(title="agentstack-gateway")` line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-gateway/tests/test_server.py -v`

Expected: all tests PASS (old + new).

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-gateway/
git commit -m "feat: load routes.json on gateway startup via lifespan"
```

---

### Task 3: Docker Provider — Gateway Integration

**Files:**
- Modify: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py`
- Modify: `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/__init__.py`

- [ ] **Step 1: Add gateway methods to DockerProvider**

Update `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/provider.py`:

Add import at top:
```python
from agentstack.schema.channel import SlackChannel
from agentstack_provider_docker.gateway import (
    build_gateway_image,
    destroy_gateway,
    provision_gateway,
    write_gateway_source,
    write_routes_file,
)
```

Add these methods to `DockerProvider`:

```python
    def _collect_gateway_info(self) -> dict:
        """Extract gateway/provider/route info from agent channels."""
        if not self._agent:
            return {}

        gateways = {}  # gateway_name -> {gateway, providers, routes}

        for channel in self._agent.channels:
            if not isinstance(channel, SlackChannel):
                continue

            cp = channel.provider
            gw = cp.gateway
            gw_name = gw.name

            if gw_name not in gateways:
                gateways[gw_name] = {
                    "gateway": gw,
                    "providers": {},
                    "routes": [],
                }

            gw_info = gateways[gw_name]

            # Add channel provider if not already there
            if cp.name not in gw_info["providers"]:
                config = dict(cp.config)
                # Resolve secrets to env values
                resolved_config = {}
                for key, value in config.items():
                    if hasattr(value, "name"):  # Secret object
                        resolved_config[key] = os.environ.get(value.name, "")
                    else:
                        resolved_config[key] = value
                gw_info["providers"][cp.name] = {
                    "name": cp.name,
                    "type": cp.type,
                    "config": resolved_config,
                }

            # Add route
            agent_url = f"http://{self._container_name(self._agent.name)}:8000"
            gw_info["routes"].append({
                "provider_name": cp.name,
                "agent_name": self._agent.name,
                "agent_url": agent_url,
                "channels": channel.channels,
                "listen": channel.listen,
                "threads": channel.threads,
                "dm": channel.dm,
            })

        return gateways

    def provision_gateways(self, network) -> None:
        """Provision gateway containers for the agent's channels."""
        gateways = self._collect_gateway_info()

        for gw_name, gw_info in gateways.items():
            gateway = gw_info["gateway"]
            gateway_dir = Path(".agentstack") / f"gateway-{gw_name}"

            # Write gateway source
            write_gateway_source(gateway_dir)

            # Write routes file
            routes_path = gateway_dir / "routes.json"
            write_routes_file(
                routes_path,
                list(gw_info["providers"].values()),
                gw_info["routes"],
            )

            # Build image
            build_gateway_image(self._client, gw_name, str(gateway_dir))

            # Collect env vars from provider configs (bot tokens etc.)
            env = {}
            for prov in gw_info["providers"].values():
                for key, value in prov["config"].items():
                    if isinstance(value, str) and value:
                        env_key = f"{prov['name'].upper().replace('-', '_')}_{key.upper()}"
                        env[env_key] = value

            # Provision container
            port = gateway.config.get("port", 8080)
            provision_gateway(
                self._client, gw_name, network,
                routes_path=str(routes_path),
                env=env,
                port=port,
            )

    def destroy_gateways(self) -> None:
        """Destroy gateway containers for the agent's channels."""
        gateways = self._collect_gateway_info()
        for gw_name in gateways:
            destroy_gateway(self._client, gw_name)
```

Update `apply()` — add gateway provisioning after resources, before agent deploy. Add this between the resource provisioning block and the "Stop existing agent container" block:

```python
            # 2.5. Provision gateways
            self.provision_gateways(network)
```

Update `destroy()` — add gateway cleanup:

```python
    def destroy(self, agent_name: str, include_resources: bool = False) -> None:
        container = self._get_container(agent_name)
        if container is not None:
            container.stop()
            container.remove()

        if include_resources and self._agent:
            for resource in self._agent.resources:
                destroy_resource(self._client, resource.name)
            self.destroy_gateways()
```

- [ ] **Step 2: Update __init__.py**

Verify `packages/python/agentstack-provider-docker/src/agentstack_provider_docker/__init__.py` still exports `DockerProvider`. No changes needed if it already does.

- [ ] **Step 3: Run all provider tests**

Run: `uv run pytest packages/python/agentstack-provider-docker/tests/ -v`

Expected: all tests PASS. The existing provider tests mock `ensure_network` and won't hit the new gateway code.

- [ ] **Step 4: Commit**

```bash
git add packages/python/agentstack-provider-docker/
git commit -m "feat: integrate gateway provisioning into DockerProvider"
```

---

### Task 4: CLI Apply — Gateway Support

**Files:**
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/apply.py`

- [ ] **Step 1: Update apply.py**

The apply command already calls `provider.set_agent(agent)` and `provider.apply(deploy_plan)`. The `apply()` method now automatically provisions gateways (added in Task 3). We just need to add a status message.

Update `packages/python/agentstack-cli/src/agentstack_cli/commands/apply.py` — add gateway status output after the deploy success message:

```python
    if result.success:
        click.echo("OK")
        click.echo()
        click.echo(f"Deployed: {agent.name}")
        click.echo(f"  {result.message}")

        # Show gateway info if channels reference gateways
        from agentstack.schema.channel import SlackChannel
        slack_channels = [ch for ch in agent.channels if isinstance(ch, SlackChannel)]
        if slack_channels:
            gateways = set()
            for ch in slack_channels:
                gateways.add(ch.provider.gateway.name)
            for gw_name in gateways:
                click.echo(f"  Gateway: agentstack-gateway-{gw_name}")
    else:
        click.echo("FAILED")
        click.echo(f"  Error: {result.message}", err=True)
        raise SystemExit(1)
```

- [ ] **Step 2: Run CLI tests**

Run: `uv run pytest packages/python/agentstack-cli/tests/ -v`

Expected: all tests PASS (existing tests don't use SlackChannel).

- [ ] **Step 3: Commit**

```bash
git add packages/python/agentstack-cli/
git commit -m "feat: show gateway info in apply output"
```

---

### Task 5: CLI Destroy — Gateway Route Cleanup

**Files:**
- Modify: `packages/python/agentstack-cli/src/agentstack_cli/commands/destroy.py`

- [ ] **Step 1: Update destroy.py**

The `destroy()` method on DockerProvider already handles gateway cleanup when `include_resources=True`. For the non-include-resources case, we should update routes.json to remove the agent's routes. But for MVP, the gateway is only destroyed with `--include-resources`. Route deregistration can be added later.

No code changes needed — the provider's `destroy()` already handles the `include_resources` path with `self.destroy_gateways()`.

However, we need to make sure `set_agent()` is called even without `--include-resources` so the provider knows about channels. Update destroy.py:

```python
def destroy(file_path, agent_name, include_resources):
    """Stop and remove a deployed agent."""
    agent = None
    if agent_name is None:
        path = find_agent_file(file=file_path)
        agent = load_agent_from_file(path)
        agent_name = agent.name

    click.echo(f"Destroying: {agent_name}")
    provider = DockerProvider()

    if agent:
        provider.set_agent(agent)

    click.echo(f"Stopping container agentstack-{agent_name}... ", nl=False)
    try:
        provider.destroy(agent_name, include_resources=include_resources)
        click.echo("OK")
        if include_resources:
            click.echo("Resource and gateway containers removed (volumes preserved)")
        click.echo(f"Destroyed: {agent_name}")
    except Exception as e:
        click.echo("FAILED")
        click.echo(f"  Error: {e}", err=True)
        raise SystemExit(1)
```

- [ ] **Step 2: Run CLI tests**

Run: `uv run pytest packages/python/agentstack-cli/tests/ -v`

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add packages/python/agentstack-cli/
git commit -m "feat: destroy gateways with --include-resources"
```

---

### Task 6: Full Verification

- [ ] **Step 1: Run all Python tests**

Run: `just test-python`

Expected: all tests pass across all packages.

- [ ] **Step 2: Run linting**

Run: `uv run ruff check packages/python/agentstack-provider-docker/ packages/python/agentstack-gateway/ packages/python/agentstack-cli/`

Fix any lint errors.

- [ ] **Step 3: Verify gateway source generation**

Run:
```bash
uv run python -c "
from pathlib import Path
from agentstack_provider_docker.gateway import write_gateway_source, write_routes_file
import tempfile

with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp) / 'gateway'
    write_gateway_source(d)
    print('Generated files:')
    for f in sorted(d.rglob('*')):
        if f.is_file():
            print(f'  {f.relative_to(d)}')

    routes_path = d / 'routes.json'
    write_routes_file(routes_path, [
        {'name': 'test-slack', 'type': 'slack', 'config': {'bot_token': 'xoxb-test', 'app_token': 'xapp-test'}},
    ], [
        {'provider_name': 'test-slack', 'agent_name': 'bot', 'agent_url': 'http://bot:8000', 'channels': ['#test'], 'listen': 'mentions', 'threads': True, 'dm': True},
    ])
    import json
    print()
    print('routes.json:')
    print(json.dumps(json.loads(routes_path.read_text()), indent=2))
"
```

Expected: prints list of generated files and valid routes.json.
