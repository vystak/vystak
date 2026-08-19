"""FastAPI app composition. Single entry point: build_agent_app(agent)."""

import os
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

# Importing a2a_native applies a runtime monkey-patch to a2a-sdk 1.0.2's
# proto_utils that swaps `field.label` for `field.is_repeated` — without
# this every request crashes on validation. See a2a_native/_sdk_compat.py.
from _vystak.runtime.a2a_native.card import build_agent_card
from _vystak.runtime.a2a_native.executor import LangGraphExecutor
from _vystak.runtime.compaction.compactor import ThresholdCompactor
from _vystak.runtime.compaction.pruner import PreCallPruner
from _vystak.runtime.graph import build_graph, pick_model_name
from _vystak.runtime.heartbeat_sessions import (
    HeartbeatSessions,
    InMemoryHeartbeatSessions,
    SqliteHeartbeatSessions,
)
from _vystak.runtime.mcp import attach_mcp_servers
from _vystak.runtime.memory import MemoryManager
from _vystak.runtime.nats_bridge import maybe_build_bridge
from _vystak.runtime.openai.chat import ChatCompletionsHandler
from _vystak.runtime.openai.responses import ResponsesHandler
from _vystak.runtime.prompt_callable import build_prompt
from _vystak.runtime.schedules import build_schedule_tools
from _vystak.runtime.skills import build_skill_tools
from _vystak.runtime.store import (
    CheckpointObserver,
    ObservedSaver,
    _LazyCheckpointer,
    _LazyStore,
    build_checkpointer,
    build_memory_store,
)
from _vystak.runtime.subagents import build_subagent_tools
from _vystak.runtime.telemetry import instrument_app
from _vystak.runtime.tools import load_user_tools
from _vystak.runtime.workspace import build_workspace_tools


async def pick_model_for_turn(
    agent: Any,
    *,
    sessions,
    session_id: str,
    override: str | None,
) -> str:
    """Resolve the model name to use for this turn.

    Reads session-stored first; falls back to override; falls back to default.
    Does NOT persist — call persist_model_choice after the LLM call succeeds.
    """
    stored = await sessions.get_model(session_id)
    return pick_model_name(agent, session_stored=stored, override=override)


async def persist_model_choice(
    *,
    sessions,
    session_id: str,
    chosen: str,
) -> None:
    """Persist `chosen` only if the session does not already have a model."""
    stored = await sessions.get_model(session_id)
    if stored is None:
        await sessions.set_model(session_id, chosen)


def build_heartbeat_sessions(agent: Any) -> HeartbeatSessions:
    """Build a HeartbeatSessions store from the agent's sessions config.

    SQLite path: same DB file the langgraph checkpointer uses (sidecar table).
    Postgres / no sessions: in-memory (Postgres impl is a follow-up).
    """
    sessions_cfg = getattr(agent, "sessions", None)
    if sessions_cfg is None:
        return InMemoryHeartbeatSessions()
    engine = getattr(sessions_cfg, "engine", None)
    if engine == "sqlite":
        path = getattr(sessions_cfg, "path", None) or ":memory:"
        return SqliteHeartbeatSessions(path)
    # TODO(heartbeat): Postgres impl
    return InMemoryHeartbeatSessions()


def build_agent_app(agent: Any) -> FastAPI:
    checkpointer = build_checkpointer(agent)
    memory_store = build_memory_store(agent)
    user_tools = load_user_tools(agent, Path("tools"))
    subagent_tools = build_subagent_tools(agent)
    skill_tools = build_skill_tools(agent, Path("."))
    workspace_tools = build_workspace_tools(agent)
    schedule_tools = build_schedule_tools(agent)
    # If memory_store is a _LazyStore, the lifespan resolves it before any
    # request runs. Until then, MemoryManager is wired with `None` and its
    # recall/handle_tool_output are safe no-ops.
    memory_mgr_store = memory_store if not isinstance(memory_store, _LazyStore) else None
    memory_mgr = MemoryManager(agent, store=memory_mgr_store) if agent.memory else None

    pruner = PreCallPruner(agent.compaction) if agent.compaction else None
    compactor = ThresholdCompactor(agent, store=None, summarizer=None) if agent.compaction else None

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
        tools=user_tools + workspace_tools + subagent_tools + skill_tools + schedule_tools,
        checkpointer=initial_checkpointer,
    )

    # Build the A2A executor + DefaultRequestHandlerV2; both will be mounted
    # by `create_jsonrpc_routes` after FastAPI is created. The executor holds
    # a graph reference that is swapped out during lifespan startup if the
    # checkpointer is lazy.
    a2a_executor = LangGraphExecutor(graph=graph, memory_mgr=memory_mgr)
    # Public URL the agent card advertises. Other agents reach this URL via
    # the SDK client, so it MUST be the externally-resolvable hostname (Docker
    # DNS / Azure FQDN / etc.) — NOT localhost. Provider sets it via env. We
    # fall back to localhost only when running locally (tests, dev).
    port_env = os.environ.get("PORT")
    listen_port = int(port_env) if port_env else (getattr(agent, "port", None) or 8000)
    public_url = os.environ.get("VYSTAK_AGENT_PUBLIC_URL")
    if not public_url:
        public_url = f"http://localhost:{listen_port}"
    a2a_card = build_agent_card(agent, base_url=public_url)
    a2a_handler = DefaultRequestHandlerV2(
        agent_executor=a2a_executor,
        task_store=InMemoryTaskStore(),
        agent_card=a2a_card,
    )

    responses_handler = ResponsesHandler(agent=agent, graph=graph, store=None)
    chat_handler = ChatCompletionsHandler(agent=agent, graph=graph)

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        async with AsyncExitStack() as stack:
            # MCP servers spawn/connect async, so tools attach at startup
            # rather than in the (sync) factory. Any attached tools force a
            # graph rebuild, same as the lazy-checkpointer path below.
            mcp_tools = await attach_mcp_servers(agent)
            app_.state.mcp_tools = mcp_tools

            if is_lazy or mcp_tools:
                resolved = (
                    await stack.enter_async_context(checkpointer.context_manager())
                    if is_lazy
                    else checkpointer
                )
                observer = CheckpointObserver()
                app_.state.checkpoint_observer = observer
                resolved = ObservedSaver(resolved, observer)
                new_graph = build_graph(
                    agent,
                    prompt=prompt,
                    tools=user_tools + workspace_tools + subagent_tools + skill_tools
                    + schedule_tools + mcp_tools,
                    checkpointer=resolved,
                )
                a2a_executor._graph = new_graph
                responses_handler.graph = new_graph
                responses_handler._observer = observer
                chat_handler.graph = new_graph
                app_.state.graph = new_graph
            else:
                app_.state.graph = graph

            if isinstance(memory_store, _LazyStore):
                resolved_store = await stack.enter_async_context(memory_store.context_manager())
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

            # NATS↔HTTP bridge — only starts when VYSTAK_TRANSPORT_TYPE=nats.
            # On HTTP transport this is a clean no-op (returns None).
            bridge = maybe_build_bridge(agent, listen_port)
            if bridge is not None:
                await bridge.start()

                async def _stop_bridge() -> None:
                    await bridge.stop()

                stack.push_async_callback(_stop_bridge)

            yield

    app = FastAPI(lifespan=lifespan)
    app.state.heartbeat_sessions = build_heartbeat_sessions(agent)

    # OTel auto-instrumentation. Reads OTEL_* env vars set by the
    # Docker provider when Platform.telemetry is enabled. No-op when
    # unset, so HTTP-only deployments without a collector pay nothing.
    instrument_app(app, service_name=f"vystak-{agent.name}")

    # Mount SDK-supplied A2A routes. The JSON-RPC dispatcher accepts both
    # the modern proto-mapped methods (`SendMessage`, `GetTask`, ...) and,
    # with v0.3 compat enabled, the legacy spec strings `message/send`,
    # `message/stream`, `tasks/get`, `tasks/cancel` which are what
    # vystak-channel-runtime + vystak-chat will speak.
    for route in create_jsonrpc_routes(a2a_handler, rpc_url="/a2a", enable_v0_3_compat=True):
        app.routes.append(route)
    # Keep the dot-form path for back-compat with chat client + channel runtime.
    for route in create_agent_card_routes(a2a_card, card_url="/.well-known/agent.json"):
        app.routes.append(route)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [{"id": f"vystak/{agent.name}", "object": "model", "owned_by": "vystak"}],
        }

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
