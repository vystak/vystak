"""Gateway management API."""

import asyncio
import os

from fastapi import FastAPI
from pydantic import BaseModel

from agentstack_gateway.router import Route, Router

app = FastAPI(title="agentstack-gateway")
router = Router()
providers: dict = {}

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
