import pytest

from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.skill import Skill

from vystak_adapter_langchain.adapter import LangChainAdapter


@pytest.fixture()
def adapter():
    return LangChainAdapter()


@pytest.fixture()
def anthropic_agent():
    return Agent(
        name="test-bot",
        model=Model(
            name="claude",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-20250514",
        ),
        skills=[Skill(name="greeting", tools=["say_hello"])],
    )


@pytest.fixture()
def openai_agent():
    return Agent(
        name="gpt-bot",
        model=Model(
            name="gpt4",
            provider=Provider(name="openai", type="openai"),
            model_name="gpt-4o",
        ),
    )


@pytest.fixture()
def invalid_provider_agent():
    return Agent(
        name="bad-bot",
        model=Model(
            name="model",
            provider=Provider(name="unknown", type="cohere"),
            model_name="command-r",
        ),
    )


class TestGenerate:
    def test_returns_generated_code(self, adapter, anthropic_agent):
        result = adapter.generate(anthropic_agent)
        assert "agent.py" in result.files
        assert "server.py" in result.files
        assert "requirements.txt" in result.files

    def test_entrypoint_is_server(self, adapter, anthropic_agent):
        result = adapter.generate(anthropic_agent)
        assert result.entrypoint == "server.py"

    def test_three_files(self, adapter, anthropic_agent):
        result = adapter.generate(anthropic_agent)
        assert len(result.files) == 3

    def test_anthropic_model_in_agent(self, adapter, anthropic_agent):
        result = adapter.generate(anthropic_agent)
        assert "ChatAnthropic" in result.files["agent.py"]

    def test_openai_model_in_agent(self, adapter, openai_agent):
        result = adapter.generate(openai_agent)
        assert "ChatOpenAI" in result.files["agent.py"]

    def test_fastapi_in_server(self, adapter, anthropic_agent):
        result = adapter.generate(anthropic_agent)
        assert "FastAPI" in result.files["server.py"]

    def test_requirements_include_provider(self, adapter, anthropic_agent):
        result = adapter.generate(anthropic_agent)
        assert "langchain-anthropic" in result.files["requirements.txt"]


class TestValidate:
    def test_valid_anthropic_agent(self, adapter, anthropic_agent):
        errors = adapter.validate(anthropic_agent)
        assert errors == []

    def test_valid_openai_agent(self, adapter, openai_agent):
        errors = adapter.validate(openai_agent)
        assert errors == []

    def test_unsupported_provider(self, adapter, invalid_provider_agent):
        errors = adapter.validate(invalid_provider_agent)
        assert len(errors) == 1
        assert "provider" in errors[0].field.lower() or "provider" in errors[0].message.lower()

    def test_returns_list(self, adapter, anthropic_agent):
        result = adapter.validate(anthropic_agent)
        assert isinstance(result, list)
