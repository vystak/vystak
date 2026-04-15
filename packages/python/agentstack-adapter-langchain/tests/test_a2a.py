import ast as python_ast

import pytest

from agentstack.schema.agent import Agent
from agentstack.schema.channel import Channel
from agentstack.schema.common import ChannelType
from agentstack.schema.model import Model
from agentstack.schema.provider import Provider
from agentstack.schema.skill import Skill

from agentstack_adapter_langchain.a2a import (
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
        channels=[Channel(name="api", type=ChannelType.API)],
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
        assert '"agentstack/test-bot"' in code

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
