import ast as python_ast

import pytest
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.skill import Skill
from vystak_adapter_langchain.a2a import (
    generate_a2a_handler_code,
    generate_agent_card_code,
    generate_task_manager_code,
)


@pytest.fixture()
def sample_agent():
    return Agent(
        name="test-bot",
        instructions="You are a helpful test agent.",
        model=Model(
            name="claude",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-20250514",
        ),
        skills=[
            Skill(name="weather", tools=["get_weather", "get_forecast"]),
            Skill(name="time", tools=["get_time"]),
        ],
    )


class TestAgentCardCode:
    def test_parseable(self, sample_agent):
        code = generate_agent_card_code(sample_agent)
        python_ast.parse(code)

    def test_has_agent_name(self, sample_agent):
        code = generate_agent_card_code(sample_agent)
        assert "test-bot" in code

    def test_has_description(self, sample_agent):
        code = generate_agent_card_code(sample_agent)
        assert "helpful test agent" in code

    def test_has_skills(self, sample_agent):
        code = generate_agent_card_code(sample_agent)
        assert "weather" in code
        assert "time" in code

    def test_has_capabilities(self, sample_agent):
        code = generate_agent_card_code(sample_agent)
        assert "streaming" in code

    def test_has_endpoint(self, sample_agent):
        code = generate_agent_card_code(sample_agent)
        assert "/.well-known/agent.json" in code

    def test_models_field_in_card(self, sample_agent):
        code = generate_agent_card_code(sample_agent)
        assert '"models"' in code
        assert '"vystak/test-bot"' in code

    def test_no_instructions_uses_name(self):
        agent = Agent(
            name="minimal-bot",
            model=Model(
                name="claude",
                provider=Provider(name="anthropic", type="anthropic"),
                model_name="claude-sonnet-4-20250514",
            ),
        )
        code = generate_agent_card_code(agent)
        assert "minimal-bot" in code
        python_ast.parse(code)


class TestTaskManagerCode:
    def test_parseable(self):
        code = generate_task_manager_code()
        python_ast.parse(code)

    def test_has_create_task(self):
        code = generate_task_manager_code()
        assert "create_task" in code

    def test_has_get_task(self):
        code = generate_task_manager_code()
        assert "get_task" in code

    def test_has_update_task(self):
        code = generate_task_manager_code()
        assert "update_task" in code

    def test_has_task_states(self):
        code = generate_task_manager_code()
        assert "submitted" in code
        assert "working" in code
        assert "completed" in code


class TestA2AHandlerCode:
    def test_parseable(self, sample_agent):
        code = generate_a2a_handler_code(sample_agent)
        python_ast.parse(code)

    def test_has_tasks_send(self, sample_agent):
        code = generate_a2a_handler_code(sample_agent)
        assert "tasks/send" in code

    def test_has_tasks_get(self, sample_agent):
        code = generate_a2a_handler_code(sample_agent)
        assert "tasks/get" in code

    def test_has_tasks_cancel(self, sample_agent):
        code = generate_a2a_handler_code(sample_agent)
        assert "tasks/cancel" in code

    def test_has_tasks_subscribe(self, sample_agent):
        code = generate_a2a_handler_code(sample_agent)
        assert "tasks/sendSubscribe" in code

    def test_has_jsonrpc(self, sample_agent):
        code = generate_a2a_handler_code(sample_agent)
        assert "jsonrpc" in code

    def test_has_interrupt_handling(self, sample_agent):
        code = generate_a2a_handler_code(sample_agent)
        assert "input_required" in code
        assert "__interrupt__" in code

    def test_has_command_resume(self, sample_agent):
        code = generate_a2a_handler_code(sample_agent)
        assert "Command" in code


class TestA2AOneShotUsesProcessTurn:
    """The migrated _a2a_one_shot calls process_turn instead of inlining ainvoke."""

    def _server_py(self):
        from vystak.schema.agent import Agent
        from vystak.schema.model import Model
        from vystak.schema.platform import Platform
        from vystak.schema.provider import Provider
        from vystak.schema.secret import Secret
        from vystak_adapter_langchain.adapter import LangChainAdapter

        p = Provider(name="anthropic", type="anthropic")
        d = Provider(name="docker", type="docker")
        agent = Agent(
            name="probe",
            model=Model(name="m", model_name="claude", provider=p),
            platform=Platform(name="local", type="docker", provider=d),
            secrets=[Secret(name="K")],
        )
        return LangChainAdapter().generate(agent).files["server.py"]

    def test_one_shot_calls_process_turn(self):
        src = self._server_py()
        assert "await process_turn(" in src

    def test_one_shot_no_longer_inlines_ainvoke(self):
        """Inside _a2a_one_shot, _agent.ainvoke must not appear (it lives in process_turn now)."""
        import re
        src = self._server_py()
        match = re.search(
            r"async def _a2a_one_shot\(.*?\)(?:\s*->\s*[^\n:]*)?:\s*\n(.*?)(?=\nasync def |\Z)",
            src, re.DOTALL,
        )
        assert match, "could not locate _a2a_one_shot function in emitted server.py"
        body = match.group(1)
        assert "_agent.ainvoke(" not in body, (
            "expected _a2a_one_shot to delegate to process_turn, "
            "but found inlined _agent.ainvoke"
        )
        assert "handle_memory_actions(" not in body
