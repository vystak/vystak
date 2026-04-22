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


def test_workspace_declared_generates_builtin_tools_and_bootstrap():
    import tempfile
    from pathlib import Path

    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.platform import Platform
    from vystak.schema.provider import Provider
    from vystak.schema.skill import Skill
    from vystak.schema.workspace import Workspace
    from vystak_adapter_langchain.adapter import LangChainAdapter

    docker_p = Provider(name="docker", type="docker")
    platform = Platform(name="local", type="docker", provider=docker_p)
    anthropic = Provider(name="anthropic", type="anthropic")
    agent = Agent(
        name="coder",
        model=Model(name="m", provider=anthropic, model_name="claude-sonnet-4-20250514"),
        platform=platform,
        skills=[Skill(name="edit", tools=["fs.readFile", "fs.writeFile", "exec.run"])],
        workspace=Workspace(name="dev", image="python:3.12-slim"),
    )
    with tempfile.TemporaryDirectory() as td:
        tools_dir = Path(td) / "tools"
        tools_dir.mkdir()
        code = LangChainAdapter().generate(agent, base_dir=Path(td))

    files = code.files
    # Built-in tools file generated
    assert "builtin_tools.py" in files
    assert "read_file" in files["builtin_tools.py"]
    # Bootstrap code initializes workspace client
    assert "WorkspaceRpcClient" in files.get("server.py", "")
    assert "VYSTAK_WORKSPACE_HOST" in files.get("server.py", "")


def test_no_workspace_no_builtin_tools():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider
    from vystak.schema.skill import Skill
    from vystak_adapter_langchain.adapter import LangChainAdapter

    anthropic = Provider(name="anthropic", type="anthropic")
    agent = Agent(
        name="coder",
        model=Model(name="m", provider=anthropic, model_name="claude-sonnet-4-20250514"),
        skills=[Skill(name="edit", tools=["say_hello"])],
    )
    code = LangChainAdapter().generate(agent)
    assert "builtin_tools.py" not in code.files
    # Server should not have workspace bootstrap
    assert "WorkspaceRpcClient" not in code.files.get("server.py", "")
    assert "VYSTAK_WORKSPACE_HOST" not in code.files.get("server.py", "")
