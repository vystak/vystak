import ast as python_ast

import pytest
from vystak.schema.agent import Agent
from vystak.schema.channel import Channel
from vystak.schema.common import ChannelType, McpTransport
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
        channels=[Channel(name="api", type=ChannelType.API)],
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

    def test_no_vystak_in_requirements(self, anthropic_agent):
        """vystak schema is bundled as openai_types.py, not installed from PyPI."""
        reqs = generate_requirements_txt(anthropic_agent)
        assert "vystak" not in reqs


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
