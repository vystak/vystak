"""Gateway management API."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from agentstack_gateway.router import Route, Router

router = Router()
providers: dict = {}

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


# === Chat / A2A Proxy ===
# The gateway proxies requests to agents, acting as the unified entry point.

import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse


@app.get("/agents")
async def list_agents():
    """List all registered agents with their Agent Cards."""
    agents = []
    async with httpx.AsyncClient(timeout=10) as client:
        for route in router.list_routes():
            try:
                resp = await client.get(f"{route.agent_url}/.well-known/agent.json")
                card = resp.json()
                card["_route"] = {"agent_name": route.agent_name, "agent_url": route.agent_url}
                agents.append(card)
            except Exception:
                agents.append({
                    "name": route.agent_name,
                    "url": route.agent_url,
                    "status": "unreachable",
                })
    return agents


@app.post("/invoke/{agent_name}")
async def proxy_invoke(agent_name: str, request: Request):
    """Proxy an invoke request to a specific agent."""
    route = _find_route(agent_name)
    if not route:
        return {"error": f"Agent '{agent_name}' not found"}

    body = await request.json()
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{route.agent_url}/invoke", json=body)
        return resp.json()


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
