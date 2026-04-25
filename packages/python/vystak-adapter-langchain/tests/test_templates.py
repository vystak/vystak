import ast as python_ast

import pytest
from vystak.schema.agent import Agent
from vystak.schema.common import McpTransport
from vystak.schema.mcp import McpServer
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.resource import SessionStore
from vystak.schema.service import Postgres, Sqlite
from vystak.schema.skill import Skill
from vystak_adapter_langchain.templates import (
    generate_agent_py,
    generate_requirements_txt,
    generate_server_py,
)


@pytest.fixture()
def anthropic_provider():
    return Provider(name="anthropic", type="anthropic")


@pytest.fixture()
def openai_provider():
    return Provider(name="openai", type="openai")


@pytest.fixture()
def anthropic_agent(anthropic_provider):
    return Agent(
        name="test-bot",
        model=Model(
            name="claude",
            provider=anthropic_provider,
            model_name="claude-sonnet-4-20250514",
            parameters={"temperature": 0.7},
        ),
        skills=[
            Skill(
                name="greeting",
                tools=["say_hello", "say_goodbye"],
                prompt="Always be polite and helpful.",
            ),
            Skill(
                name="math",
                tools=["calculate"],
                prompt="Show your work step by step.",
            ),
        ],
    )


@pytest.fixture()
def openai_agent(openai_provider):
    return Agent(
        name="gpt-bot",
        model=Model(
            name="gpt4",
            provider=openai_provider,
            model_name="gpt-4o",
        ),
    )


class TestGenerateAgentPy:
    def test_parseable(self, anthropic_agent):
        code = generate_agent_py(anthropic_agent)
        python_ast.parse(code)

    def test_anthropic_import(self, anthropic_agent):
        code = generate_agent_py(anthropic_agent)
        assert "from langchain_anthropic import ChatAnthropic" in code

    def test_openai_import(self, openai_agent):
        code = generate_agent_py(openai_agent)
        assert "from langchain_openai import ChatOpenAI" in code

    def test_model_name_injected(self, anthropic_agent):
        code = generate_agent_py(anthropic_agent)
        assert "claude-sonnet-4-20250514" in code

    def test_temperature_injected(self, anthropic_agent):
        code = generate_agent_py(anthropic_agent)
        assert "temperature" in code
        assert "0.7" in code

    def test_tools_generated(self, anthropic_agent):
        code = generate_agent_py(anthropic_agent)
        assert "def say_hello(" in code
        assert "def say_goodbye(" in code
        assert "def calculate(" in code
        assert "@tool" in code

    def test_system_prompt_included(self, anthropic_agent):
        code = generate_agent_py(anthropic_agent)
        assert "Always be polite and helpful." in code
        assert "Show your work step by step." in code

    def test_create_react_agent(self, anthropic_agent):
        code = generate_agent_py(anthropic_agent)
        assert "create_react_agent" in code

    def test_no_tools_still_valid(self, openai_agent):
        code = generate_agent_py(openai_agent)
        python_ast.parse(code)


class TestGenerateServerPy:
    def test_parseable(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        python_ast.parse(code)

    def test_has_health(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/health"' in code

    def test_has_v1_models(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/v1/models"' in code
        assert "vystak/test-bot" in code

    def test_has_v1_chat_completions(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/v1/chat/completions"' in code

    def test_chat_completions_stateless(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "for msg in request.messages" in code

    def test_has_v1_responses(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/v1/responses"' in code
        assert "CreateResponseRequest" in code

    def test_has_v1_responses_get(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/v1/responses/{response_id}"' in code

    def test_responses_streaming(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "response.created" in code
        assert "response.output_text.delta" in code
        assert "response.completed" in code
        assert "response.function_call_arguments.delta" in code

    def test_responses_background(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "background" in code
        assert "in_progress" in code

    def test_no_threads_endpoints(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/v1/threads"' not in code
        assert "CreateThreadRequest" not in code

    def test_no_invoke_endpoint(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/invoke"' not in code

    def test_no_stream_endpoint(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert '"/stream"' not in code

    def test_imports_openai_types(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "from openai_types import" in code
        assert "CreateResponseRequest" in code
        assert "ResponseObject" in code

    def test_openai_error_format(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "ErrorResponse" in code

    def test_agent_name_injected(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "test-bot" in code

    def test_uvicorn(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "uvicorn" in code

    def test_responses_handler_class_emitted(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "class ResponsesHandler:" in code
        assert "async def create(" in code
        assert "async def create_stream(" in code
        assert "async def get(" in code

    def test_responses_handler_instantiated(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "_responses_handler = ResponsesHandler(" in code
        # FastAPI adapter route delegates to handler, not inline logic.
        assert "_responses_handler.create_stream(" in code
        assert "_responses_handler.create(" in code
        assert "_responses_handler.get(" in code


class TestGenerateResponsesHandlerCode:
    """Direct tests for the ResponsesHandler code-gen function."""

    def test_generate_responses_handler_code_contains_class(self, anthropic_agent):
        from vystak_adapter_langchain.responses import generate_responses_handler_code

        code = generate_responses_handler_code(anthropic_agent)
        assert "class ResponsesHandler:" in code
        assert "async def create(" in code
        assert "async def create_stream(" in code
        assert "async def get(" in code

    def test_generate_responses_handler_code_preserves_wire_events(self, anthropic_agent):
        """Streaming path must still emit the same ``response.*`` event types."""
        from vystak_adapter_langchain.responses import generate_responses_handler_code

        code = generate_responses_handler_code(anthropic_agent)
        assert "response.created" in code
        assert "response.output_item.added" in code
        assert "response.content_part.added" in code
        assert "response.output_text.delta" in code
        assert "response.output_text.done" in code
        assert "response.completed" in code
        assert "response.function_call_arguments.delta" in code
        assert "response.function_call_arguments.done" in code


class TestGenerateRequirementsTxt:
    def test_anthropic_requirements(self, anthropic_agent):
        reqs = generate_requirements_txt(anthropic_agent)
        assert "langchain-anthropic" in reqs
        assert "langchain-core" in reqs
        assert "langgraph" in reqs
        assert "fastapi" in reqs
        assert "uvicorn" in reqs
        assert "sse-starlette" in reqs

    def test_openai_requirements(self, openai_agent):
        reqs = generate_requirements_txt(openai_agent)
        assert "langchain-openai" in reqs
        assert "langchain-anthropic" not in reqs

    def test_common_deps_present(self, anthropic_agent):
        reqs = generate_requirements_txt(anthropic_agent)
        lines = reqs.strip().split("\n")
        assert len(lines) >= 6

    def test_vystak_not_in_requirements(self, anthropic_agent):
        """vystak is bundled as source by the Docker provider, not installed
        from PyPI. It must NOT appear in generated requirements.txt."""
        reqs = generate_requirements_txt(anthropic_agent)
        assert "vystak>=" not in reqs
        assert "vystak-transport-http>=" not in reqs


@pytest.fixture()
def postgres_agent(anthropic_provider):
    docker_provider = Provider(name="docker", type="docker")
    return Agent(
        name="pg-bot",
        model=Model(
            name="claude", provider=anthropic_provider, model_name="claude-sonnet-4-20250514"
        ),
        resources=[SessionStore(name="sessions", provider=docker_provider, engine="postgres")],
    )


@pytest.fixture()
def sqlite_agent(anthropic_provider):
    docker_provider = Provider(name="docker", type="docker")
    return Agent(
        name="sqlite-bot",
        model=Model(
            name="claude", provider=anthropic_provider, model_name="claude-sonnet-4-20250514"
        ),
        resources=[SessionStore(name="sessions", provider=docker_provider, engine="sqlite")],
    )


class TestCheckpointerSelection:
    def test_no_resource_uses_memory(self, openai_agent):
        code = generate_agent_py(openai_agent)
        assert "MemorySaver" in code
        assert "PostgresSaver" not in code
        assert "SqliteSaver" not in code

    def test_postgres_checkpointer(self, postgres_agent):
        code = generate_agent_py(postgres_agent)
        assert "PostgresSaver" in code
        assert "SESSION_STORE_URL" in code
        assert "MemorySaver" not in code
        python_ast.parse(code)

    def test_sqlite_checkpointer(self, sqlite_agent):
        code = generate_agent_py(sqlite_agent)
        assert "SqliteSaver" in code
        assert "/data/" in code
        assert "MemorySaver" not in code
        python_ast.parse(code)

    def test_postgres_requirements(self, postgres_agent):
        reqs = generate_requirements_txt(postgres_agent)
        assert "langgraph-checkpoint-postgres" in reqs

    def test_sqlite_requirements(self, sqlite_agent):
        reqs = generate_requirements_txt(sqlite_agent)
        assert "langgraph-checkpoint-sqlite" in reqs

    def test_no_resource_no_extra_requirements(self, openai_agent):
        reqs = generate_requirements_txt(openai_agent)
        assert "langgraph-checkpoint-postgres" not in reqs
        assert "langgraph-checkpoint-sqlite" not in reqs


class TestMemoryGeneration:
    def test_memory_tools_generated_with_resource(self, postgres_agent):
        code = generate_agent_py(postgres_agent)
        assert "save_memory" in code
        assert "forget_memory" in code
        assert "__SAVE_MEMORY__" in code

    def test_no_memory_tools_without_resource(self, openai_agent):
        code = generate_agent_py(openai_agent)
        assert "save_memory" not in code
        assert "forget_memory" not in code

    def test_prompt_callable_with_resource(self, postgres_agent):
        """Persistent agents use a prompt callable for ephemeral memory recall."""
        code = generate_agent_py(postgres_agent)
        assert "_make_prompt" in code
        assert "prompt_fn" in code
        assert "asearch" in code

    def test_memory_system_prompt_with_resource(self, postgres_agent):
        code = generate_agent_py(postgres_agent)
        assert "long-term memory" in code.lower()

    def test_no_memory_prompt_without_resource(self, openai_agent):
        code = generate_agent_py(openai_agent)
        assert "long-term memory" not in code.lower()

    def test_postgres_store_import(self, postgres_agent):
        code = generate_agent_py(postgres_agent)
        assert "AsyncPostgresStore" in code

    def test_sqlite_store_import(self, sqlite_agent):
        code = generate_agent_py(sqlite_agent)
        assert "AsyncSqliteStore" in code

    def test_create_agent_accepts_store(self, postgres_agent):
        code = generate_agent_py(postgres_agent)
        assert "store=None" in code or "store=" in code

    def test_agent_py_with_memory_parseable(self, postgres_agent):
        code = generate_agent_py(postgres_agent)
        python_ast.parse(code)

    def test_agent_py_sqlite_with_memory_parseable(self, sqlite_agent):
        code = generate_agent_py(sqlite_agent)
        python_ast.parse(code)


class TestServerMemory:
    def test_server_accepts_user_id(self, postgres_agent):
        code = generate_server_py(postgres_agent)
        assert "user_id" in code

    def test_server_accepts_project_id(self, postgres_agent):
        code = generate_server_py(postgres_agent)
        assert "project_id" in code

    def test_server_no_recall_memories(self, postgres_agent):
        """Memory recall moved to agent's prompt callable — not in server."""
        code = generate_server_py(postgres_agent)
        assert "recall_memories" not in code

    def test_server_handle_memory_actions(self, postgres_agent):
        code = generate_server_py(postgres_agent)
        assert "handle_memory_actions" in code

    def test_server_no_memory_without_resource(self, openai_agent):
        code = generate_server_py(openai_agent)
        assert "recall_memories" not in code

    def test_server_with_memory_parseable(self, postgres_agent):
        code = generate_server_py(postgres_agent)
        python_ast.parse(code)

    def test_server_sqlite_with_memory_parseable(self, sqlite_agent):
        code = generate_server_py(sqlite_agent)
        python_ast.parse(code)

    def test_sqlite_requirements_include_aiosqlite(self, sqlite_agent):
        reqs = generate_requirements_txt(sqlite_agent)
        assert "aiosqlite" in reqs


class TestA2AInServer:
    def test_server_has_agent_card_endpoint(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "/.well-known/agent.json" in code

    def test_server_has_a2a_endpoint(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "/a2a" in code

    def test_server_has_task_manager(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "TaskManager" in code

    def test_server_has_jsonrpc_methods(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "tasks/send" in code
        assert "tasks/get" in code
        assert "tasks/cancel" in code
        assert "tasks/sendSubscribe" in code

    def test_server_a2a_parseable(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        python_ast.parse(code)

    def test_server_a2a_with_resources_parseable(self, postgres_agent):
        code = generate_server_py(postgres_agent)
        python_ast.parse(code)

    def test_server_a2a_sqlite_parseable(self, sqlite_agent):
        code = generate_server_py(sqlite_agent)
        python_ast.parse(code)


@pytest.fixture()
def mcp_agent(anthropic_provider):
    return Agent(
        name="mcp-bot",
        model=Model(
            name="claude", provider=anthropic_provider, model_name="claude-sonnet-4-20250514"
        ),
        mcp_servers=[
            McpServer(
                name="filesystem",
                transport=McpTransport.STDIO,
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", "/data"],
            ),
            McpServer(
                name="remote",
                transport=McpTransport.STREAMABLE_HTTP,
                url="http://example.com/mcp",
                headers={"Authorization": "Bearer token"},
            ),
        ],
    )


@pytest.fixture()
def mcp_agent_with_resources(anthropic_provider):
    docker_provider = Provider(name="docker", type="docker")
    return Agent(
        name="mcp-pg-bot",
        model=Model(
            name="claude", provider=anthropic_provider, model_name="claude-sonnet-4-20250514"
        ),
        mcp_servers=[
            McpServer(
                name="filesystem",
                transport=McpTransport.STDIO,
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem"],
            ),
        ],
        resources=[SessionStore(name="sessions", provider=docker_provider, engine="postgres")],
    )


class TestSessionsField:
    """Tests that the adapter reads from agent.sessions (new API)."""

    def test_postgres_from_sessions_field(self, anthropic_provider):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot",
            model=Model(
                name="claude", provider=anthropic_provider, model_name="claude-sonnet-4-20250514"
            ),
            sessions=Postgres(provider=docker),
        )
        code = generate_server_py(agent)
        assert "PostgresSaver" in code

    def test_sqlite_from_sessions_field(self, anthropic_provider):
        docker = Provider(name="docker", type="docker")
        agent = Agent(
            name="bot",
            model=Model(
                name="claude", provider=anthropic_provider, model_name="claude-sonnet-4-20250514"
            ),
            sessions=Sqlite(provider=docker),
        )
        code = generate_server_py(agent)
        assert "SqliteSaver" in code or "store" in code.lower()

    def test_bring_your_own_sessions(self, anthropic_provider):
        agent = Agent(
            name="bot",
            model=Model(
                name="claude", provider=anthropic_provider, model_name="claude-sonnet-4-20250514"
            ),
            sessions=Postgres(connection_string_env="DATABASE_URL"),
        )
        code = generate_server_py(agent)
        assert "PostgresSaver" in code


class TestMCPIntegration:
    def test_mcp_config_generated(self, mcp_agent):
        code = generate_agent_py(mcp_agent)
        assert "MCP_SERVERS" in code
        assert '"filesystem"' in code
        assert '"remote"' in code

    def test_mcp_transport_mapping(self, mcp_agent):
        code = generate_agent_py(mcp_agent)
        assert '"transport": "stdio"' in code
        assert '"transport": "http"' in code

    def test_mcp_import(self, mcp_agent):
        code = generate_agent_py(mcp_agent)
        assert "MultiServerMCPClient" in code

    def test_mcp_tools_in_create_agent(self, mcp_agent):
        code = generate_agent_py(mcp_agent)
        assert "mcp_tools" in code

    def test_mcp_lifespan_in_server(self, mcp_agent):
        code = generate_server_py(mcp_agent)
        assert "MultiServerMCPClient" in code
        assert "mcp_tools" in code

    def test_mcp_requirements(self, mcp_agent):
        reqs = generate_requirements_txt(mcp_agent)
        assert "langchain-mcp-adapters" in reqs

    def test_no_mcp_unchanged(self, openai_agent):
        code = generate_agent_py(openai_agent)
        assert "MCP_SERVERS" not in code
        assert "MultiServerMCPClient" not in code

    def test_mcp_agent_parseable(self, mcp_agent):
        code = generate_agent_py(mcp_agent)
        python_ast.parse(code)

    def test_mcp_server_parseable(self, mcp_agent):
        code = generate_server_py(mcp_agent)
        python_ast.parse(code)

    def test_mcp_with_resources_agent_parseable(self, mcp_agent_with_resources):
        code = generate_agent_py(mcp_agent_with_resources)
        python_ast.parse(code)
        assert "MCP_SERVERS" in code
        assert "mcp_tools" in code

    def test_mcp_with_resources_server_parseable(self, mcp_agent_with_resources):
        code = generate_server_py(mcp_agent_with_resources)
        python_ast.parse(code)
        assert "MultiServerMCPClient" in code


def _basic_agent():
    return Agent(
        name="basic",
        model=Model(
            name="m",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-3-haiku-20240307",
        ),
    )


class TestTransportBootstrap:
    def test_generated_server_parses_as_python(self):
        source = generate_server_py(_basic_agent())
        python_ast.parse(source)

    def test_generated_server_has_transport_bootstrap(self):
        source = generate_server_py(_basic_agent())
        assert "VYSTAK_TRANSPORT_TYPE" in source
        assert "VYSTAK_ROUTES_JSON" in source
        assert "AGENT_CANONICAL_NAME" in source
        assert "_transport.serve(" in source

    def test_generated_server_bootstrap_has_nats_branch(self):
        """Emitted server source must contain the NATS branch so
        NATS-deployment containers can boot without regeneration."""
        source = generate_server_py(_basic_agent())
        assert "VYSTAK_NATS_URL" in source
        assert "VYSTAK_NATS_SUBJECT_PREFIX" in source
        assert "NatsTransport" in source

    def test_generated_server_emits_server_dispatcher_class(self):
        """Generated server defines a ServerDispatcher class fanning A2A vs
        Responses methods to the respective handlers."""
        source = generate_server_py(_basic_agent())
        assert "class ServerDispatcher:" in source
        # All five ServerDispatcherProtocol methods must be present.
        assert "async def dispatch_a2a(" in source
        assert "def dispatch_a2a_stream(" in source
        assert "async def dispatch_responses_create(" in source
        assert "def dispatch_responses_create_stream(" in source
        assert "async def dispatch_responses_get(" in source

    def test_generated_server_instantiates_dispatcher_and_passes_to_serve(self):
        """Dispatcher is constructed from the existing handlers and passed to
        the transport listener."""
        source = generate_server_py(_basic_agent())
        assert "_server_dispatcher = ServerDispatcher(" in source
        assert "a2a_handler=_a2a_handler" in source
        assert "responses_handler=_responses_handler" in source
        assert "handler=_server_dispatcher" in source

    def test_generated_server_dispatcher_streams_are_sync_def(self):
        """Stream methods must return the underlying async iterator directly
        (i.e. be regular ``def``, not ``async def``)."""
        source = generate_server_py(_basic_agent())
        # Ensure the streaming methods are NOT ``async def``.
        assert "async def dispatch_a2a_stream(" not in source
        assert "async def dispatch_responses_create_stream(" not in source


def test_subagents_generates_ask_tool_per_peer():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak_adapter_langchain.templates import generate_agent_py

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(
        name="weather-agent",
        instructions="Weather specialist. Use get_weather for real data.",
        model=m,
    )
    time = Agent(name="time-agent", instructions="Time specialist.", model=m)
    assistant = Agent(
        name="assistant-agent",
        model=m,
        subagents=[weather, time],
    )

    code = generate_agent_py(assistant)
    assert "async def ask_weather_agent(" in code
    assert "async def ask_time_agent(" in code
    # Imports
    assert "from vystak.transport import ask_agent" in code
    assert "from langchain_core.runnables import RunnableConfig" in code
    # Session-id propagation
    assert "thread_id" in code
    assert (
        "metadata = {'sessionId': session_id} if session_id else {}" in code
        or 'metadata = {"sessionId": session_id} if session_id else {}' in code
    )
    # Wired into the react agent
    assert "ask_weather_agent" in code.split("create_react_agent")[-1]


def test_subagents_docstring_pulled_from_instructions():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak_adapter_langchain.templates import generate_agent_py

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(
        name="weather-agent",
        instructions="Weather specialist. Use get_weather for real data.",
        model=m,
    )
    assistant = Agent(name="assistant", model=m, subagents=[weather])
    code = generate_agent_py(assistant)
    assert "Weather specialist." in code


def test_subagents_docstring_first_paragraph_only():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak_adapter_langchain.templates import generate_agent_py

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(
        name="weather-agent",
        instructions="First paragraph here.\n\nSecond paragraph not in docstring.",
        model=m,
    )
    assistant = Agent(name="assistant", model=m, subagents=[weather])
    code = generate_agent_py(assistant)
    assert "First paragraph here." in code
    assert "Second paragraph" not in code


def test_subagents_docstring_fallback_when_instructions_empty():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak_adapter_langchain.templates import generate_agent_py

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    weather = Agent(name="weather-agent", model=m)  # no instructions
    assistant = Agent(name="assistant", model=m, subagents=[weather])
    code = generate_agent_py(assistant)
    assert "Delegate to the weather-agent agent." in code


def test_no_subagents_no_codegen_change():
    """If subagents is empty, no ask_ tool is emitted and no extra imports added."""
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak_adapter_langchain.templates import generate_agent_py

    p = Provider(name="p", type="anthropic")
    m = Model(name="m", provider=p, model_name="claude-sonnet-4-20250514")
    bare = Agent(name="solo", model=m)
    code = generate_agent_py(bare)
    assert "ask_agent" not in code
    assert "from vystak.transport" not in code
