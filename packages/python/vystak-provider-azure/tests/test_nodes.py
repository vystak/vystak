"""Tests for Azure provider node types."""

import os
from unittest.mock import MagicMock, patch

from vystak.provisioning.health import HttpHealthCheck, NoopHealthCheck
from vystak.provisioning.node import ProvisionResult
from vystak_provider_azure.nodes.aca_app import ContainerAppNode
from vystak_provider_azure.nodes.aca_channel_app import AzureChannelAppNode
from vystak_provider_azure.nodes.aca_environment import ACAEnvironmentNode
from vystak_provider_azure.nodes.acr import ACRNode
from vystak_provider_azure.nodes.log_analytics import LogAnalyticsNode
from vystak_provider_azure.nodes.resource_group import ResourceGroupNode

# ---------------------------------------------------------------------------
# ResourceGroup
# ---------------------------------------------------------------------------


class TestResourceGroupNode:
    def _make_node(self):
        client = MagicMock()
        return ResourceGroupNode(client, rg_name="test-rg", location="eastus", tags={"env": "test"})

    def test_name_and_deps(self):
        node = self._make_node()
        assert node.name == "resource-group"
        assert node.depends_on == []

    def test_provision_creates_rg(self):
        node = self._make_node()
        # Simulate RG does not exist
        node._client.resource_groups.check_existence.return_value = False
        result = node.provision({})
        assert result.success is True
        assert result.info["rg_name"] == "test-rg"
        assert result.info["created"] is True
        node._client.resource_groups.create_or_update.assert_called_once()

    def test_provision_existing_rg(self):
        node = self._make_node()
        node._client.resource_groups.check_existence.return_value = True
        result = node.provision({})
        assert result.success is True
        assert result.info["created"] is False

    def test_health_check(self):
        node = self._make_node()
        assert isinstance(node.health_check(), NoopHealthCheck)


# ---------------------------------------------------------------------------
# LogAnalytics
# ---------------------------------------------------------------------------


class TestLogAnalyticsNode:
    def _make_node(self):
        client = MagicMock()
        return LogAnalyticsNode(
            client, rg_name="test-rg", workspace_name="test-la", location="eastus"
        )

    def test_name_and_deps(self):
        node = self._make_node()
        assert node.name == "log-analytics"
        assert node.depends_on == ["resource-group"]

    def test_provision(self):
        node = self._make_node()
        workspace_result = MagicMock()
        workspace_result.customer_id = "cust-123"
        node._client.workspaces.begin_create_or_update.return_value.result.return_value = (
            workspace_result
        )

        keys_result = MagicMock()
        keys_result.primary_shared_key = "shared-key-abc"
        node._client.shared_keys.get_shared_keys.return_value = keys_result

        result = node.provision({})
        assert result.success is True
        assert result.info["customer_id"] == "cust-123"
        assert result.info["shared_key"] == "shared-key-abc"
        assert result.info["workspace_name"] == "test-la"

    def test_health_check(self):
        node = self._make_node()
        assert isinstance(node.health_check(), NoopHealthCheck)


# ---------------------------------------------------------------------------
# ACR
# ---------------------------------------------------------------------------


class TestACRNode:
    def _make_node(self, existing=False):
        client = MagicMock()
        return ACRNode(
            client, rg_name="test-rg", registry_name="testreg", location="eastus", existing=existing
        )

    def test_name_and_deps(self):
        node = self._make_node()
        assert node.name == "acr"
        assert node.depends_on == ["resource-group"]

    def test_provision_creates_registry(self):
        node = self._make_node()
        registry_result = MagicMock()
        registry_result.login_server = "testreg.azurecr.io"
        node._client.registries.begin_create.return_value.result.return_value = registry_result

        creds = MagicMock()
        creds.username = "testreg"
        creds.passwords = [MagicMock(value="secret-pass")]
        node._client.registries.list_credentials.return_value = creds

        result = node.provision({})
        assert result.success is True
        assert result.info["login_server"] == "testreg.azurecr.io"
        assert result.info["username"] == "testreg"
        assert result.info["password"] == "secret-pass"
        assert result.info["registry_name"] == "testreg"
        node._client.registries.begin_create.assert_called_once()

    def test_provision_existing_registry(self):
        node = self._make_node(existing=True)
        existing_reg = MagicMock()
        existing_reg.login_server = "testreg.azurecr.io"
        node._client.registries.get.return_value = existing_reg

        creds = MagicMock()
        creds.username = "testreg"
        creds.passwords = [MagicMock(value="secret-pass")]
        node._client.registries.list_credentials.return_value = creds

        result = node.provision({})
        assert result.success is True
        node._client.registries.begin_create.assert_not_called()

    def test_health_check(self):
        node = self._make_node()
        assert isinstance(node.health_check(), NoopHealthCheck)


# ---------------------------------------------------------------------------
# ACA Environment
# ---------------------------------------------------------------------------


class TestACAEnvironmentNode:
    def _make_node(self, existing=False):
        client = MagicMock()
        return ACAEnvironmentNode(
            client, rg_name="test-rg", env_name="test-env", location="eastus", existing=existing
        )

    def test_name_and_deps(self):
        node = self._make_node()
        assert node.name == "aca-environment"
        assert node.depends_on == ["resource-group", "log-analytics"]

    def test_provision(self):
        node = self._make_node()
        env_result = MagicMock()
        env_result.id = (
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.App/managedEnvironments/test-env"
        )
        env_result.default_domain = "test-env.eastus.azurecontainerapps.io"
        begin = node._client.managed_environments.begin_create_or_update
        begin.return_value.result.return_value = env_result

        context = {
            "log-analytics": ProvisionResult(
                name="log-analytics",
                success=True,
                info={"customer_id": "cust-123", "shared_key": "key-abc", "workspace_name": "ws"},
            ),
        }
        result = node.provision(context)
        assert result.success is True
        assert result.info["environment_id"] == env_result.id
        assert result.info["default_domain"] == "test-env.eastus.azurecontainerapps.io"

    def test_provision_existing(self):
        node = self._make_node(existing=True)
        existing_env = MagicMock()
        existing_env.id = "/subscriptions/sub/providers/Microsoft.App/managedEnvironments/test-env"
        existing_env.default_domain = "test-env.eastus.azurecontainerapps.io"
        node._client.managed_environments.get.return_value = existing_env

        result = node.provision({})
        assert result.success is True
        node._client.managed_environments.begin_create_or_update.assert_not_called()

    def test_health_check(self):
        node = self._make_node()
        assert isinstance(node.health_check(), NoopHealthCheck)


# ---------------------------------------------------------------------------
# ContainerApp
# ---------------------------------------------------------------------------


class TestContainerAppNode:
    def _make_agent(self):
        agent = MagicMock()
        agent.name = "my-agent"
        agent.mcp_servers = []
        secret1 = MagicMock()
        secret1.name = "API_KEY"
        secret2 = MagicMock()
        secret2.name = "DB_PASS"
        agent.secrets = [secret1, secret2]
        agent.sessions = None
        agent.memory = None
        return agent

    def _make_node(self):
        aca_client = MagicMock()
        docker_client = MagicMock()
        agent = self._make_agent()
        generated_code = MagicMock()
        generated_code.files = {"main.py": "print('hello')", "requirements.txt": "fastapi"}
        generated_code.entrypoint = "main.py"
        plan = MagicMock()
        plan.target_hash = "abc123"
        platform_config = {
            "min_replicas": 0,
            "max_replicas": 3,
            "cpu": "0.5",
            "memory": "1Gi",
            "ingress_external": True,
            "port": 8000,
        }
        return ContainerAppNode(
            aca_client=aca_client,
            docker_client=docker_client,
            rg_name="test-rg",
            agent=agent,
            generated_code=generated_code,
            plan=plan,
            platform_config=platform_config,
        )

    def test_name_and_deps(self):
        node = self._make_node()
        assert node.name == "container-app"
        assert node.depends_on == ["aca-environment", "acr"]

    @patch.dict(os.environ, {"API_KEY": "key-val", "DB_PASS": "db-val"})
    @patch("vystak_provider_azure.nodes.aca_app.subprocess.run")
    def test_provision(self, mock_subprocess, tmp_path):
        node = self._make_node()

        # Mock subprocess (docker login + docker buildx)
        mock_subprocess.return_value = MagicMock(returncode=0, stderr="")

        # Mock ACA client
        app_result = MagicMock()
        app_result.configuration.ingress.fqdn = "my-agent.eastus.azurecontainerapps.io"
        node._aca_client.container_apps.begin_create_or_update.return_value.result.return_value = (
            app_result
        )

        context = {
            "aca-environment": ProvisionResult(
                name="aca-environment",
                success=True,
                info={"environment_id": "/sub/env-id", "default_domain": "test.io"},
            ),
            "acr": ProvisionResult(
                name="acr",
                success=True,
                info={
                    "login_server": "testreg.azurecr.io",
                    "username": "testreg",
                    "password": "secret-pass",
                    "registry_name": "testreg",
                },
            ),
        }

        with patch("vystak_provider_azure.nodes.aca_app.Path") as mock_path_cls, \
             patch("shutil.copytree") as _copytree, \
             patch("shutil.rmtree") as _rmtree:  # noqa: F841 — suppress vystak-source bundling
            mock_build_dir = MagicMock()
            mock_path_cls.return_value.__truediv__ = lambda self, other: mock_build_dir
            mock_build_dir.__truediv__ = lambda self, other: MagicMock()
            mock_build_dir.mkdir = MagicMock()
            mock_build_dir.__str__ = lambda self: "/tmp/fake-build"

            result = node.provision(context)

        assert result.success is True
        assert result.info["fqdn"] == "my-agent.eastus.azurecontainerapps.io"
        assert result.info["url"] == "https://my-agent.eastus.azurecontainerapps.io"
        assert result.info["app_name"] == "my-agent"
        # Verify subprocess was called for docker login and buildx
        assert mock_subprocess.call_count == 2

        # Verify transport env vars are injected
        create_call = node._aca_client.container_apps.begin_create_or_update
        container_app = create_call.call_args[0][2]
        env_list = container_app.template.containers[0].env
        env_names = [e["name"] if isinstance(e, dict) else e.name for e in env_list]
        assert "VYSTAK_TRANSPORT_TYPE" in env_names
        assert "VYSTAK_ROUTES_JSON" in env_names
        # Verify VYSTAK_ROUTES_JSON defaults to "{}" when peer_routes_json not specified
        routes_entry = next(
            e
            for e in env_list
            if (e["name"] if isinstance(e, dict) else e.name) == "VYSTAK_ROUTES_JSON"
        )
        routes_value = (
            routes_entry["value"] if isinstance(routes_entry, dict) else routes_entry.value
        )
        assert routes_value == "{}"

    def test_health_check(self):
        node = self._make_node()
        # health_check needs context info; set the fqdn
        node._fqdn = "my-agent.eastus.azurecontainerapps.io"
        hc = node.health_check()
        assert isinstance(hc, HttpHealthCheck)

    @patch.dict(os.environ, {"API_KEY": "key-val", "DB_PASS": "db-val"})
    @patch("vystak_provider_azure.nodes.aca_app.subprocess.run")
    def test_provision_with_postgres_env_vars(self, mock_subprocess, tmp_path):
        node = self._make_node()

        # Give the agent sessions and memory fields
        sessions_svc = MagicMock()
        sessions_svc.name = "sessions-db"
        sessions_svc.connection_string_env = None
        sessions_svc.is_managed = True
        memory_svc = MagicMock()
        memory_svc.name = "memory-db"
        memory_svc.connection_string_env = None
        memory_svc.is_managed = True
        node._agent.sessions = sessions_svc
        node._agent.memory = memory_svc
        node._agent.services = []

        mock_subprocess.return_value = MagicMock(returncode=0, stderr="")

        app_result = MagicMock()
        app_result.configuration.ingress.fqdn = "my-agent.eastus.azurecontainerapps.io"
        node._aca_client.container_apps.begin_create_or_update.return_value.result.return_value = (
            app_result
        )

        context = {
            "aca-environment": ProvisionResult(
                name="aca-environment",
                success=True,
                info={"environment_id": "/sub/env-id", "default_domain": "test.io"},
            ),
            "acr": ProvisionResult(
                name="acr",
                success=True,
                info={
                    "login_server": "testreg.azurecr.io",
                    "username": "testreg",
                    "password": "secret-pass",
                    "registry_name": "testreg",
                },
            ),
            "sessions-db": ProvisionResult(
                name="sessions-db",
                success=True,
                info={
                    "engine": "postgres",
                    "connection_string": "postgresql://vystak:pw@host:5432/vystak?sslmode=require",
                },
            ),
            "memory-db": ProvisionResult(
                name="memory-db",
                success=True,
                info={
                    "engine": "postgres",
                    "connection_string": "postgresql://vystak:pw2@host2:5432/vystak?sslmode=require",
                },
            ),
        }

        with patch("vystak_provider_azure.nodes.aca_app.Path") as mock_path_cls, \
             patch("shutil.copytree") as _copytree, \
             patch("shutil.rmtree") as _rmtree:  # noqa: F841
            mock_build_dir = MagicMock()
            mock_path_cls.return_value.__truediv__ = lambda self, other: mock_build_dir
            mock_build_dir.__truediv__ = lambda self, other: MagicMock()
            mock_build_dir.mkdir = MagicMock()
            mock_build_dir.__str__ = lambda self: "/tmp/fake-build"
            result = node.provision(context)

        assert result.success is True

        # Verify the ContainerApp was created with correct secrets and env vars
        create_call = node._aca_client.container_apps.begin_create_or_update
        call_args = create_call.call_args
        container_app = call_args[0][2]  # Third positional arg is the ContainerApp object

        # Check secrets contain session-store-url and memory-store-url
        secret_names = [s.name for s in container_app.configuration.secrets]
        assert "session-store-url" in secret_names
        assert "memory-store-url" in secret_names

        # Check env vars reference the secrets
        env_list = container_app.template.containers[0].env
        env_names = [e["name"] if isinstance(e, dict) else e.name for e in env_list]
        assert "SESSION_STORE_URL" in env_names
        assert "MEMORY_STORE_URL" in env_names


# ---------------------------------------------------------------------------
# AzureChannelAppNode
# ---------------------------------------------------------------------------


class TestAzureChannelAppNode:
    def _make_node(self, generated_code=None, platform_config=None):
        from vystak.providers.base import DeployPlan, GeneratedCode
        from vystak.schema.channel import Channel
        from vystak.schema.common import ChannelType
        from vystak.schema.platform import Platform
        from vystak.schema.provider import Provider
        from vystak.schema.secret import Secret

        prov = Provider(name="azure", type="azure", config={})
        platform = Platform(name="aca", type="container-apps", provider=prov)
        channel = Channel(
            name="chat",
            type=ChannelType.CHAT,
            platform=platform,
            secrets=[Secret(name="SLACK_BOT_TOKEN")],
            config={"port": 8080},
        )
        plan = DeployPlan(
            agent_name="chat",
            actions=["Create"],
            current_hash=None,
            target_hash="hash-abc",
            changes={},
        )
        code = generated_code or GeneratedCode(
            files={
                "server.py": "# stub\n",
                "Dockerfile": "FROM python:3.11-slim\nWORKDIR /app\n",
                "requirements.txt": "fastapi\n",
                "routes.json": "{}\n",
            },
            entrypoint="server.py",
        )
        return AzureChannelAppNode(
            aca_client=MagicMock(),
            docker_client=MagicMock(),
            rg_name="test-rg",
            channel=channel,
            generated_code=code,
            plan=plan,
            platform_config=platform_config or {"location": "eastus2"},
        )

    def test_name_and_deps(self):
        node = self._make_node()
        assert node.name == "channel-app:chat"
        assert "aca-environment" in node.depends_on
        assert "acr" in node.depends_on

    def test_health_check_noop_before_provision(self):
        node = self._make_node()
        assert isinstance(node.health_check(), NoopHealthCheck)

    def test_health_check_http_after_provision(self):
        node = self._make_node()
        node._fqdn = "channel-chat.example.azurecontainerapps.io"
        hc = node.health_check()
        assert isinstance(hc, HttpHealthCheck)

    @patch("subprocess.run")
    def test_provision_rewrites_dockerfile_platform(self, mock_subproc, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_subproc.return_value = MagicMock(returncode=0)
        node = self._make_node()

        context = {
            "acr": ProvisionResult(
                name="acr",
                success=True,
                info={
                    "login_server": "test.azurecr.io",
                    "username": "user",
                    "password": "pw",
                },
            ),
            "aca-environment": ProvisionResult(
                name="aca-environment",
                success=True,
                info={"environment_id": "/subs/env-id"},
            ),
        }

        fake_app = MagicMock()
        fake_app.configuration.ingress.fqdn = "channel-chat.example.io"
        node._aca_client.container_apps.begin_create_or_update.return_value.result.return_value = (
            fake_app
        )

        result = node.provision(context)
        assert result.success is True
        dockerfile = (tmp_path / ".vystak" / "channels" / "chat" / "Dockerfile").read_text()
        assert "FROM --platform=linux/amd64 python:3.11-slim" in dockerfile

    @patch("subprocess.run")
    def test_provision_injects_secrets_and_port_env(self, mock_subproc, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-mock-test")
        mock_subproc.return_value = MagicMock(returncode=0)
        node = self._make_node()

        context = {
            "acr": ProvisionResult(
                name="acr",
                success=True,
                info={
                    "login_server": "test.azurecr.io",
                    "username": "user",
                    "password": "pw",
                },
            ),
            "aca-environment": ProvisionResult(
                name="aca-environment",
                success=True,
                info={"environment_id": "/subs/env-id"},
            ),
        }

        fake_app = MagicMock()
        fake_app.configuration.ingress.fqdn = "channel-chat.example.io"
        node._aca_client.container_apps.begin_create_or_update.return_value.result.return_value = (
            fake_app
        )

        node.provision(context)
        create_call = node._aca_client.container_apps.begin_create_or_update
        container_app = create_call.call_args[0][2]

        secret_names = [s.name for s in container_app.configuration.secrets]
        assert "acr-password" in secret_names
        assert "slack-bot-token" in secret_names

        env_list = container_app.template.containers[0].env
        env_map = {e["name"]: e for e in env_list}
        assert "SLACK_BOT_TOKEN" in env_map
        assert env_map["SLACK_BOT_TOKEN"]["secretRef"] == "slack-bot-token"
        assert env_map["PORT"]["value"] == "8080"

        assert container_app.tags["vystak:channel"] == "chat"
        assert container_app.tags["vystak:channel-hash"] == "hash-abc"
        assert container_app.tags["vystak:channel-type"] == "chat"
