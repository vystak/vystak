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
    # Built-in tools file generated with each skill's tools
    assert "builtin_tools.py" in files
    assert "read_file" in files["builtin_tools.py"]
    # Workspace client bundled as a sibling file (not package import) so the
    # agent container doesn't need vystak_adapter_langchain installed.
    assert "workspace_client.py" in files
    # builtin_tools.py self-initializes WorkspaceRpcClient from VYSTAK_WORKSPACE_HOST
    bt = files["builtin_tools.py"]
    assert "WorkspaceRpcClient" in bt
    assert "VYSTAK_WORKSPACE_HOST" in bt
    # Each generated tool traps exceptions and returns the error text so the
    # LLM sees a ToolMessage instead of the graph crashing.
    assert "except Exception as e:" in bt
    assert "Error calling" in bt
    # ALL_TOOLS list is emitted so agent.py can import it in one shot
    assert "ALL_TOOLS" in bt
    # agent.py actually wires the built-ins into create_react_agent
    ap = files["agent.py"]
    assert "from builtin_tools import ALL_TOOLS" in ap
    assert "*_builtin_tools" in ap


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


def _minimal_agent_for_turn_core_test():
    from vystak.schema.agent import Agent
    from vystak.schema.model import Model
    from vystak.schema.provider import Provider

    p = Provider(name="anthropic", type="anthropic")
    return Agent(
        name="probe",
        model=Model(name="m", model_name="claude-sonnet-4-20250514", provider=p),
    )


class TestServerPyEmitsTurnCoreHelpers:
    """Phase 1.2: every generated server.py includes the shared cores."""

    def _server_py(self):
        from vystak_adapter_langchain.adapter import LangChainAdapter

        agent = _minimal_agent_for_turn_core_test()
        return LangChainAdapter().generate(agent).files["server.py"]

    def test_imports_dataclass(self):
        assert "from dataclasses import dataclass" in self._server_py()

    def test_imports_literal(self):
        assert "from typing import Literal" in self._server_py()

    def test_imports_command(self):
        assert "from langgraph.types import Command" in self._server_py()

    def test_emits_turn_result_dataclass(self):
        assert "class TurnResult:" in self._server_py()

    def test_emits_turn_event_dataclass(self):
        assert "class TurnEvent:" in self._server_py()

    def test_emits_flatten_message_content(self):
        assert "def _flatten_message_content(" in self._server_py()

    def test_emits_process_turn(self):
        assert "async def process_turn(" in self._server_py()

    def test_emits_process_turn_streaming(self):
        assert "async def process_turn_streaming(" in self._server_py()

    def test_server_py_is_syntactically_valid(self):
        import ast

        ast.parse(self._server_py())

    def test_stateless_agent_emits_store_none_and_handle_memory_stub(self):
        """Stateless agents need _store and handle_memory_actions in scope.

        Without them the cores' ``if _store is not None:`` guards would raise NameError.
        """
        src = self._server_py()  # uses the stateless _minimal_agent_for_turn_core_test
        assert "_store = None" in src
        # The cores reference handle_memory_actions inside an `if _store is not None:` guard,
        # but handle_memory_actions still needs to exist for static analyzers.
        assert "async def handle_memory_actions(" in src

    def test_persistent_agent_emits_handle_memory_actions_before_process_turn(self):
        """In a persistent agent, handle_memory_actions must come BEFORE process_turn.

        This ordering ensures process_turn's reference resolves at call time.
        """
        from vystak.schema.agent import Agent
        from vystak.schema.model import Model
        from vystak.schema.platform import Platform
        from vystak.schema.provider import Provider
        from vystak.schema.secret import Secret
        from vystak.schema.service import Sqlite
        from vystak_adapter_langchain.adapter import LangChainAdapter

        p = Provider(name="anthropic", type="anthropic")
        d = Provider(name="docker", type="docker")
        agent = Agent(
            name="probe",
            model=Model(name="m", model_name="claude", provider=p),
            platform=Platform(name="local", type="docker", provider=d),
            secrets=[Secret(name="K")],
            sessions=Sqlite(name="probe-sessions", provider=d),
        )
        src = LangChainAdapter().generate(agent).files["server.py"]
        # Both must be present.
        assert "async def handle_memory_actions(" in src
        assert "async def process_turn(" in src
        # And in the right order.
        idx_handle = src.index("async def handle_memory_actions(")
        idx_proc = src.index("async def process_turn(")
        assert idx_handle < idx_proc, (
            "handle_memory_actions must be defined before process_turn so "
            "process_turn's reference resolves at call time"
        )


class TestSharedTurnCoreInvariants:
    """Acceptance criteria 1 and 2 from the spec.

    Structural backstop: if a future change adds an _agent.ainvoke or
    _agent.astream_events call outside the cores, these tests break and
    the author notices before merge.

    Refs: docs/superpowers/specs/2026-04-26-langchain-adapter-shared-turn-core-design.md
    """

    SRC_DIR = "packages/python/vystak-adapter-langchain/src/vystak_adapter_langchain"

    def _grep_source(self, needle):
        """Return list of "{file}:{lineno}: {line}" hits across the adapter source."""
        import pathlib
        # Test file lives at packages/python/vystak-adapter-langchain/tests/test_adapter.py
        # so the repo root is parents[4]:
        #   parents[0] = …/tests
        #   parents[1] = …/vystak-adapter-langchain
        #   parents[2] = …/python
        #   parents[3] = …/packages
        #   parents[4] = repo root (worktree root)
        repo_root = pathlib.Path(__file__).resolve().parents[4]
        root = repo_root / self.SRC_DIR
        hits = []
        for path in sorted(root.glob("*.py")):
            text = path.read_text()
            for lineno, line in enumerate(text.splitlines(), 1):
                if needle in line:
                    hits.append(f"{path.name}:{lineno}: {line.strip()}")
        return hits

    def test_ainvoke_appears_only_inside_turn_core(self):
        hits = self._grep_source("_agent.ainvoke(")
        assert len(hits) == 1, (
            "spec AC1 violated: expected 1 _agent.ainvoke site (inside "
            "process_turn in turn_core.py); got:\n" + "\n".join(hits)
        )
        assert hits[0].startswith("turn_core.py:"), (
            f"_agent.ainvoke must live in turn_core.py only; got: {hits[0]}"
        )

    def test_astream_events_appears_only_inside_turn_core(self):
        hits = self._grep_source("_agent.astream_events(")
        assert len(hits) == 1, (
            "spec AC1 violated: expected 1 _agent.astream_events site "
            "(inside process_turn_streaming in turn_core.py); got:\n" + "\n".join(hits)
        )
        assert hits[0].startswith("turn_core.py:"), (
            f"_agent.astream_events must live in turn_core.py only; got: {hits[0]}"
        )

    def test_no_residual_astream_calls_outside_turn_core(self):
        """No streaming protocol path should still inline its own _agent.astream(...) loop."""
        hits = self._grep_source("_agent.astream(")
        # NOTE: _agent.astream_events also matches _agent.astream as a substring,
        # but we use the suffix "_events(" filter via separate test above. To
        # check the bare astream form, search for the exact substring.
        # An astream_events hit also contains the substring _agent.astream so
        # filter those out.
        bare = [h for h in hits if "astream_events(" not in h]
        assert bare == [], (
            "spec AC: expected zero _agent.astream(...) bare calls outside "
            "turn_core.py; got:\n" + "\n".join(bare)
        )

    def test_handle_memory_actions_call_sites(self):
        """handle_memory_actions is called from exactly 2 places (the two cores)."""
        hits = self._grep_source("await handle_memory_actions(")
        assert len(hits) == 2, (
            "spec AC2 violated: expected 2 handle_memory_actions call "
            "sites (both inside turn_core.py — process_turn and "
            "process_turn_streaming); got:\n" + "\n".join(hits)
        )
        assert all(h.startswith("turn_core.py:") for h in hits), (
            "All handle_memory_actions calls must originate in turn_core.py; got:\n"
            + "\n".join(hits)
        )
