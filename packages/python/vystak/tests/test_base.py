import pytest

from vystak.providers.base import (
    AgentStatus, ChannelAdapter, DeployPlan, DeployResult,
    FrameworkAdapter, GeneratedCode, PlatformProvider, ValidationError,
)


class TestSupportingTypes:
    def test_generated_code(self):
        code = GeneratedCode(files={"main.py": "print('hello')"}, entrypoint="main.py")
        assert code.entrypoint == "main.py"

    def test_deploy_plan(self):
        plan = DeployPlan(agent_name="bot", actions=["create container"], current_hash=None, target_hash="abc123", changes={"brain": (None, "abc123")})
        assert plan.agent_name == "bot"

    def test_deploy_result(self):
        result = DeployResult(agent_name="bot", success=True, hash="abc123", message="deployed")
        assert result.success is True

    def test_agent_status(self):
        status = AgentStatus(agent_name="bot", running=True, hash="abc123")
        assert status.info == {}

    def test_validation_error(self):
        err = ValidationError(field="model", message="model is required")
        assert err.field == "model"


class TestFrameworkAdapterABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            FrameworkAdapter()

    def test_valid_subclass(self):
        class GoodAdapter(FrameworkAdapter):
            def generate(self, agent):
                return GeneratedCode(files={}, entrypoint="main.py")
            def validate(self, agent):
                return []
        adapter = GoodAdapter()
        assert adapter is not None


class TestPlatformProviderABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            PlatformProvider()

    def test_valid_subclass(self):
        class GoodProvider(PlatformProvider):
            def plan(self, agent, current_hash):
                return DeployPlan(agent_name=agent.name, actions=[], current_hash=current_hash, target_hash="x", changes={})
            def apply(self, plan):
                return DeployResult(agent_name=plan.agent_name, success=True, hash="x", message="ok")
            def destroy(self, agent_name):
                pass
            def status(self, agent_name):
                return AgentStatus(agent_name=agent_name, running=False, hash=None)
            def get_hash(self, agent_name):
                return None
        provider = GoodProvider()
        assert provider is not None


class TestChannelAdapterABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            ChannelAdapter()

    def test_valid_subclass(self):
        class GoodChannel(ChannelAdapter):
            def setup(self, agent, channel):
                pass
            def teardown(self, channel):
                pass
        adapter = GoodChannel()
        assert adapter is not None
