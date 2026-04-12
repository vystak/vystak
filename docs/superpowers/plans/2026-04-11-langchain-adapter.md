# LangChain Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a LangChain/LangGraph framework adapter that generates deployable agent code (LangGraph agent + FastAPI harness) from AgentStack schema definitions.

**Architecture:** The adapter implements `FrameworkAdapter` ABC and uses string templates to generate three files: `agent.py` (LangGraph react agent), `server.py` (FastAPI harness with invoke/stream/health endpoints), and `requirements.txt`. The adapter itself has no LangChain dependency — it only generates code that uses LangChain.

**Tech Stack:** Python 3.11+, agentstack core SDK, pytest, `ast` module for validating generated code

---

### Task 1: Package Scaffolding

**Files:**
- Create: `packages/python/agentstack-adapter-langchain/pyproject.toml`
- Create: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/__init__.py`
- Modify: `pyproject.toml` (root workspace)

- [ ] **Step 1: Create `packages/python/agentstack-adapter-langchain/pyproject.toml`**

```toml
[project]
name = "agentstack-adapter-langchain"
version = "0.1.0"
description = "AgentStack LangChain/LangGraph framework adapter"
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
    "agentstack>=0.1.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentstack_adapter_langchain"]

[tool.uv.sources]
agentstack = { workspace = true }
```

- [ ] **Step 2: Create `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/__init__.py`**

```python
"""AgentStack LangChain/LangGraph framework adapter."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Add to root workspace**

Add `agentstack-adapter-langchain` to root `pyproject.toml` dev-dependencies list and `tool.uv.sources`:

In the `dev-dependencies` list, add:
```
"agentstack-adapter-langchain",
```

In `[tool.uv.sources]`, add:
```
agentstack-adapter-langchain = { workspace = true }
```

- [ ] **Step 4: Sync workspace**

Run: `cd ~/Developer/work/AgentsStack && uv sync`

Expected: all packages install including the new one.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/ pyproject.toml uv.lock
git commit -m "feat: scaffold agentstack-adapter-langchain package"
```

---

### Task 2: Code Generation Templates

**Files:**
- Create: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py`
- Create: `packages/python/agentstack-adapter-langchain/tests/test_templates.py`

- [ ] **Step 1: Write tests for templates**

`packages/python/agentstack-adapter-langchain/tests/test_templates.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/test_templates.py -v`

Expected: FAIL — `ModuleNotFoundError` for `agentstack_adapter_langchain.templates`.

- [ ] **Step 3: Implement templates.py**

`packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/templates.py`:
```python
"""Code generation templates for LangChain/LangGraph agents."""

from textwrap import dedent

from agentstack.schema.agent import Agent

# Provider type -> (import statement, class name)
MODEL_PROVIDERS = {
    "anthropic": (
        "from langchain_anthropic import ChatAnthropic",
        "ChatAnthropic",
    ),
    "openai": (
        "from langchain_openai import ChatOpenAI",
        "ChatOpenAI",
    ),
}

# Provider type -> pip package
PROVIDER_PACKAGES = {
    "anthropic": "langchain-anthropic>=0.3",
    "openai": "langchain-openai>=0.3",
}


def _generate_tool_stubs(agent: Agent) -> str:
    """Generate @tool stub functions from agent skills."""
    tools = []
    seen = set()
    for skill in agent.skills:
        for tool_name in skill.tools:
            if tool_name in seen:
                continue
            seen.add(tool_name)
            tools.append(dedent(f"""\
                @tool
                def {tool_name}(input: str) -> str:
                    \"\"\"{tool_name.replace('_', ' ').title()}.\"\"\"\
                    return f"Stub: {tool_name} called with {{input}}"
            """))
    return "\n\n".join(tools)


def _collect_system_prompt(agent: Agent) -> str:
    """Collect and concatenate system prompts from all skills."""
    prompts = []
    for skill in agent.skills:
        if skill.prompt:
            prompts.append(skill.prompt)
    return "\n\n".join(prompts)


def generate_agent_py(agent: Agent) -> str:
    """Generate a LangGraph agent definition file."""
    provider_type = agent.model.provider.type
    model_import, model_class = MODEL_PROVIDERS.get(
        provider_type, MODEL_PROVIDERS["anthropic"]
    )

    # Build model kwargs
    model_kwargs = [f'model="{agent.model.model_name}"']
    for key, value in agent.model.parameters.items():
        if isinstance(value, str):
            model_kwargs.append(f'{key}="{value}"')
        else:
            model_kwargs.append(f"{key}={value}")
    model_kwargs_str = ", ".join(model_kwargs)

    # Build tool stubs
    tool_stubs = _generate_tool_stubs(agent)

    # Collect tool names
    tool_names = []
    seen = set()
    for skill in agent.skills:
        for tool_name in skill.tools:
            if tool_name not in seen:
                seen.add(tool_name)
                tool_names.append(tool_name)

    tools_list = ", ".join(tool_names) if tool_names else ""

    # System prompt
    system_prompt = _collect_system_prompt(agent)

    # Build the agent code
    lines = []
    lines.append(f'"""AgentStack generated agent: {agent.name}."""\n')
    lines.append(f"{model_import}")

    if tool_names:
        lines.append("from langchain_core.tools import tool")

    lines.append("from langgraph.prebuilt import create_react_agent")
    lines.append("")
    lines.append("")
    lines.append(f"# Model")
    lines.append(f"model = {model_class}({model_kwargs_str})")
    lines.append("")

    if tool_stubs:
        lines.append("")
        lines.append("# Tools")
        lines.append(tool_stubs)

    lines.append("")
    lines.append("# Agent")

    if system_prompt:
        escaped_prompt = system_prompt.replace('"""', '\\"\\"\\"')
        lines.append(f'system_prompt = """{escaped_prompt}"""')
        lines.append("")
        lines.append(
            f"agent = create_react_agent(model, [{tools_list}], prompt=system_prompt)"
        )
    else:
        lines.append(f"agent = create_react_agent(model, [{tools_list}])")

    lines.append("")

    return "\n".join(lines)


def generate_server_py(agent: Agent) -> str:
    """Generate a FastAPI harness server file."""
    return dedent(f"""\
        \"\"\"AgentStack harness server for {agent.name}.\"\"\"

        import asyncio
        import json
        import os
        import uuid

        from fastapi import FastAPI
        from pydantic import BaseModel
        from sse_starlette.sse import EventSourceResponse

        from agent import agent

        app = FastAPI(title="{agent.name}")

        AGENT_NAME = os.environ.get("AGENTSTACK_AGENT_NAME", "{agent.name}")
        HOST = os.environ.get("HOST", "0.0.0.0")
        PORT = int(os.environ.get("PORT", "8000"))


        class InvokeRequest(BaseModel):
            message: str
            session_id: str | None = None


        class InvokeResponse(BaseModel):
            response: str
            session_id: str


        @app.get("/health")
        async def health():
            return {{"status": "ok", "agent": AGENT_NAME, "version": "0.1.0"}}


        @app.post("/invoke", response_model=InvokeResponse)
        async def invoke(request: InvokeRequest):
            session_id = request.session_id or str(uuid.uuid4())
            result = await agent.ainvoke(
                {{"messages": [("user", request.message)]}},
                config={{"configurable": {{"thread_id": session_id}}}},
            )
            response_text = result["messages"][-1].content
            return InvokeResponse(response=response_text, session_id=session_id)


        @app.post("/stream")
        async def stream(request: InvokeRequest):
            session_id = request.session_id or str(uuid.uuid4())

            async def event_generator():
                async for event in agent.astream_events(
                    {{"messages": [("user", request.message)]}},
                    config={{"configurable": {{"thread_id": session_id}}}},
                    version="v2",
                ):
                    if event["event"] == "on_chat_model_stream":
                        token = event["data"]["chunk"].content
                        if token:
                            yield {{"data": json.dumps({{"token": token, "session_id": session_id}})}}
                yield {{"data": json.dumps({{"done": True, "session_id": session_id}})}}

            return EventSourceResponse(event_generator())


        if __name__ == "__main__":
            import uvicorn

            uvicorn.run(app, host=HOST, port=PORT)
    """)


def generate_requirements_txt(agent: Agent) -> str:
    """Generate a requirements.txt based on the agent's model provider."""
    provider_type = agent.model.provider.type
    provider_pkg = PROVIDER_PACKAGES.get(provider_type, PROVIDER_PACKAGES["anthropic"])

    return dedent(f"""\
        langchain-core>=0.3
        langgraph>=0.2
        {provider_pkg}
        fastapi>=0.115
        uvicorn>=0.34
        sse-starlette>=2.0
    """)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/test_templates.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/
git commit -m "feat: add LangChain code generation templates"
```

---

### Task 3: LangChainAdapter Class

**Files:**
- Create: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/adapter.py`
- Modify: `packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/__init__.py`
- Create: `packages/python/agentstack-adapter-langchain/tests/test_adapter.py`

- [ ] **Step 1: Write tests for adapter**

`packages/python/agentstack-adapter-langchain/tests/test_adapter.py`:
```python
import pytest

from agentstack.schema.agent import Agent
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider
from agentstack.schema.skill import Skill

from agentstack_adapter_langchain.adapter import LangChainAdapter


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/test_adapter.py -v`

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement adapter.py**

`packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/adapter.py`:
```python
"""LangChain/LangGraph framework adapter."""

from agentstack.providers.base import FrameworkAdapter, GeneratedCode, ValidationError
from agentstack.schema.agent import Agent

from agentstack_adapter_langchain.templates import (
    MODEL_PROVIDERS,
    generate_agent_py,
    generate_requirements_txt,
    generate_server_py,
)


class LangChainAdapter(FrameworkAdapter):
    """Generates LangGraph agent code + FastAPI harness from an Agent schema."""

    def generate(self, agent: Agent) -> GeneratedCode:
        """Generate deployable LangGraph agent code."""
        return GeneratedCode(
            files={
                "agent.py": generate_agent_py(agent),
                "server.py": generate_server_py(agent),
                "requirements.txt": generate_requirements_txt(agent),
            },
            entrypoint="server.py",
        )

    def validate(self, agent: Agent) -> list[ValidationError]:
        """Validate that the agent can be deployed with LangChain."""
        errors = []

        provider_type = agent.model.provider.type
        if provider_type not in MODEL_PROVIDERS:
            supported = ", ".join(MODEL_PROVIDERS.keys())
            errors.append(
                ValidationError(
                    field="model.provider.type",
                    message=f"Unsupported provider '{provider_type}'. Supported: {supported}",
                )
            )

        return errors
```

- [ ] **Step 4: Update __init__.py with re-exports**

`packages/python/agentstack-adapter-langchain/src/agentstack_adapter_langchain/__init__.py`:
```python
"""AgentStack LangChain/LangGraph framework adapter."""

__version__ = "0.1.0"

from agentstack_adapter_langchain.adapter import LangChainAdapter

__all__ = ["LangChainAdapter", "__version__"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/ -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/python/agentstack-adapter-langchain/
git commit -m "feat: add LangChainAdapter with generate and validate"
```

---

### Task 4: Full Verification

- [ ] **Step 1: Run all tests for the adapter package**

Run: `uv run pytest packages/python/agentstack-adapter-langchain/tests/ -v`

Expected: all tests pass.

- [ ] **Step 2: Run all Python tests across all packages**

Run: `just test-python`

Expected: all tests pass (agentstack core + cli + all adapters/providers).

- [ ] **Step 3: Run linting**

Run: `uv run ruff check packages/python/agentstack-adapter-langchain/`

Expected: no lint errors (or fix any that appear).

- [ ] **Step 4: Verify adapter works end-to-end**

Run:
```bash
uv run python -c "
from agentstack import Agent, Model, Provider, Skill, Channel, ChannelType
from agentstack_adapter_langchain import LangChainAdapter

anthropic = Provider(name='anthropic', type='anthropic')
model = Model(name='claude', provider=anthropic, model_name='claude-sonnet-4-20250514', parameters={'temperature': 0.7})
agent = Agent(
    name='demo-bot',
    model=model,
    skills=[Skill(name='greeting', tools=['say_hello', 'say_goodbye'], prompt='Be friendly.')],
    channels=[Channel(name='api', type=ChannelType.API)],
)

adapter = LangChainAdapter()
errors = adapter.validate(agent)
print(f'Validation errors: {errors}')

code = adapter.generate(agent)
print(f'Generated files: {list(code.files.keys())}')
print(f'Entrypoint: {code.entrypoint}')
print()
print('=== agent.py ===')
print(code.files['agent.py'])
print()
print('=== server.py (first 10 lines) ===')
for line in code.files['server.py'].split(chr(10))[:10]:
    print(line)
print()
print('=== requirements.txt ===')
print(code.files['requirements.txt'])
"
```

Expected: prints validation (no errors), file list, generated agent code with tools and system prompt, server code snippet, and requirements.
