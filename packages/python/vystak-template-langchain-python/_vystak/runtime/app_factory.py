"""FastAPI app composition. Single entry point: build_agent_app(agent)."""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from _vystak.runtime.a2a.card import AgentCard
from _vystak.runtime.a2a.handler import A2AHandler
from _vystak.runtime.a2a.tasks import TaskManager
from _vystak.runtime.compaction.compactor import ThresholdCompactor
from _vystak.runtime.compaction.pruner import PreCallPruner
from _vystak.runtime.graph import build_graph
from _vystak.runtime.memory import MemoryManager
from _vystak.runtime.openai.chat import ChatCompletionsHandler
from _vystak.runtime.openai.responses import ResponsesHandler
from _vystak.runtime.prompt_callable import build_prompt
from _vystak.runtime.store import build_checkpointer
from _vystak.runtime.tools import load_user_tools


def build_agent_app(agent: Any) -> FastAPI:
    app = FastAPI()

    checkpointer = build_checkpointer(agent)
    user_tools = load_user_tools(agent, Path("tools"))
    # TODO(later-phase): wire build_workspace_tools(agent) once builtin
    # workspace tools land. For now agents only see user-defined tools.
    workspace_tools: list[Any] = []
    memory_mgr = MemoryManager(agent, store=None) if agent.memory else None

    pruner = PreCallPruner(agent.compaction) if agent.compaction else None
    compactor = (
        ThresholdCompactor(agent, store=None, summarizer=None)
        if agent.compaction
        else None
    )

    prompt = build_prompt(agent, memory_mgr=memory_mgr, compactor=compactor, pruner=pruner)
    graph = build_graph(
        agent,
        prompt=prompt,
        tools=user_tools + workspace_tools,
        checkpointer=checkpointer,
    )

    a2a_handler = A2AHandler(agent=agent, graph=graph, task_manager=TaskManager())
    responses_handler = ResponsesHandler(agent=agent, graph=graph, store=None)
    chat_handler = ChatCompletionsHandler(agent=agent, graph=graph)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/.well-known/agent.json")
    async def agent_card():
        return AgentCard(agent).render()

    @app.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [
                {"id": f"vystak/{agent.name}", "object": "model", "owned_by": "vystak"}
            ],
        }

    @app.post("/a2a")
    async def a2a(request: Request):
        payload = await request.json()
        if payload.get("method") == "tasks/sendSubscribe":
            async def gen():
                async for frame in a2a_handler.stream_dispatch(payload):
                    yield frame
            return StreamingResponse(gen(), media_type="text/event-stream")
        return JSONResponse(await a2a_handler.dispatch(payload))

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        body = await request.json()
        return await chat_handler.create(body)

    @app.post("/v1/responses")
    async def create_response(request: Request):
        body = await request.json()
        result = await responses_handler.create(body)
        if hasattr(result, "__aiter__"):
            return StreamingResponse(result, media_type="text/event-stream")
        return result

    @app.get("/v1/responses/{response_id}")
    async def get_response(response_id: str):
        try:
            return await responses_handler.get(response_id)
        except KeyError as e:
            raise HTTPException(
                status_code=404,
                detail=f"Response not found: {response_id}",
            ) from e

    return app
