# Channels & Gateway (Spec 1) — Schema + Gateway Package

## Overview

Add Gateway and ChannelProvider as first-class concepts to AgentStack. Build the gateway package — a standalone service that manages channel provider connections (Slack bots, etc.) and routes events to agent API endpoints. This spec covers schema models and the gateway package. Spec 2 covers Docker provisioning and CLI integration.

## Architecture

```
Gateway container (one or more)
├── Management API (:8080)
│   ├── POST /register-provider
│   ├── POST /register-route
│   ├── DELETE /routes/{agent_name}
│   ├── GET  /health
│   └── GET  /routes
├── Channel Providers (bot connections)
│   ├── internal-slack (Socket Mode)
│   └── customer-slack (Socket Mode)
└── Router
    └── event → match channel → POST agent /invoke
```

Agents are stateless API endpoints. The gateway handles all channel connections and routes events to agents via their `/invoke` endpoint. Multiple agents can share a gateway. Multiple gateways can run independently.

## Decisions

| Decision | Choice |
|----------|--------|
| Gateway deployment | Separate container, provisioned as a resource |
| Channel connections | Managed by gateway, not by agent containers |
| Slack mode | Socket Mode (outbound WebSocket, no public URL) |
| Routing | Channel provider + Slack channel → agent URL |
| Bot credentials | Per ChannelProvider, multiple providers per gateway |
| Agent scaling | Stateless replicas, Postgres handles session locking |
| Default listen mode | mentions (agent responds when @mentioned) |

## Python API

```python
import agentstack as ast

docker = ast.Provider(name="docker", type="docker")

# Gateway — the running service
gateway = ast.Gateway(
    name="main-gateway",
    provider=docker,
    config={"port": 8080},
)

# Channel providers — bot connections on the gateway
internal_slack = ast.ChannelProvider(
    name="internal-slack",
    type="slack",
    gateway=gateway,
    config={
        "bot_token": ast.Secret("INTERNAL_SLACK_BOT_TOKEN"),
        "app_token": ast.Secret("INTERNAL_SLACK_APP_TOKEN"),
    },
)

customer_slack = ast.ChannelProvider(
    name="customer-slack",
    type="slack",
    gateway=gateway,
    config={
        "bot_token": ast.Secret("CUSTOMER_SLACK_BOT_TOKEN"),
        "app_token": ast.Secret("CUSTOMER_SLACK_APP_TOKEN"),
    },
)

postgres = ast.SessionStore(name="sessions", provider=docker, engine="postgres")

# Agent 1
support_bot = ast.Agent(
    name="support-bot",
    model=sonnet,
    channels=[
        ast.Channel(name="api", type=ast.ChannelType.API),
        ast.SlackChannel(
            name="support",
            provider=internal_slack,
            channels=["#support", "#help"],
            listen="mentions",
            threads=True,
            dm=True,
        ),
    ],
    resources=[postgres],
)

# Agent 2 — same gateway, different bot
customer_bot = ast.Agent(
    name="customer-bot",
    model=sonnet,
    channels=[
        ast.SlackChannel(
            name="customer-support",
            provider=customer_slack,
            channels=["#customer-help"],
            listen="messages",
            threads=True,
        ),
    ],
    resources=[postgres],
)

# Agent 3 — same bot as Agent 1, different channels
hr_bot = ast.Agent(
    name="hr-bot",
    model=sonnet,
    channels=[
        ast.SlackChannel(
            name="hr",
            provider=internal_slack,
            channels=["#hr-questions"],
            listen="mentions",
        ),
    ],
    resources=[postgres],
)
```

## Schema Models

### gateway.py — new file

```python
class Gateway(NamedModel):
    """A running service that manages channel provider connections."""
    name: str
    provider: Provider
    config: dict = {}

class ChannelProvider(NamedModel):
    """A bot connection managed by a gateway."""
    name: str
    type: str                    # "slack", "discord", "telegram", etc.
    gateway: Gateway
    config: dict = {}            # bot tokens, secrets, etc.
```

### channel.py — modified

Add `SlackChannel` subclass:

```python
class SlackChannel(NamedModel):
    """A Slack channel binding — routes Slack events to an agent."""
    name: str
    provider: ChannelProvider
    channels: list[str] = []     # Slack channels to listen in
    listen: str = "mentions"     # "mentions" | "messages" | "all"
    threads: bool = True         # reply in threads
    dm: bool = True              # respond to DMs
```

Existing `Channel` stays unchanged for API and simple channel types.

### Schema re-exports

Add to `agentstack.schema.__init__` and `agentstack.__init__`:
- `Gateway`
- `ChannelProvider`
- `SlackChannel`

## Gateway Package

### Package structure

```
packages/python/agentstack-gateway/
├── pyproject.toml
├── src/agentstack_gateway/
│   ├── __init__.py              # __version__, exports
│   ├── server.py                # FastAPI management API
│   ├── router.py                # Routing table + event dispatch
│   └── providers/
│       ├── __init__.py
│       ├── base.py              # ChannelProviderRunner ABC
│       └── slack.py             # Slack Socket Mode runner
└── tests/
    ├── test_server.py           # Management API tests
    ├── test_router.py           # Routing logic tests
    └── test_slack.py            # Slack provider tests (mocked)
```

### Dependencies

- `fastapi` — management API
- `uvicorn` — server
- `slack-bolt` — Slack Socket Mode
- `httpx` — forward events to agent `/invoke`
- `agentstack` — core SDK (for types)

### server.py — Management API

```python
app = FastAPI(title="agentstack-gateway")

@app.post("/register-provider")
async def register_provider(request: RegisterProviderRequest):
    """Register a channel provider (start a bot connection)."""
    # Starts a Slack Socket Mode connection in the background

@app.post("/register-route")
async def register_route(request: RegisterRouteRequest):
    """Map a channel to an agent URL."""
    # Adds to routing table: (provider_name, slack_channel) → agent_url

@app.delete("/routes/{agent_name}")
async def remove_routes(agent_name: str):
    """Remove all routes for an agent."""

@app.get("/routes")
async def list_routes():
    """List all active routes."""

@app.get("/health")
async def health():
    """Health check."""
```

Request models:

```python
class RegisterProviderRequest(BaseModel):
    name: str                    # "internal-slack"
    type: str                    # "slack"
    config: dict                 # {"bot_token": "xoxb-...", "app_token": "xapp-..."}

class RegisterRouteRequest(BaseModel):
    provider_name: str           # "internal-slack"
    agent_name: str              # "support-bot"
    agent_url: str               # "http://agentstack-support-bot:8000"
    channels: list[str]          # ["#support", "#help"]
    listen: str = "mentions"
    threads: bool = True
    dm: bool = True
```

### router.py — Routing Table

```python
class Route:
    provider_name: str
    agent_name: str
    agent_url: str
    channels: list[str]
    listen: str
    threads: bool
    dm: bool

class Router:
    def add_route(self, route: Route): ...
    def remove_routes(self, agent_name: str): ...
    def resolve(self, provider_name: str, channel: str, is_dm: bool) -> Route | None: ...
    def list_routes(self) -> list[Route]: ...
```

The router resolves: given a provider name + Slack channel (or DM), which agent should handle it?

### providers/base.py — ABC

```python
class ChannelProviderRunner(ABC):
    """Manages a bot connection and dispatches events to the router."""

    @abstractmethod
    async def start(self): ...

    @abstractmethod
    async def stop(self): ...

    @abstractmethod
    def is_running(self) -> bool: ...
```

### providers/slack.py — Slack Socket Mode

```python
class SlackProviderRunner(ChannelProviderRunner):
    """Manages a Slack Socket Mode connection."""

    def __init__(self, name: str, config: dict, router: Router):
        self.name = name
        self.router = router
        self.app = AsyncApp(token=config["bot_token"])
        self.handler = AsyncSocketModeHandler(self.app, config["app_token"])
        self._setup_listeners()

    def _setup_listeners(self):
        @self.app.event("message")
        async def on_message(event, say):
            # Determine channel from event
            # Look up route via self.router.resolve()
            # If no route, ignore
            # Check listen mode (mentions vs messages)
            # Build session_id from thread_ts
            # POST to agent_url/invoke
            # Reply via say()

        @self.app.event("app_mention")
        async def on_mention(event, say):
            # Same flow but always responds (mention-triggered)

    async def start(self):
        await self.handler.start_async()

    async def stop(self):
        await self.handler.close_async()
```

**Session ID mapping:**
```
DM:     "slack:{provider}:dm:{user_id}"
Thread: "slack:{provider}:{channel}:{thread_ts}"
New:    "slack:{provider}:{channel}:{message_ts}"
```

**Message flow:**
1. Slack event arrives via Socket Mode
2. SlackProviderRunner receives it
3. Router resolves channel → agent URL + config
4. Check listen mode: if "mentions", only proceed if bot was @mentioned
5. Build session_id from thread context
6. POST `{"message": event.text, "session_id": session_id}` to agent `/invoke`
7. Reply in Slack (in thread if threads=True)

## Testing Strategy

### test_router.py
- `test_add_route` — adds route, resolve finds it
- `test_resolve_by_channel` — correct agent for given channel
- `test_resolve_dm` — DM routes to agent with dm=True
- `test_resolve_no_match` — returns None for unknown channel
- `test_remove_routes` — removes all routes for an agent
- `test_multiple_providers` — routes from different providers to different agents
- `test_same_provider_different_channels` — two agents on same provider, different channels

### test_server.py
- `test_register_provider` — POST /register-provider succeeds
- `test_register_route` — POST /register-route succeeds
- `test_list_routes` — GET /routes returns registered routes
- `test_remove_routes` — DELETE /routes/{name} removes routes
- `test_health` — GET /health returns ok

### test_slack.py (mocked slack-bolt)
- `test_message_routed` — message in configured channel triggers agent call
- `test_message_ignored` — message in unconfigured channel ignored
- `test_mention_mode` — listen=mentions only responds to @mentions
- `test_thread_session` — thread messages get same session_id
- `test_dm_routed` — DM triggers agent call when dm=True
- `test_dm_ignored` — DM ignored when dm=False

## What This Spec Does NOT Cover

- Docker provisioning of gateway containers (Spec 2)
- CLI integration for gateway management (Spec 2)
- End-to-end Slack testing (Spec 2)
- Discord, Telegram, or other channel providers
- Webhook channel type
- Gateway scaling/replication
- Authentication on gateway management API
- Rate limiting
