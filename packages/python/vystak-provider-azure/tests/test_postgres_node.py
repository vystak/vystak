"""Tests for AzurePostgresNode."""

import re
from unittest.mock import MagicMock, patch

import pytest

from vystak.provisioning.health import NoopHealthCheck, TcpHealthCheck
from vystak.provisioning.node import ProvisionResult

from vystak_provider_azure.nodes.postgres import AzurePostgresNode


class TestAzurePostgresNode:
    def _make_node(self, server_name="test-rg-main-db", service_name="main-db", config=None):
        client = MagicMock()
        return AzurePostgresNode(
            client=client,
            rg_name="test-rg",
            server_name=server_name,
            service_name=service_name,
            location="eastus2",
            admin_password="test-secret-pw",
            config=config or {},
            tags={"vystak:managed": "true"},
        )

    def test_name(self):
        node = self._make_node()
        assert node.name == "main-db"

    def test_depends_on(self):
        node = self._make_node()
        assert node.depends_on == ["resource-group"]

    def test_provision_creates_server(self):
        node = self._make_node()

        from azure.core.exceptions import ResourceNotFoundError
        node._client.servers.get.side_effect = ResourceNotFoundError("not found")

        server_result = MagicMock()
        server_result.state = "Ready"
        server_result.fully_qualified_domain_name = "test-rg-main-db.postgres.database.azure.com"
        node._client.servers.begin_create.return_value.result.return_value = server_result

        node._client.firewall_rules.begin_create_or_update.return_value.result.return_value = MagicMock()
        node._client.databases.begin_create.return_value.result.return_value = MagicMock()

        result = node.provision({"resource-group": ProvisionResult(name="resource-group", success=True, info={"rg_name": "test-rg"})})

        assert result.success is True
        assert result.info["engine"] == "postgres"
        assert result.info["server_name"] == "test-rg-main-db"
        assert result.info["host"] == "test-rg-main-db.postgres.database.azure.com"
        assert "connection_string" in result.info
        assert "sslmode=require" in result.info["connection_string"]
        assert "vystak:test-secret-pw@" in result.info["connection_string"]

        node._client.servers.begin_create.assert_called_once()
        node._client.firewall_rules.begin_create_or_update.assert_called_once()
        node._client.databases.begin_create.assert_called_once()

    def test_provision_reuses_existing_server(self):
        node = self._make_node()

        existing = MagicMock()
        existing.state = "Ready"
        existing.fully_qualified_domain_name = "test-rg-main-db.postgres.database.azure.com"
        node._client.servers.get.return_value = existing

        node._client.databases.begin_create.return_value.result.return_value = MagicMock()

        result = node.provision({"resource-group": ProvisionResult(name="resource-group", success=True, info={"rg_name": "test-rg"})})

        assert result.success is True
        assert result.info["host"] == "test-rg-main-db.postgres.database.azure.com"
        node._client.servers.begin_create.assert_not_called()

    def test_provision_with_custom_config(self):
        node = self._make_node(config={
            "sku": "Standard_B2s",
            "version": "15",
            "storage_gb": 64,
            "backup_retention_days": 14,
        })

        from azure.core.exceptions import ResourceNotFoundError
        node._client.servers.get.side_effect = ResourceNotFoundError("not found")

        server_result = MagicMock()
        server_result.state = "Ready"
        server_result.fully_qualified_domain_name = "test-rg-main-db.postgres.database.azure.com"
        node._client.servers.begin_create.return_value.result.return_value = server_result
        node._client.firewall_rules.begin_create_or_update.return_value.result.return_value = MagicMock()
        node._client.databases.begin_create.return_value.result.return_value = MagicMock()

        result = node.provision({"resource-group": ProvisionResult(name="resource-group", success=True, info={"rg_name": "test-rg"})})
        assert result.success is True

        call_args = node._client.servers.begin_create.call_args
        server_params = call_args[0][2]
        assert server_params.sku.name == "Standard_B2s"
        assert server_params.version == "15"
        assert server_params.storage.storage_size_gb == 64
        assert server_params.backup.backup_retention_days == 14

    def test_provision_error(self):
        node = self._make_node()

        from azure.core.exceptions import ResourceNotFoundError
        node._client.servers.get.side_effect = ResourceNotFoundError("not found")
        node._client.servers.begin_create.side_effect = Exception("Azure API error")

        result = node.provision({"resource-group": ProvisionResult(name="resource-group", success=True, info={"rg_name": "test-rg"})})
        assert result.success is False
        assert "Azure API error" in result.error

    def test_health_check_always_noop(self):
        node = self._make_node()
        node._host = "test-rg-main-db.postgres.database.azure.com"
        hc = node.health_check()
        assert isinstance(hc, NoopHealthCheck)

    def test_health_check_without_host(self):
        node = self._make_node()
        hc = node.health_check()
        assert isinstance(hc, NoopHealthCheck)
