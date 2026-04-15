"""Gateway management API."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from agentstack_gateway.router import Route, Router
from agentstack_gateway.store import RegistrationStore, create_store

router = Router()
providers: dict = {}
reg_store: RegistrationStore | None = None

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))
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


@asynccontextmanager
async def lifespan(app_instance):
    global reg_store
    # Initialize registration store
    reg_store = create_store()
    await reg_store.setup()

    # Load persisted registrations
    registrations = await reg_store.list_all()
    for agent_name, data in registrations.items():
        route = Route(
            provider_name=data.get("provider_name", "api"),
            agent_name=agent_name,
            agent_url=data["url"],
            channels=data.get("channels", []),
            listen=data.get("listen", "all"),
            threads=data.get("threads", True),
            dm=data.get("dm", True),
        )
        router.add_route(route)

    # Load static routes file (if present)
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


class RegisterAgentRequest(BaseModel):
    """Agent self-registration request."""
    name: str
    url: str
    description: str = ""
    skills: list[dict] = []


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


# === Agent Self-Registration ===

@app.post("/register")
async def register_agent(request: RegisterAgentRequest):
    """Register an agent. Called by CLI after deployment or by agents on startup."""
    route = Route(
        provider_name="api",
        agent_name=request.name,
        agent_url=request.url,
        channels=[],
        listen="all",
        threads=True,
        dm=True,
    )
    router.add_route(route)

    # Persist to store
    if reg_store:
        await reg_store.save(request.name, {
            "url": request.url,
            "description": request.description,
            "skills": request.skills,
            "provider_name": "api",
        })

    return {"status": "registered", "agent": request.name, "url": request.url}


@app.delete("/unregister/{agent_name}")
async def unregister_agent(agent_name: str):
    """Deregister an agent."""
    router.remove_routes(agent_name)

    # Remove from store
    if reg_store:
        await reg_store.delete(agent_name)

    return {"status": "unregistered", "agent": agent_name}


# === Chat / A2A Proxy ===
# The gateway proxies requests to agents, acting as the unified entry point.

import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse


@app.get("/agents")
async def list_agents():
    """List all registered agents with status and Agent Cards."""
    agents = []
    async with httpx.AsyncClient(timeout=10) as client:
        for route in router.list_routes():
            entry = {
                "name": route.agent_name,
                "url": route.agent_url,
                "status": route.status,
                "registered_at": route.registered_at,
                "last_seen": route.last_seen,
            }
            if route.status == "online":
                try:
                    resp = await client.get(f"{route.agent_url}/.well-known/agent.json")
                    card = resp.json()
                    entry.update(card)
                except Exception:
                    pass
            agents.append(entry)
    return agents


@app.post("/invoke/{agent_name}")
async def proxy_invoke(agent_name: str, request: Request):
    """Proxy an invoke request to a specific agent."""
    route = _find_route(agent_name)
    if not route:
        return {"error": f"Agent '{agent_name}' not found"}

    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{route.agent_url}/invoke", json=body)
            router.mark_online(agent_name)
            return resp.json()
    except Exception as e:
        router.mark_offline(agent_name, str(e))
        return {"error": f"Agent '{agent_name}' is not responding: {e}"}


@app.post("/stream/{agent_name}")
async def proxy_stream(agent_name: str, request: Request):
    """Proxy a stream request to a specific agent via SSE."""
    route = _find_route(agent_name)
    if not route:
        return {"error": f"Agent '{agent_name}' not found"}

    body = await request.json()

    async def stream_proxy():
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", f"{route.agent_url}/stream", json=body) as resp:
                async for line in resp.aiter_lines():
                    if line:
                        yield line + "\n"

    return StreamingResponse(stream_proxy(), media_type="text/event-stream")


@app.post("/a2a/{agent_name}")
async def proxy_a2a(agent_name: str, request: Request):
    """Proxy an A2A JSON-RPC request to a specific agent."""
    route = _find_route(agent_name)
    if not route:
        return {"error": f"Agent '{agent_name}' not found"}

    body = await request.json()
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{route.agent_url}/a2a", json=body)
        return resp.json()


@app.get("/.well-known/agent.json")
async def gateway_agent_card():
    """Gateway Agent Card — lists all agents as skills."""
    skills = []
    for route in router.list_routes():
        skills.append({
            "id": route.agent_name,
            "name": route.agent_name,
            "url": route.agent_url,
        })
    return {
        "name": "agentstack-gateway",
        "description": "AgentStack gateway — unified entry point for all agents",
        "version": "0.1.0",
        "capabilities": {"streaming": True, "pushNotifications": False},
        "skills": skills,
    }


def _find_route(agent_name: str) -> Route | None:
    """Find a route by agent name."""
    for route in router.list_routes():
        if route.agent_name == agent_name:
            return route
    return None


# === Chat CLI Compatible Proxy ===
# The chat CLI expects {base_url}/invoke and {base_url}/stream.
# /proxy/{agent_name} acts as the base URL for a specific agent.

@app.get("/proxy/{agent_name}/health")
async def proxy_health(agent_name: str):
    """Proxy health check for a specific agent."""
    route = _find_route(agent_name)
    if not route:
        return {"error": f"Agent '{agent_name}' not found"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{route.agent_url}/health")
        return resp.json()


@app.post("/proxy/{agent_name}/invoke")
async def proxy_agent_invoke(agent_name: str, request: Request):
    """Proxy invoke for a specific agent (chat CLI compatible)."""
    route = _find_route(agent_name)
    if not route:
        return {"error": f"Agent '{agent_name}' not found"}
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{route.agent_url}/invoke", json=body)
            router.mark_online(agent_name)
            return resp.json()
    except Exception as e:
        router.mark_offline(agent_name, str(e))
        return {"error": f"Agent '{agent_name}' is not responding: {e}"}


@app.post("/proxy/{agent_name}/stream")
async def proxy_agent_stream(agent_name: str, request: Request):
    """Proxy stream for a specific agent (chat CLI compatible)."""
    route = _find_route(agent_name)
    if not route:
        return {"error": f"Agent '{agent_name}' not found"}
    body = await request.json()

    async def stream_proxy():
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", f"{route.agent_url}/stream", json=body) as resp:
                async for line in resp.aiter_lines():
                    if line:
                        yield line + "\n"

    return StreamingResponse(stream_proxy(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
