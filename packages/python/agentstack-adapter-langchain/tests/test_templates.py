import ast as python_ast

import pytest

from agentstack.schema.agent import Agent
from agentstack.schema.channel import Channel
from agentstack.schema.common import ChannelType
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider
from agentstack.schema.skill import Skill

from agentstack_adapter_langchain.templates import (
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

    def test_fastapi_app(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "FastAPI" in code

    def test_invoke_endpoint(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "/invoke" in code

    def test_stream_endpoint(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "/stream" in code

    def test_health_endpoint(self, anthropic_agent):
        code = generate_server_py(anthropic_agent)
        assert "/health" in code

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
