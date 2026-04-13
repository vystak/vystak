"""Tests for AzureProvider."""

from unittest.mock import MagicMock, patch

import pytest

from agentstack.providers.base import DeployPlan, GeneratedCode
from agentstack_provider_azure.provider import AzureProvider


def _make_agent(name="my-agent"):
    agent = MagicMock()
    agent.name = name
    agent.model = MagicMock()
    agent.skills = []
    agent.mcp_servers = []
    agent.channels = []
    agent.workspace = None
    agent.resources = []
    agent.secrets = []
    agent.sessions = None
    agent.memory = None
    agent.services = []
    agent.platform = MagicMock()
    agent.platform.config = {}
    agent.platform.provider.config = {}
    agent.platform.provider.type = "azure"
    return agent


class TestAzureProviderPlan:
    def test_plan_always_has_action(self):
        provider = AzureProvider()
        agent = _make_agent()
        plan = provider.plan(agent, current_hash=None)
        assert plan.agent_name == "my-agent"
        assert len(plan.actions) == 1
        assert "Azure Container Apps" in plan.actions[0]

    def test_plan_with_current_hash(self):
        provider = AzureProvider()
        agent = _make_agent()
        plan = provider.plan(agent, current_hash="old-hash")
        assert plan.current_hash == "old-hash"


class TestAzureProviderGetHash:
    def test_returns_none(self):
        provider = AzureProvider()
        assert provider.get_hash("any-agent") is None


class TestAzureProviderApplyNoCode:
    def test_apply_without_generated_code(self):
        provider = AzureProvider()
        plan = DeployPlan(
            agent_name="test",
            actions=["Deploy"],
            current_hash=None,
            target_hash="abc",
            changes={},
        )
        result = provider.apply(plan)
        assert result.success is False
        assert "generated code" in result.message.lower()


class TestAzureProviderApply:
    @patch("agentstack_provider_azure.provider.ProvisionGraph")
    @patch("agentstack_provider_azure.provider.AzureProvider._create_docker_client")
    @patch("agentstack_provider_azure.provider.get_credential")
    @patch("agentstack_provider_azure.provider.get_subscription_id")
    @patch("agentstack_provider_azure.provider.get_location")
    def test_apply_builds_graph_and_executes(
        self, mock_location, mock_sub, mock_cred, mock_docker, mock_graph_cls
    ):
        mock_location.return_value = "eastus2"
        mock_sub.return_value = "sub-123"
        mock_cred.return_value = MagicMock()
        mock_docker.return_value = MagicMock()

        # Mock ProvisionGraph
        mock_graph = MagicMock()
        mock_graph_cls.return_value = mock_graph

        from agentstack.provisioning.node import ProvisionResult

        mock_graph.execute.return_value = {
            "container-app": ProvisionResult(
                name="container-app",
                success=True,
                info={"url": "https://my-agent.eastus.azurecontainerapps.io", "fqdn": "my-agent.eastus.azurecontainerapps.io", "app_name": "my-agent"},
            ),
        }

        provider = AzureProvider()
        agent = _make_agent()
        provider.set_agent(agent)
        provider.set_generated_code(GeneratedCode(
            files={"main.py": "print('hi')", "requirements.txt": "fastapi"},
            entrypoint="main.py",
        ))

        plan = DeployPlan(
            agent_name="my-agent",
            actions=["Deploy to Azure Container Apps"],
            current_hash=None,
            target_hash="abc123",
            changes={"all": (None, "abc123")},
        )

        with patch.dict("sys.modules", {
            "azure.mgmt.resource": MagicMock(),
            "azure.mgmt.loganalytics": MagicMock(),
            "azure.mgmt.containerregistry": MagicMock(),
            "azure.mgmt.appcontainers": MagicMock(),
        }):
            result = provider.apply(plan)

        assert result.success is True
        assert "my-agent" in result.message
        # Verify 5 nodes were added to the graph
        assert mock_graph.add.call_count == 5
        mock_graph.execute.assert_called_once()

    @patch("agentstack_provider_azure.provider.ProvisionGraph")
    @patch("agentstack_provider_azure.provider.AzureProvider._create_docker_client")
    @patch("agentstack_provider_azure.provider.get_credential")
    @patch("agentstack_provider_azure.provider.get_subscription_id")
    @patch("agentstack_provider_azure.provider.get_location")
    def test_apply_uses_config_names(
        self, mock_location, mock_sub, mock_cred, mock_docker, mock_graph_cls
    ):
        mock_location.return_value = "westus"
        mock_sub.return_value = "sub-123"
        mock_cred.return_value = MagicMock()
        mock_docker.return_value = MagicMock()

        mock_graph = MagicMock()
        mock_graph_cls.return_value = mock_graph

        from agentstack.provisioning.node import ProvisionResult

        mock_graph.execute.return_value = {
            "container-app": ProvisionResult(
                name="container-app",
                success=True,
                info={"url": "https://test.io", "fqdn": "test.io", "app_name": "my-agent"},
            ),
        }

        provider = AzureProvider()
        agent = _make_agent()
        agent.platform.config = {"resource_group": "custom-rg"}
        agent.platform.provider.config = {
            "registry": "myregistry.azurecr.io",
            "environment": "custom-env",
        }
        provider.set_agent(agent)
        provider.set_generated_code(GeneratedCode(
            files={"main.py": "pass", "requirements.txt": ""},
            entrypoint="main.py",
        ))

        plan = DeployPlan(
            agent_name="my-agent",
            actions=["Deploy"],
            current_hash=None,
            target_hash="xyz",
            changes={},
        )

        with patch.dict("sys.modules", {
            "azure.mgmt.resource": MagicMock(),
            "azure.mgmt.loganalytics": MagicMock(),
            "azure.mgmt.containerregistry": MagicMock(),
            "azure.mgmt.appcontainers": MagicMock(),
        }):
            result = provider.apply(plan)

        assert result.success is True
        # Verify config-derived names were used
        assert provider._rg_name("my-agent") == "custom-rg"
        assert provider._acr_name("my-agent") == "myregistry"
        assert provider._env_name("my-agent") == "custom-env"


class TestAzureProviderConfigHelpers:
    def test_default_rg_name(self):
        provider = AzureProvider()
        agent = _make_agent("test-agent")
        provider.set_agent(agent)
        assert provider._rg_name("test-agent") == "agentstack-test-agent-rg"

    def test_default_env_name(self):
        provider = AzureProvider()
        agent = _make_agent("test-agent")
        provider.set_agent(agent)
        assert provider._env_name("test-agent") == "agentstack-test-agent-env"

    def test_acr_name_strips_suffix(self):
        provider = AzureProvider()
        agent = _make_agent()
        agent.platform.provider.config = {"registry": "myreg.azurecr.io"}
        provider.set_agent(agent)
        assert provider._acr_name("my-agent") == "myreg"

    def test_acr_name_generates_from_hash(self):
        provider = AzureProvider()
        agent = _make_agent()
        provider.set_agent(agent)
        name = provider._acr_name("my-agent")
        assert name.startswith("agentstack")
        assert len(name) == len("agentstack") + 8

    def test_tags_merge(self):
        provider = AzureProvider()
        agent = _make_agent()
        agent.platform.config = {"tags": {"env": "prod"}}
        provider.set_agent(agent)
        tags = provider._tags("my-agent")
        assert tags["agentstack:managed"] == "true"
        assert tags["agentstack:agent"] == "my-agent"
        assert tags["env"] == "prod"
