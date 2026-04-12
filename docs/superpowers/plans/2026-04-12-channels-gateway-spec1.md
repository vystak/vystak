# Channels & Gateway (Spec 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Gateway, ChannelProvider, and SlackChannel schema models, then build the gateway package — a standalone FastAPI service that manages Slack bot connections and routes events to agent API endpoints.

**Architecture:** New schema models (Gateway, ChannelProvider, SlackChannel) in the core SDK. A new `agentstack-gateway` package with a FastAPI management API, a routing table, and a Slack Socket Mode provider. The gateway receives Slack events and POSTs to agent `/invoke` endpoints.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, slack-bolt, httpx, pytest

---

### Task 1: Schema Models (Gateway, ChannelProvider, SlackChannel)

**Files:**
- Create: `packages/python/agentstack/src/agentstack/schema/gateway.py`
- Modify: `packages/python/agentstack/src/agentstack/schema/channel.py`
- Modify: `packages/python/agentstack/src/agentstack/schema/__init__.py`
- Modify: `packages/python/agentstack/src/agentstack/__init__.py`
- Create: `packages/python/agentstack/tests/test_gateway.py`
- Create: `packages/python/agentstack/tests/test_slack_channel.py`

- [ ] **Step 1: Write tests for gateway.py**

`packages/python/agentstack/tests/test_gateway.py`:
```python
import pytest
from pydantic import ValidationError

from agentstack.schema.gateway import ChannelProvider, Gateway
from agentstack.schema.provider import Provider
from agentstack.schema.secret import Secret


@pytest.fixture()
def docker():
    return Provider(name="docker", type="docker")


@pytest.fixture()
def gateway(docker):
    return Gateway(name="main-gateway", provider=docker, config={"port": 8080})


class TestGateway:
    def test_create(self, docker):
        gw = Gateway(name="main", provider=docker)
        assert gw.name == "main"
        assert gw.provider.name == "docker"
        assert gw.config == {}

    def test_with_config(self, docker):
        gw = Gateway(name="main", provider=docker, config={"port": 8080})
        assert gw.config["port"] == 8080

    def test_provider_required(self):
        with pytest.raises(ValidationError):
            Gateway(name="main")

    def test_serialization_roundtrip(self, docker):
        gw = Gateway(name="main", provider=docker, config={"port": 8080})
        data = gw.model_dump()
        restored = Gateway.model_validate(data)
        assert restored == gw


class TestChannelProvider:
    def test_create(self, gateway):
        cp = ChannelProvider(
            name="internal-slack",
            type="slack",
            gateway=gateway,
            config={"bot_token": "xoxb-test", "app_token": "xapp-test"},
        )
        assert cp.name == "internal-slack"
        assert cp.type == "slack"
        assert cp.gateway.name == "main-gateway"

    def test_gateway_required(self):
        with pytest.raises(ValidationError):
            ChannelProvider(name="test", type="slack")

    def test_type_required(self, gateway):
        with pytest.raises(ValidationError):
            ChannelProvider(name="test", gateway=gateway)

    def test_serialization_roundtrip(self, gateway):
        cp = ChannelProvider(
            name="slack",
            type="slack",
            gateway=gateway,
            config={"bot_token": "xoxb-test"},
        )
        data = cp.model_dump()
        restored = ChannelProvider.model_validate(data)
        assert restored == cp
```

- [ ] **Step 2: Write tests for SlackChannel**

`packages/python/agentstack/tests/test_slack_channel.py`:
```python
import pytest
from pydantic import ValidationError

from agentstack.schema.channel import SlackChannel
from agentstack.schema.gateway import ChannelProvider, Gateway
from agentstack.schema.provider import Provider


@pytest.fixture()
def slack_provider():
    docker = Provider(name="docker", type="docker")
    gw = Gateway(name="main", provider=docker)
    return ChannelProvider(
        name="internal-slack",
        type="slack",
        gateway=gw,
        config={"bot_token": "xoxb-test", "app_token": "xapp-test"},
    )


class TestSlackChannel:
    def test_create_minimal(self, slack_provider):
        ch = SlackChannel(name="support", provider=slack_provider)
        assert ch.name == "support"
        assert ch.channels == []
        assert ch.listen == "mentions"
        assert ch.threads is True
        assert ch.dm is True

    def test_create_full(self, slack_provider):
        ch = SlackChannel(
            name="support",
            provider=slack_provider,
            channels=["#support", "#help"],
            listen="messages",
            threads=False,
            dm=False,
        )
        assert ch.channels == ["#support", "#help"]
        assert ch.listen == "messages"
        assert ch.threads is False
        assert ch.dm is False

    def test_provider_required(self):
        with pytest.raises(ValidationError):
            SlackChannel(name="support")

    def test_serialization_roundtrip(self, slack_provider):
        ch = SlackChannel(
            name="support",
            provider=slack_provider,
            channels=["#support"],
            listen="mentions",
        )
        data = ch.model_dump()
        restored = SlackChannel.model_validate(data)
        assert restored == ch
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/akolodkin/Developer/work/AgentsStack && uv run pytest packages/python/agentstack/tests/test_gateway.py packages/python/agentstack/tests/test_slack_channel.py -v`

Expected: FAIL — modules not found.

- [ ] **Step 4: Implement gateway.py**

`packages/python/agentstack/src/agentstack/schema/gateway.py`:
```python
"""Gateway and ChannelProvider models."""

from agentstack.schema.common import NamedModel
from agentstack.schema.provider import Provider


class Gateway(NamedModel):
    """A running service that manages channel provider connections."""

    provider: Provider
    config: dict = {}


class ChannelProvider(NamedModel):
    """A bot connection managed by a gateway."""

    type: str
    gateway: Gateway
    config: dict = {}
```

- [ ] **Step 5: Add SlackChannel to channel.py**

Append to `packages/python/agentstack/src/agentstack/schema/channel.py`:

```python
from agentstack.schema.gateway import ChannelProvider


class SlackChannel(NamedModel):
    """A Slack channel binding — routes Slack events to an agent."""

    provider: ChannelProvider
    channels: list[str] = []
    listen: str = "mentions"
    threads: bool = True
    dm: bool = True
```

- [ ] **Step 6: Update schema/__init__.py**

Add imports and re-exports for `Gateway`, `ChannelProvider`, `SlackChannel`:

Add these imports:
```python
from agentstack.schema.channel import SlackChannel
from agentstack.schema.gateway import ChannelProvider, Gateway
```

Add to `__all__`: `"ChannelProvider"`, `"Gateway"`, `"SlackChannel"`

- [ ] **Step 7: Update agentstack/__init__.py**

Add to the schema import block:
```python
from agentstack.schema import (
    ..., ChannelProvider, Gateway, SlackChannel,
)
```

Add to `__all__`: `"ChannelProvider"`, `"Gateway"`, `"SlackChannel"`

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack/tests/test_gateway.py packages/python/agentstack/tests/test_slack_channel.py -v`

Expected: all tests PASS.

- [ ] **Step 9: Run all core SDK tests**

Run: `uv run pytest packages/python/agentstack/tests/ -v`

Expected: all tests PASS (existing + new).

- [ ] **Step 10: Commit**

```bash
git add packages/python/agentstack/
git commit -m "feat: add Gateway, ChannelProvider, SlackChannel schema models"
```

---

### Task 2: Gateway Package Scaffolding + Router

**Files:**
- Create: `packages/python/agentstack-gateway/pyproject.toml`
- Create: `packages/python/agentstack-gateway/src/agentstack_gateway/__init__.py`
- Create: `packages/python/agentstack-gateway/src/agentstack_gateway/router.py`
- Create: `packages/python/agentstack-gateway/tests/test_router.py`
- Modify: `pyproject.toml` (root workspace)

- [ ] **Step 1: Create pyproject.toml**

`packages/python/agentstack-gateway/pyproject.toml`:
```toml
[project]
name = "agentstack-gateway"
version = "0.1.0"
description = "AgentStack channel gateway — routes events to agents"
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
    "agentstack>=0.1.0",
    "fastapi>=0.115",
    "uvicorn>=0.34",
    "httpx>=0.28",
    "slack-bolt>=1.21",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentstack_gateway"]

[tool.uv.sources]
agentstack = { workspace = true }
```

- [ ] **Step 2: Create __init__.py**

`packages/python/agentstack-gateway/src/agentstack_gateway/__init__.py`:
```python
"""AgentStack channel gateway — routes events to agents."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Add to root workspace**

Add `"agentstack-gateway"` to root `pyproject.toml` dev-dependencies and `agentstack-gateway = { workspace = true }` to `[tool.uv.sources]`.

Run: `cd /Users/akolodkin/Developer/work/AgentsStack && uv sync`

- [ ] **Step 4: Write router tests**

`packages/python/agentstack-gateway/tests/test_router.py`:
```python
import pytest

from agentstack_gateway.router import Route, Router


@pytest.fixture()
def router():
    return Router()


@pytest.fixture()
def support_route():
    return Route(
        provider_name="internal-slack",
        agent_name="support-bot",
        agent_url="http://agentstack-support-bot:8000",
        channels=["#support", "#help"],
        listen="mentions",
        threads=True,
        dm=True,
    )


@pytest.fixture()
def sales_route():
    return Route(
        provider_name="internal-slack",
        agent_name="sales-bot",
        agent_url="http://agentstack-sales-bot:8000",
        channels=["#sales"],
        listen="messages",
        threads=True,
        dm=False,
    )


@pytest.fixture()
def customer_route():
    return Route(
        provider_name="customer-slack",
        agent_name="customer-bot",
        agent_url="http://agentstack-customer-bot:8000",
        channels=["#customer-help"],
        listen="messages",
        threads=True,
        dm=True,
    )


class TestAddRoute:
    def test_add_and_list(self, router, support_route):
        router.add_route(support_route)
        routes = router.list_routes()
        assert len(routes) == 1
        assert routes[0].agent_name == "support-bot"


class TestResolve:
    def test_resolve_by_channel(self, router, support_route):
        router.add_route(support_route)
        route = router.resolve("internal-slack", "#support", is_dm=False)
        assert route is not None
        assert route.agent_name == "support-bot"

    def test_resolve_second_channel(self, router, support_route):
        router.add_route(support_route)
        route = router.resolve("internal-slack", "#help", is_dm=False)
        assert route is not None
        assert route.agent_name == "support-bot"

    def test_resolve_no_match(self, router, support_route):
        router.add_route(support_route)
        route = router.resolve("internal-slack", "#random", is_dm=False)
        assert route is None

    def test_resolve_dm(self, router, support_route):
        router.add_route(support_route)
        route = router.resolve("internal-slack", None, is_dm=True)
        assert route is not None
        assert route.agent_name == "support-bot"

    def test_resolve_dm_disabled(self, router, sales_route):
        router.add_route(sales_route)
        route = router.resolve("internal-slack", None, is_dm=True)
        assert route is None

    def test_multiple_providers(self, router, support_route, customer_route):
        router.add_route(support_route)
        router.add_route(customer_route)

        r1 = router.resolve("internal-slack", "#support", is_dm=False)
        assert r1.agent_name == "support-bot"

        r2 = router.resolve("customer-slack", "#customer-help", is_dm=False)
        assert r2.agent_name == "customer-bot"

    def test_same_provider_different_channels(self, router, support_route, sales_route):
        router.add_route(support_route)
        router.add_route(sales_route)

        r1 = router.resolve("internal-slack", "#support", is_dm=False)
        assert r1.agent_name == "support-bot"

        r2 = router.resolve("internal-slack", "#sales", is_dm=False)
        assert r2.agent_name == "sales-bot"


class TestRemoveRoutes:
    def test_remove(self, router, support_route, sales_route):
        router.add_route(support_route)
        router.add_route(sales_route)
        router.remove_routes("support-bot")
        routes = router.list_routes()
        assert len(routes) == 1
        assert routes[0].agent_name == "sales-bot"

    def test_remove_nonexistent(self, router):
        router.remove_routes("nobody")  # should not raise
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack-gateway/tests/test_router.py -v`

Expected: FAIL.

- [ ] **Step 6: Implement router.py**

`packages/python/agentstack-gateway/src/agentstack_gateway/router.py`:
```python
"""Routing table — maps channel events to agent endpoints."""

from dataclasses import dataclass, field


@dataclass
class Route:
    """A mapping from a channel provider + channel to an agent."""

    provider_name: str
    agent_name: str
    agent_url: str
    channels: list[str] = field(default_factory=list)
    listen: str = "mentions"
    threads: bool = True
    dm: bool = True


class Router:
    """Routes incoming channel events to the correct agent."""

    def __init__(self):
        self._routes: list[Route] = []

    def add_route(self, route: Route) -> None:
        self._routes.append(route)

    def remove_routes(self, agent_name: str) -> None:
        self._routes = [r for r in self._routes if r.agent_name != agent_name]

    def resolve(self, provider_name: str, channel: str | None, is_dm: bool) -> Route | None:
        """Find the route for a given provider + channel or DM."""
        for route in self._routes:
            if route.provider_name != provider_name:
                continue
            if is_dm:
                if route.dm:
                    return route
                continue
            if channel in route.channels:
                return route
        return None

    def list_routes(self) -> list[Route]:
        return list(self._routes)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-gateway/tests/test_router.py -v`

Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add packages/python/agentstack-gateway/ pyproject.toml uv.lock
git commit -m "feat: add gateway package with routing table"
```

---

### Task 3: Gateway Management API

**Files:**
- Create: `packages/python/agentstack-gateway/src/agentstack_gateway/server.py`
- Create: `packages/python/agentstack-gateway/tests/test_server.py`

- [ ] **Step 1: Write tests**

`packages/python/agentstack-gateway/tests/test_server.py`:
```python
import pytest
from fastapi.testclient import TestClient

from agentstack_gateway.server import app, router, providers


@pytest.fixture(autouse=True)
def reset_state():
    """Reset gateway state between tests."""
    router._routes.clear()
    providers.clear()
    yield
    router._routes.clear()
    providers.clear()


client = TestClient(app)


class TestHealth:
    def test_health(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestRegisterRoute:
    def test_register(self):
        response = client.post("/register-route", json={
            "provider_name": "internal-slack",
            "agent_name": "support-bot",
            "agent_url": "http://agentstack-support-bot:8000",
            "channels": ["#support"],
            "listen": "mentions",
            "threads": True,
            "dm": True,
        })
        assert response.status_code == 200

    def test_list_after_register(self):
        client.post("/register-route", json={
            "provider_name": "internal-slack",
            "agent_name": "support-bot",
            "agent_url": "http://agentstack-support-bot:8000",
            "channels": ["#support"],
        })
        response = client.get("/routes")
        assert response.status_code == 200
        routes = response.json()
        assert len(routes) == 1
        assert routes[0]["agent_name"] == "support-bot"


class TestRemoveRoutes:
    def test_remove(self):
        client.post("/register-route", json={
            "provider_name": "internal-slack",
            "agent_name": "support-bot",
            "agent_url": "http://agentstack-support-bot:8000",
            "channels": ["#support"],
        })
        response = client.delete("/routes/support-bot")
        assert response.status_code == 200

        routes = client.get("/routes").json()
        assert len(routes) == 0


class TestRegisterProvider:
    def test_register(self):
        response = client.post("/register-provider", json={
            "name": "internal-slack",
            "type": "slack",
            "config": {"bot_token": "xoxb-test", "app_token": "xapp-test"},
        })
        assert response.status_code == 200
        assert response.json()["status"] == "registered"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack-gateway/tests/test_server.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement server.py**

`packages/python/agentstack-gateway/src/agentstack_gateway/server.py`:
```python
"""Gateway management API."""

import asyncio
import os

from fastapi import FastAPI
from pydantic import BaseModel

from agentstack_gateway.router import Route, Router

app = FastAPI(title="agentstack-gateway")
router = Router()
providers: dict = {}  # name -> ChannelProviderRunner

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))


class RegisterProviderRequest(BaseModel):
    name: str
    type: str
    config: dict


class RegisterRouteRequest(BaseModel):
    provider_name: str
    agent_name: str
    agent_url: str
    channels: list[str] = []
    listen: str = "mentions"
    threads: bool = True
    dm: bool = True


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "providers": list(providers.keys()),
        "routes": len(router.list_routes()),
    }


@app.post("/register-provider")
async def register_provider(request: RegisterProviderRequest):
    if request.name in providers:
        return {"status": "already_registered", "name": request.name}

    if request.type == "slack":
        from agentstack_gateway.providers.slack import SlackProviderRunner

        runner = SlackProviderRunner(
            name=request.name,
            config=request.config,
            event_router=router,
        )
        providers[request.name] = runner
        asyncio.create_task(runner.start())
        return {"status": "registered", "name": request.name}

    return {"status": "error", "message": f"Unknown provider type: {request.type}"}


@app.post("/register-route")
async def register_route(request: RegisterRouteRequest):
    route = Route(
        provider_name=request.provider_name,
        agent_name=request.agent_name,
        agent_url=request.agent_url,
        channels=request.channels,
        listen=request.listen,
        threads=request.threads,
        dm=request.dm,
    )
    router.add_route(route)
    return {"status": "ok", "agent": request.agent_name}


@app.delete("/routes/{agent_name}")
async def remove_routes(agent_name: str):
    router.remove_routes(agent_name)
    return {"status": "ok", "agent": agent_name}


@app.get("/routes")
async def list_routes():
    return [
        {
            "provider_name": r.provider_name,
            "agent_name": r.agent_name,
            "agent_url": r.agent_url,
            "channels": r.channels,
            "listen": r.listen,
            "threads": r.threads,
            "dm": r.dm,
        }
        for r in router.list_routes()
    ]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-gateway/tests/test_server.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-gateway/
git commit -m "feat: add gateway management API"
```

---

### Task 4: Channel Provider ABC + Slack Provider

**Files:**
- Create: `packages/python/agentstack-gateway/src/agentstack_gateway/providers/__init__.py`
- Create: `packages/python/agentstack-gateway/src/agentstack_gateway/providers/base.py`
- Create: `packages/python/agentstack-gateway/src/agentstack_gateway/providers/slack.py`
- Create: `packages/python/agentstack-gateway/tests/test_slack.py`

- [ ] **Step 1: Create providers/__init__.py**

`packages/python/agentstack-gateway/src/agentstack_gateway/providers/__init__.py`:
```python
"""Channel provider runners."""
```

- [ ] **Step 2: Implement base.py**

`packages/python/agentstack-gateway/src/agentstack_gateway/providers/base.py`:
```python
"""Abstract base class for channel provider runners."""

from abc import ABC, abstractmethod


class ChannelProviderRunner(ABC):
    """Manages a bot connection and dispatches events to the router."""

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def is_running(self) -> bool: ...
```

- [ ] **Step 3: Write Slack provider tests**

`packages/python/agentstack-gateway/tests/test_slack.py`:
```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentstack_gateway.router import Route, Router
from agentstack_gateway.providers.slack import SlackProviderRunner, _build_session_id


class TestBuildSessionId:
    def test_thread(self):
        sid = _build_session_id("my-slack", "#support", thread_ts="1234.5678", ts="9999.0000")
        assert sid == "slack:my-slack:#support:1234.5678"

    def test_new_message(self):
        sid = _build_session_id("my-slack", "#support", thread_ts=None, ts="9999.0000")
        assert sid == "slack:my-slack:#support:9999.0000"

    def test_dm(self):
        sid = _build_session_id("my-slack", None, thread_ts=None, ts="9999.0000", user_id="U123")
        assert sid == "slack:my-slack:dm:U123"


class TestSlackProviderRunner:
    @patch("agentstack_gateway.providers.slack.AsyncApp")
    @patch("agentstack_gateway.providers.slack.AsyncSocketModeHandler")
    def test_create(self, mock_handler_cls, mock_app_cls):
        router = Router()
        runner = SlackProviderRunner(
            name="test-slack",
            config={"bot_token": "xoxb-test", "app_token": "xapp-test"},
            event_router=router,
        )
        assert runner.name == "test-slack"
        assert runner.is_running() is False
        mock_app_cls.assert_called_once_with(token="xoxb-test")

    @patch("agentstack_gateway.providers.slack.AsyncApp")
    @patch("agentstack_gateway.providers.slack.AsyncSocketModeHandler")
    def test_is_not_running_initially(self, mock_handler_cls, mock_app_cls):
        router = Router()
        runner = SlackProviderRunner(
            name="test-slack",
            config={"bot_token": "xoxb-test", "app_token": "xapp-test"},
            event_router=router,
        )
        assert runner.is_running() is False


@pytest.mark.asyncio
class TestSlackEventHandling:
    @patch("agentstack_gateway.providers.slack.httpx")
    @patch("agentstack_gateway.providers.slack.AsyncApp")
    @patch("agentstack_gateway.providers.slack.AsyncSocketModeHandler")
    async def test_message_routed(self, mock_handler_cls, mock_app_cls, mock_httpx):
        router = Router()
        router.add_route(Route(
            provider_name="test-slack",
            agent_name="support-bot",
            agent_url="http://agent:8000",
            channels=["#support"],
            listen="messages",
            threads=True,
            dm=True,
        ))

        runner = SlackProviderRunner(
            name="test-slack",
            config={"bot_token": "xoxb-test", "app_token": "xapp-test"},
            event_router=router,
        )

        # Simulate a message event
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Hello!", "session_id": "test"}
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_httpx.AsyncClient.return_value = mock_client

        say = AsyncMock()

        await runner._handle_message(
            event={"text": "hello", "channel": "#support", "ts": "123.456", "user": "U1"},
            say=say,
        )

        mock_client.post.assert_called_once()
        say.assert_called_once()

    @patch("agentstack_gateway.providers.slack.httpx")
    @patch("agentstack_gateway.providers.slack.AsyncApp")
    @patch("agentstack_gateway.providers.slack.AsyncSocketModeHandler")
    async def test_message_ignored_no_route(self, mock_handler_cls, mock_app_cls, mock_httpx):
        router = Router()
        runner = SlackProviderRunner(
            name="test-slack",
            config={"bot_token": "xoxb-test", "app_token": "xapp-test"},
            event_router=router,
        )

        say = AsyncMock()
        await runner._handle_message(
            event={"text": "hello", "channel": "#random", "ts": "123.456", "user": "U1"},
            say=say,
        )

        say.assert_not_called()

    @patch("agentstack_gateway.providers.slack.httpx")
    @patch("agentstack_gateway.providers.slack.AsyncApp")
    @patch("agentstack_gateway.providers.slack.AsyncSocketModeHandler")
    async def test_dm_routed(self, mock_handler_cls, mock_app_cls, mock_httpx):
        router = Router()
        router.add_route(Route(
            provider_name="test-slack",
            agent_name="support-bot",
            agent_url="http://agent:8000",
            channels=["#support"],
            listen="mentions",
            dm=True,
        ))

        runner = SlackProviderRunner(
            name="test-slack",
            config={"bot_token": "xoxb-test", "app_token": "xapp-test"},
            event_router=router,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Hi!", "session_id": "test"}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_httpx.AsyncClient.return_value = mock_client

        say = AsyncMock()
        await runner._handle_message(
            event={"text": "hello", "channel": "D123", "ts": "123.456", "user": "U1", "channel_type": "im"},
            say=say,
        )

        mock_client.post.assert_called_once()
        say.assert_called_once()

    @patch("agentstack_gateway.providers.slack.httpx")
    @patch("agentstack_gateway.providers.slack.AsyncApp")
    @patch("agentstack_gateway.providers.slack.AsyncSocketModeHandler")
    async def test_dm_ignored_when_disabled(self, mock_handler_cls, mock_app_cls, mock_httpx):
        router = Router()
        router.add_route(Route(
            provider_name="test-slack",
            agent_name="support-bot",
            agent_url="http://agent:8000",
            channels=["#support"],
            listen="mentions",
            dm=False,
        ))

        runner = SlackProviderRunner(
            name="test-slack",
            config={"bot_token": "xoxb-test", "app_token": "xapp-test"},
            event_router=router,
        )

        say = AsyncMock()
        await runner._handle_message(
            event={"text": "hello", "channel": "D123", "ts": "123.456", "user": "U1", "channel_type": "im"},
            say=say,
        )

        say.assert_not_called()
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack-gateway/tests/test_slack.py -v`

Expected: FAIL.

- [ ] **Step 5: Implement slack.py**

`packages/python/agentstack-gateway/src/agentstack_gateway/providers/slack.py`:
```python
"""Slack Socket Mode channel provider."""

import httpx
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from agentstack_gateway.providers.base import ChannelProviderRunner
from agentstack_gateway.router import Router


def _build_session_id(
    provider_name: str,
    channel: str | None,
    thread_ts: str | None = None,
    ts: str | None = None,
    user_id: str | None = None,
) -> str:
    """Build a session ID from Slack event context."""
    if channel is None and user_id:
        return f"slack:{provider_name}:dm:{user_id}"
    if thread_ts:
        return f"slack:{provider_name}:{channel}:{thread_ts}"
    return f"slack:{provider_name}:{channel}:{ts}"


class SlackProviderRunner(ChannelProviderRunner):
    """Manages a Slack Socket Mode connection."""

    def __init__(self, name: str, config: dict, event_router: Router):
        self.name = name
        self._router = event_router
        self._running = False

        self._app = AsyncApp(token=config["bot_token"])
        self._handler = AsyncSocketModeHandler(self._app, config["app_token"])

        self._setup_listeners()

    def _setup_listeners(self):
        @self._app.event("message")
        async def on_message(event, say):
            await self._handle_message(event, say)

        @self._app.event("app_mention")
        async def on_mention(event, say):
            await self._handle_mention(event, say)

    async def _handle_message(self, event: dict, say) -> None:
        """Handle a message event from Slack."""
        # Skip bot messages
        if event.get("bot_id") or event.get("subtype"):
            return

        channel = event.get("channel", "")
        is_dm = event.get("channel_type") == "im"

        route = self._router.resolve(self.name, channel if not is_dm else None, is_dm=is_dm)
        if route is None:
            return

        # For non-DM messages with listen=mentions, skip (handled by app_mention)
        if not is_dm and route.listen == "mentions":
            return

        await self._forward_and_reply(event, route, say)

    async def _handle_mention(self, event: dict, say) -> None:
        """Handle an app_mention event from Slack."""
        channel = event.get("channel", "")
        route = self._router.resolve(self.name, channel, is_dm=False)
        if route is None:
            return

        await self._forward_and_reply(event, route, say)

    async def _forward_and_reply(self, event: dict, route, say) -> None:
        """Forward message to agent and reply in Slack."""
        is_dm = event.get("channel_type") == "im"
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts")
        ts = event.get("ts")
        user_id = event.get("user")

        session_id = _build_session_id(
            self.name,
            channel if not is_dm else None,
            thread_ts=thread_ts,
            ts=ts,
            user_id=user_id if is_dm else None,
        )

        text = event.get("text", "")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{route.agent_url}/invoke",
                json={"message": text, "session_id": session_id},
            )

        if response.status_code == 200:
            data = response.json()
            reply_text = data.get("response", "")

            reply_kwargs = {"text": reply_text}
            if route.threads and not is_dm:
                reply_kwargs["thread_ts"] = thread_ts or ts

            await say(**reply_kwargs)

    async def start(self) -> None:
        self._running = True
        await self._handler.start_async()

    async def stop(self) -> None:
        self._running = False
        await self._handler.close_async()

    def is_running(self) -> bool:
        return self._running
```

- [ ] **Step 6: Add pytest-asyncio dependency**

Add `"pytest-asyncio>=0.25"` to the root `pyproject.toml` dev-dependencies. Run `uv sync`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-gateway/tests/test_slack.py -v`

Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add packages/python/agentstack-gateway/ pyproject.toml uv.lock
git commit -m "feat: add Slack Socket Mode provider for gateway"
```

---

### Task 5: Full Verification

- [ ] **Step 1: Run all Python tests**

Run: `just test-python`

Expected: all tests pass across all packages.

- [ ] **Step 2: Run linting**

Run: `uv run ruff check packages/python/agentstack-gateway/ packages/python/agentstack/`

Fix any lint errors.

- [ ] **Step 3: Verify schema imports work**

Run:
```bash
uv run python -c "
from agentstack import Gateway, ChannelProvider, SlackChannel, Provider, Secret

docker = Provider(name='docker', type='docker')
gw = Gateway(name='main', provider=docker)
cp = ChannelProvider(name='slack', type='slack', gateway=gw, config={'bot_token': 'test'})
ch = SlackChannel(name='support', provider=cp, channels=['#support'], listen='mentions')
print(f'Gateway: {gw.name}')
print(f'ChannelProvider: {cp.name} (type={cp.type})')
print(f'SlackChannel: {ch.name} (channels={ch.channels}, listen={ch.listen})')
"
```

Expected: prints gateway, provider, and channel info.

- [ ] **Step 4: Verify gateway server starts**

Run:
```bash
uv run python -c "
from agentstack_gateway.server import app
from agentstack_gateway.router import Router
print(f'Gateway app: {app.title}')
print(f'Routes: {[r.path for r in app.routes]}')
"
```

Expected: prints app title and route paths.
