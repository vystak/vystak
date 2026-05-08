"""FastAPI app composition. Single entry point: build_agent_app(agent)."""

from contextlib import AsyncExitStack, asynccontextmanager
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
from _vystak.runtime.store import (
    _LazyCheckpointer,
    _LazyStore,
    build_checkpointer,
    build_memory_store,
)
from _vystak.runtime.subagents import build_subagent_tools
from _vystak.runtime.tools import load_user_tools


def build_agent_app(agent: Any) -> FastAPI:
    checkpointer = build_checkpointer(agent)
    memory_store = build_memory_store(agent)
    user_tools = load_user_tools(agent, Path("tools"))
    subagent_tools = build_subagent_tools(agent)
    # TODO(later-phase): wire build_workspace_tools(agent) once builtin
    # workspace tools land. For now agents only see user-defined tools.
    workspace_tools: list[Any] = []
    # If memory_store is a _LazyStore, the lifespan resolves it before any
    # request runs. Until then, MemoryManager is wired with `None` and its
    # recall/handle_tool_output are safe no-ops.
    memory_mgr_store = memory_store if not isinstance(memory_store, _LazyStore) else None
    memory_mgr = MemoryManager(agent, store=memory_mgr_store) if agent.memory else None

    pruner = PreCallPruner(agent.compaction) if agent.compaction else None
    compactor = (
        ThresholdCompactor(agent, store=None, summarizer=None)
        if agent.compaction
        else None
    )

    prompt = build_prompt(agent, memory_mgr=memory_mgr, compactor=compactor, pruner=pruner)

    # Lazy savers (sqlite/postgres) need an async resolution step. LangGraph's
    # compile() rejects them as `BaseCheckpointSaver`, so we build the graph
    # with checkpointer=None initially and swap in the resolved saver during
    # lifespan startup.
    is_lazy = isinstance(checkpointer, _LazyCheckpointer)
    initial_checkpointer = None if is_lazy else checkpointer

    graph = build_graph(
        agent,
        prompt=prompt,
        tools=user_tools + workspace_tools + subagent_tools,
        checkpointer=initial_checkpointer,
    )

    a2a_handler = A2AHandler(agent=agent, graph=graph, task_manager=TaskManager())
    responses_handler = ResponsesHandler(agent=agent, graph=graph, store=None)
    chat_handler = ChatCompletionsHandler(agent=agent, graph=graph)

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        async with AsyncExitStack() as stack:
            if is_lazy:
                resolved = await stack.enter_async_context(checkpointer.context_manager())
                new_graph = build_graph(
                    agent,
                    prompt=prompt,
                    tools=user_tools + workspace_tools + subagent_tools,
                    checkpointer=resolved,
                )
                a2a_handler.graph = new_graph
                responses_handler.graph = new_graph
                chat_handler.graph = new_graph
                app_.state.graph = new_graph
            else:
                app_.state.graph = graph

            if isinstance(memory_store, _LazyStore):
                resolved_store = await stack.enter_async_context(
                    memory_store.context_manager()
                )
                # Postgres-backed stores create their schema on first use; SQLite
                # / in-memory stores ignore setup. Always call when present.
                setup_fn = getattr(resolved_store, "setup", None)
                if setup_fn is not None:
                    import inspect

                    if inspect.iscoroutinefunction(setup_fn):
                        await setup_fn()
                    else:
                        setup_fn()
                if memory_mgr is not None:
                    memory_mgr.store = resolved_store

            yield

    app = FastAPI(lifespan=lifespan)

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
