"""Tests for AzureProvider."""

from unittest.mock import MagicMock, patch

from vystak.providers.base import DeployPlan, GeneratedCode
from vystak_provider_azure.provider import AzureProvider


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
    @patch("vystak_provider_azure.provider.ProvisionGraph")
    @patch("vystak_provider_azure.provider.AzureProvider._create_docker_client")
    @patch("vystak_provider_azure.provider.get_credential")
    @patch("vystak_provider_azure.provider.get_subscription_id")
    @patch("vystak_provider_azure.provider.get_location")
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

        from vystak.provisioning.node import ProvisionResult

        mock_graph.execute.return_value = {
            "container-app": ProvisionResult(
                name="container-app",
                success=True,
                info={
                    "url": "https://my-agent.eastus.azurecontainerapps.io",
                    "fqdn": "my-agent.eastus.azurecontainerapps.io",
                    "app_name": "my-agent",
                },
            ),
        }

        provider = AzureProvider()
        agent = _make_agent()
        provider.set_agent(agent)
        provider.set_generated_code(
            GeneratedCode(
                files={"main.py": "print('hi')", "requirements.txt": "fastapi"},
                entrypoint="main.py",
            )
        )

        plan = DeployPlan(
            agent_name="my-agent",
            actions=["Deploy to Azure Container Apps"],
            current_hash=None,
            target_hash="abc123",
            changes={"all": (None, "abc123")},
        )

        with patch.dict(
            "sys.modules",
            {
                "azure.mgmt.resource": MagicMock(),
                "azure.mgmt.loganalytics": MagicMock(),
                "azure.mgmt.containerregistry": MagicMock(),
                "azure.mgmt.appcontainers": MagicMock(),
            },
        ):
            result = provider.apply(plan)

        assert result.success is True
        assert "my-agent" in result.message
        # Verify 5 nodes were added to the graph
        assert mock_graph.add.call_count == 5
        mock_graph.execute.assert_called_once()

    @patch("vystak_provider_azure.provider.ProvisionGraph")
    @patch("vystak_provider_azure.provider.AzureProvider._create_docker_client")
    @patch("vystak_provider_azure.provider.get_credential")
    @patch("vystak_provider_azure.provider.get_subscription_id")
    @patch("vystak_provider_azure.provider.get_location")
    def test_apply_uses_config_names(
        self, mock_location, mock_sub, mock_cred, mock_docker, mock_graph_cls
    ):
        mock_location.return_value = "westus"
        mock_sub.return_value = "sub-123"
        mock_cred.return_value = MagicMock()
        mock_docker.return_value = MagicMock()

        mock_graph = MagicMock()
        mock_graph_cls.return_value = mock_graph

        from vystak.provisioning.node import ProvisionResult

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
        provider.set_generated_code(
            GeneratedCode(
                files={"main.py": "pass", "requirements.txt": ""},
                entrypoint="main.py",
            )
        )

        plan = DeployPlan(
            agent_name="my-agent",
            actions=["Deploy"],
            current_hash=None,
            target_hash="xyz",
            changes={},
        )

        with patch.dict(
            "sys.modules",
            {
                "azure.mgmt.resource": MagicMock(),
                "azure.mgmt.loganalytics": MagicMock(),
                "azure.mgmt.containerregistry": MagicMock(),
                "azure.mgmt.appcontainers": MagicMock(),
            },
        ):
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
        assert provider._rg_name("test-agent") == "vystak-test-agent-rg"

    def test_default_env_name(self):
        provider = AzureProvider()
        agent = _make_agent("test-agent")
        provider.set_agent(agent)
        assert provider._env_name("test-agent") == "vystak-test-agent-rg-env"

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
        assert name.startswith("vystak")
        assert len(name) == len("vystak") + 8

    def test_tags_merge(self):
        provider = AzureProvider()
        agent = _make_agent()
        agent.platform.config = {"tags": {"env": "prod"}}
        provider.set_agent(agent)
        tags = provider._tags("my-agent")
        assert tags["vystak:managed"] == "true"
        assert tags["vystak:agent"] == "my-agent"
        assert tags["env"] == "prod"


def _make_channel(name="chat", channel_type=None):
    """Build a real Channel (not MagicMock) so hash_channel works."""
    from vystak.schema.channel import Channel, RouteRule
    from vystak.schema.common import ChannelType
    from vystak.schema.platform import Platform
    from vystak.schema.provider import Provider
    from vystak.schema.secret import Secret

    prov = Provider(name="azure", type="azure", config={})
    platform = Platform(name="aca", type="container-apps", provider=prov)
    return Channel(
        name=name,
        type=channel_type or ChannelType.CHAT,
        platform=platform,
        routes=[RouteRule(match={}, agent="test-agent")],
        secrets=[Secret(name="TEST_SECRET")],
    )


class TestAzureChannelPlan:
    def test_plan_channel_new(self):
        provider = AzureProvider()
        channel = _make_channel()
        plan = provider.plan_channel(channel, current_hash=None)
        assert plan.agent_name == "chat"
        assert len(plan.actions) == 1
        assert "Azure Container Apps" in plan.actions[0]

    def test_plan_channel_unchanged(self):
        from vystak.hash import hash_channel

        provider = AzureProvider()
        channel = _make_channel()
        current = hash_channel(channel).root
        plan = provider.plan_channel(channel, current_hash=current)
        assert plan.actions == []

    def test_plan_channel_update(self):
        provider = AzureProvider()
        channel = _make_channel()
        plan = provider.plan_channel(channel, current_hash="old-hash")
        assert "Update" in plan.actions[0]


class TestAzureChannelApply:
    @patch("vystak_provider_azure.provider.ProvisionGraph")
    @patch("vystak_provider_azure.provider.AzureProvider._create_docker_client")
    @patch("vystak_provider_azure.provider.get_credential")
    @patch("vystak_provider_azure.provider.get_subscription_id")
    @patch("vystak_provider_azure.provider.get_location")
    def test_apply_channel_builds_graph(
        self, mock_location, mock_sub, mock_cred, mock_docker, mock_graph_cls
    ):
        import vystak_channel_chat  # noqa: F401 — registers CHAT plugin

        mock_location.return_value = "eastus2"
        mock_sub.return_value = "sub-123"
        mock_cred.return_value = MagicMock()
        mock_docker.return_value = MagicMock()

        mock_graph = MagicMock()
        mock_graph_cls.return_value = mock_graph

        from vystak.provisioning.node import ProvisionResult

        mock_graph.execute.return_value = {
            "channel-app:chat": ProvisionResult(
                name="channel-app:chat",
                success=True,
                info={
                    "url": "https://channel-chat.eastus.azurecontainerapps.io",
                    "fqdn": "channel-chat.eastus.azurecontainerapps.io",
                    "app_name": "channel-chat",
                },
            ),
        }

        provider = AzureProvider()
        channel = _make_channel()

        plan = DeployPlan(
            agent_name="chat",
            actions=["Create new channel deployment on Azure Container Apps"],
            current_hash=None,
            target_hash="chan-hash-123",
            changes={"all": (None, "chan-hash-123")},
        )

        with patch.dict(
            "sys.modules",
            {
                "azure.mgmt.resource": MagicMock(),
                "azure.mgmt.loganalytics": MagicMock(),
                "azure.mgmt.containerregistry": MagicMock(),
                "azure.mgmt.appcontainers": MagicMock(),
            },
        ):
            result = provider.apply_channel(
                plan,
                channel,
                resolved_routes={"test-agent": "https://test-agent.example.com"},
            )

        assert result.success is True
        assert "chat" in result.message
        # RG + LogAnalytics + ACR + Env + AzureChannelAppNode = 5 nodes
        assert mock_graph.add.call_count == 5

    def test_apply_channel_unknown_plugin(self):
        from vystak.schema.channel import Channel, RouteRule
        from vystak.schema.common import ChannelType
        from vystak.schema.platform import Platform
        from vystak.schema.provider import Provider

        # Construct a channel with a type nobody registered.
        # ChannelType.VOICE — no plugin ships for it yet.
        prov = Provider(name="azure", type="azure", config={})
        platform = Platform(name="aca", type="container-apps", provider=prov)
        channel = Channel(
            name="voice",
            type=ChannelType.VOICE,
            platform=platform,
            routes=[RouteRule(agent="x")],
        )

        provider = AzureProvider()
        plan = DeployPlan(
            agent_name="voice",
            actions=["Create"],
            current_hash=None,
            target_hash="h",
            changes={},
        )
        result = provider.apply_channel(plan, channel, resolved_routes={})
        assert result.success is False
        assert "No plugin registered" in result.message


class TestAzureChannelAppNaming:
    def test_channel_app_name(self):
        provider = AzureProvider()
        assert provider._channel_app_name("chat") == "channel-chat"
        assert provider._channel_app_name("slack-main") == "channel-slack-main"

    def test_channel_rg_default(self):
        provider = AzureProvider()
        channel = _make_channel("my-chat")
        assert provider._channel_rg_name(channel) == "vystak-my-chat-rg"

    def test_channel_rg_override(self):
        provider = AzureProvider()
        channel = _make_channel("my-chat")
        channel.platform.provider.config = {"resource_group": "shared-rg"}
        assert provider._channel_rg_name(channel) == "shared-rg"
