"""Gateway management API."""

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from agentstack.schema.openai import (
    ChatCompletionRequest, ChatCompletionResponse, ChatCompletionChunk,
    ChatMessage, Choice, ChunkChoice, ChunkDelta, CompletionUsage,
    CreateThreadRequest, ErrorDetail, ErrorResponse, ModelList, ModelObject, Thread,
)
from agentstack_gateway.router import Route, Router
from agentstack_gateway.store import RegistrationStore, ThreadStore, create_store

router = Router()
providers: dict = {}
reg_store: RegistrationStore | None = None
thread_store = ThreadStore()

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


# === Agent Listing & A2A Proxy ===

@app.get("/agents")
async def list_agents():
    """List all registered agents with status and Agent Cards."""
    agents = []
    async with httpx.AsyncClient(timeout=10) as http_client:
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
                    resp = await http_client.get(f"{route.agent_url}/.well-known/agent.json")
                    card = resp.json()
                    entry.update(card)
                except Exception:
                    pass
            agents.append(entry)
    return agents


@app.post("/a2a/{agent_name}")
async def proxy_a2a(agent_name: str, request: Request):
    """Proxy an A2A JSON-RPC request to a specific agent."""
    route = _find_route(agent_name)
    if not route:
        return {"error": f"Agent '{agent_name}' not found"}

    body = await request.json()
    async with httpx.AsyncClient(timeout=120) as http_client:
        resp = await http_client.post(f"{route.agent_url}/a2a", json=body)
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


# === OpenAI-Compatible v1 Endpoints ===

@app.get("/v1/models")
async def v1_models():
    """List all registered agents as OpenAI-compatible model entries."""
    models = []
    for route in router.list_routes():
        models.append(ModelObject(
            id=f"agentstack/{route.agent_name}",
            created=int(time.time()),
            owned_by="agentstack",
        ))
    return ModelList(object="list", data=models)


@app.post("/v1/chat/completions")
async def v1_chat_completions(request: ChatCompletionRequest):
    """Route chat completions to agents via A2A."""
    # Parse model field — strip agentstack/ prefix
    model = request.model
    agent_name = model.removeprefix("agentstack/")

    route = _find_route(agent_name)
    if not route:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error=ErrorDetail(
                    message=f"Model '{model}' not found",
                    type="invalid_request_error",
                    code="model_not_found",
                )
            ).model_dump(),
        )

    # Build the user message from the last message
    last_msg = ""
    for msg in reversed(request.messages):
        if msg.role == "user" and msg.content:
            last_msg = msg.content
            break

    session_id = request.session_id or str(uuid.uuid4())

    if request.stream:
        return await _stream_chat_completion(route, agent_name, model, session_id, last_msg, request)
    else:
        return await _non_stream_chat_completion(route, agent_name, model, session_id, last_msg, request)


async def _non_stream_chat_completion(route, agent_name, model, session_id, last_msg, request):
    """Send A2A tasks/send and return ChatCompletionResponse."""
    a2a_request = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "id": 1,
        "params": {
            "id": session_id,
            "sessionId": session_id,
            "message": {"role": "user", "parts": [{"text": last_msg}]},
            "metadata": {
                "trace_id": str(uuid.uuid4()),
                "user_id": request.user_id or "",
                "project_id": request.project_id or "",
            },
        },
    }

    async with httpx.AsyncClient(timeout=120) as http_client:
        resp = await http_client.post(f"{route.agent_url}/a2a", json=a2a_request)
        a2a_resp = resp.json()

    # Extract response text from A2A result
    response_text = ""
    result = a2a_resp.get("result", {})
    status = result.get("status", {})
    status_message = status.get("message", {})
    parts = status_message.get("parts", [])
    if parts:
        response_text = parts[0].get("text", "")

    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
        created=int(time.time()),
        model=model,
        choices=[Choice(
            index=0,
            message=ChatMessage(role="assistant", content=response_text),
            finish_reason="stop",
        )],
        usage=CompletionUsage(),
    )


async def _stream_chat_completion(route, agent_name, model, session_id, last_msg, request):
    """Send A2A tasks/sendSubscribe and translate SSE to ChatCompletionChunk stream."""
    a2a_request = {
        "jsonrpc": "2.0",
        "method": "tasks/sendSubscribe",
        "id": 1,
        "params": {
            "id": session_id,
            "sessionId": session_id,
            "message": {"role": "user", "parts": [{"text": last_msg}]},
            "metadata": {
                "trace_id": str(uuid.uuid4()),
                "user_id": request.user_id or "",
                "project_id": request.project_id or "",
            },
        },
    }

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    async def stream_generator():
        async with httpx.AsyncClient(timeout=120) as http_client:
            async with http_client.stream("POST", f"{route.agent_url}/a2a", json=a2a_request) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    result = event.get("result", {})

                    # Check for artifact with text content
                    artifact = result.get("artifact", {})
                    if artifact:
                        parts = artifact.get("parts", [])
                        for part in parts:
                            text = part.get("text", "")
                            if text:
                                chunk = ChatCompletionChunk(
                                    id=completion_id,
                                    created=created,
                                    model=model,
                                    choices=[ChunkChoice(
                                        index=0,
                                        delta=ChunkDelta(content=text),
                                    )],
                                )
                                yield f"data: {chunk.model_dump_json()}\n\n"

                    # Check for final status
                    if result.get("final"):
                        # Send finish chunk
                        finish_chunk = ChatCompletionChunk(
                            id=completion_id,
                            created=created,
                            model=model,
                            choices=[ChunkChoice(
                                index=0,
                                delta=ChunkDelta(),
                                finish_reason="stop",
                            )],
                        )
                        yield f"data: {finish_chunk.model_dump_json()}\n\n"
                        yield "data: [DONE]\n\n"
                        return

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@app.post("/v1/threads")
async def v1_create_thread(request: CreateThreadRequest):
    """Create a thread with optional model binding."""
    thread_id = f"thread_{uuid.uuid4().hex}"

    # Validate model if provided
    if request.model:
        agent_name = request.model.removeprefix("agentstack/")
        route = _find_route(agent_name)
        if not route:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error=ErrorDetail(
                        message=f"Model '{request.model}' not found",
                        type="invalid_request_error",
                        code="model_not_found",
                    )
                ).model_dump(),
            )

    thread = thread_store.create(
        thread_id=thread_id,
        model=request.model,
        metadata=request.metadata,
    )
    return thread


@app.get("/v1/threads/{thread_id}/messages")
async def v1_list_thread_messages(thread_id: str):
    """List messages for a thread — proxies to bound agent."""
    thread = thread_store.get(thread_id)
    if not thread:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error=ErrorDetail(
                    message=f"Thread '{thread_id}' not found",
                    type="invalid_request_error",
                    code="thread_not_found",
                )
            ).model_dump(),
        )

    model = thread.get("model")
    if not model:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error=ErrorDetail(
                    message="Thread has no bound model",
                    type="invalid_request_error",
                    code="no_model_bound",
                )
            ).model_dump(),
        )

    agent_name = model.removeprefix("agentstack/")
    route = _find_route(agent_name)
    if not route:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error=ErrorDetail(
                    message=f"Model '{model}' not found",
                    type="invalid_request_error",
                    code="model_not_found",
                )
            ).model_dump(),
        )

    # Proxy to agent's thread messages endpoint
    async with httpx.AsyncClient(timeout=30) as http_client:
        resp = await http_client.get(f"{route.agent_url}/v1/threads/{thread_id}/messages")
        return resp.json()


@app.post("/v1/threads/{thread_id}/runs")
async def v1_create_thread_run(thread_id: str, request: Request):
    """Create a run on a thread — proxies to bound agent with deferred model binding."""
    thread = thread_store.get(thread_id)
    if not thread:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error=ErrorDetail(
                    message=f"Thread '{thread_id}' not found",
                    type="invalid_request_error",
                    code="thread_not_found",
                )
            ).model_dump(),
        )

    body = await request.json()

    # Deferred model binding: if thread has no model, bind from run request
    model = thread.get("model") or body.get("model")
    if model and not thread.get("model"):
        thread_store.bind_model(thread_id, model)

    if not model:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error=ErrorDetail(
                    message="No model specified in thread or run request",
                    type="invalid_request_error",
                    code="no_model_bound",
                )
            ).model_dump(),
        )

    agent_name = model.removeprefix("agentstack/")
    route = _find_route(agent_name)
    if not route:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error=ErrorDetail(
                    message=f"Model '{model}' not found",
                    type="invalid_request_error",
                    code="model_not_found",
                )
            ).model_dump(),
        )

    # Proxy to agent
    async with httpx.AsyncClient(timeout=120) as http_client:
        resp = await http_client.post(
            f"{route.agent_url}/v1/threads/{thread_id}/runs",
            json=body,
        )
        return resp.json()


def _find_route(agent_name: str) -> Route | None:
    """Find a route by agent name."""
    for route in router.list_routes():
        if route.agent_name == agent_name:
            return route
    return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
