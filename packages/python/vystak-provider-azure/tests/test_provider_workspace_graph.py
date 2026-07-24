"""Verifies that AzureProvider._add_workspace_nodes wires the standalone
workspace subgraph correctly."""

from unittest.mock import MagicMock

import pytest
from vystak_provider_azure.provider import AzureProvider


def _make_provider_for(agent) -> AzureProvider:
    provider = AzureProvider()
    provider.set_agent(agent)
    return provider


def _agent_with_workspace(persistence: str, include_storage_account: bool = True):
    """Build a test Agent with workspace declared."""
    from vystak.schema import Agent, Model, Platform, Provider, Workspace

    config: dict = {
        "subscription_id": "sub-test",
        "resource_group": "rg-test",
        "location": "eastus",
    }
    if include_storage_account:
        config["storage_account"] = "mystorage"

    return Agent(
        name="assistant",
        framework="langchain-python",
        default_model=Model(
            name="claude",
            model_name="claude-3",
            provider=Provider(name="anthropic", type="anthropic"),
        ),
        platform=Platform(
            name="aca",
            type="container-apps",
            provider=Provider(name="azure", type="azure"),
            config=config,
        ),
        workspace=Workspace(
            name="dev",
            persistence=persistence,
        ),
    )


def test_add_workspace_nodes_includes_all_four_when_volume():
    provider = _make_provider_for(_agent_with_workspace("volume"))
    graph = MagicMock()

    workspace_app_name, ssh_secrets = provider._add_workspace_nodes(
        graph=graph,
        agent=provider._agent,
        rg_name="rg-test",
        env_name="env-test",
        acr_name="acrtest",
        vault_node_name="vault-test",
        workspace_identity_key="ws-id",
        location="eastus",
        cfg=provider._agent.platform.config,
        aca_client=MagicMock(),
        docker_client=MagicMock(),
        secret_client=MagicMock(),
        storage_client=MagicMock(),
    )

    added_node_types = [
        type(call.args[0]).__name__ for call in graph.add.call_args_list
    ]
    assert "AzureWorkspaceSshKeygenNode" in added_node_types
    assert "AzureFilesShareNode" in added_node_types
    assert "ACAEnvStorageNode" in added_node_types
    assert "ACAWorkspaceAppNode" in added_node_types
    assert workspace_app_name is not None
    assert ssh_secrets == [
        "vystak-workspace-ssh-assistant-client-key",
        "vystak-workspace-ssh-assistant-host-key-pub",
    ]


def test_add_workspace_nodes_skips_share_when_ephemeral():
    provider = _make_provider_for(_agent_with_workspace("ephemeral"))
    graph = MagicMock()

    provider._add_workspace_nodes(
        graph=graph,
        agent=provider._agent,
        rg_name="rg-test",
        env_name="env-test",
        acr_name="acrtest",
        vault_node_name="vault-test",
        workspace_identity_key="ws-id",
        location="eastus",
        cfg=provider._agent.platform.config,
        aca_client=MagicMock(),
        docker_client=MagicMock(),
        secret_client=MagicMock(),
        storage_client=MagicMock(),
    )

    added_node_types = [
        type(call.args[0]).__name__ for call in graph.add.call_args_list
    ]
    assert "AzureFilesShareNode" not in added_node_types
    assert "ACAEnvStorageNode" not in added_node_types
    assert "ACAWorkspaceAppNode" in added_node_types


def test_add_workspace_nodes_raises_when_volume_without_storage_account():
    provider = _make_provider_for(
        _agent_with_workspace("volume", include_storage_account=False)
    )
    graph = MagicMock()

    with pytest.raises(ValueError, match="storage_account"):
        provider._add_workspace_nodes(
            graph=graph,
            agent=provider._agent,
            rg_name="rg-test",
            env_name="env-test",
            acr_name="acrtest",
            vault_node_name="vault-test",
            workspace_identity_key="ws-id",
            location="eastus",
            cfg=provider._agent.platform.config,
            aca_client=MagicMock(),
            docker_client=MagicMock(),
            secret_client=MagicMock(),
            storage_client=MagicMock(),
        )


def test_add_workspace_nodes_returns_none_when_no_workspace():
    """When agent.workspace is None, no nodes are added and helper returns (None, [])."""
    from vystak.schema import Agent, Model, Platform, Provider

    agent = Agent(
        name="bare",
        framework="langchain-python",
        default_model=Model(
            name="claude",
            model_name="claude-3",
            provider=Provider(name="anthropic", type="anthropic"),
        ),
        platform=Platform(
            name="aca",
            type="container-apps",
            provider=Provider(name="azure", type="azure"),
            config={
                "subscription_id": "sub-test",
                "resource_group": "rg-test",
                "location": "eastus",
            },
        ),
    )
    provider = _make_provider_for(agent)
    graph = MagicMock()

    name, secrets = provider._add_workspace_nodes(
        graph=graph,
        agent=agent,
        rg_name="rg-test",
        env_name="env-test",
        acr_name="acrtest",
        vault_node_name="",
        workspace_identity_key=None,
        location="eastus",
        cfg=agent.platform.config,
        aca_client=MagicMock(),
        docker_client=MagicMock(),
        secret_client=MagicMock(),
        storage_client=MagicMock(),
    )

    assert name is None
    assert secrets == []
    graph.add.assert_not_called()


def _agent_with_volume(volume):
    """Like _agent_with_workspace but referencing a named Volume."""
    from vystak.schema import Agent, Model, Platform, Provider, Workspace

    return Agent(
        name="assistant",
        framework="langchain-python",
        default_model=Model(
            name="claude",
            model_name="claude-3",
            provider=Provider(name="anthropic", type="anthropic"),
        ),
        platform=Platform(
            name="aca",
            type="container-apps",
            provider=Provider(name="azure", type="azure"),
            config={
                "subscription_id": "sub-test",
                "resource_group": "rg-test",
                "location": "eastus",
                "storage_account": "mystorage",
            },
        ),
        workspace=Workspace(name="dev", volume=volume),
    )


def _run_add_workspace_nodes(provider, graph, **client_overrides):
    clients = {
        "aca_client": MagicMock(),
        "docker_client": MagicMock(),
        "secret_client": MagicMock(),
        "storage_client": MagicMock(),
    }
    clients.update(client_overrides)
    return provider._add_workspace_nodes(
        graph=graph,
        agent=provider._agent,
        rg_name="rg-test",
        env_name="env-test",
        acr_name="acrtest",
        vault_node_name="vault-test",
        workspace_identity_key="ws-id",
        location="eastus",
        cfg=provider._agent.platform.config,
        **clients,
    )


def _added_node_names(graph):
    return [call.args[0].name for call in graph.add.call_args_list]


def test_named_volume_share_name():
    from vystak.schema.volume import Volume

    provider = _make_provider_for(_agent_with_volume(Volume(name="team-code")))
    graph = MagicMock()
    _run_add_workspace_nodes(provider, graph)
    assert "files-share-vystak-volume-team-code" in _added_node_names(graph)


def test_implicit_volume_keeps_legacy_share_name():
    provider = _make_provider_for(_agent_with_workspace("volume"))
    graph = MagicMock()
    _run_add_workspace_nodes(provider, graph)
    assert "files-share-vystak-assistant-workspace-data" in _added_node_names(graph)


def _premium_clients(kind="FileStorage", subnet="subnet-id"):
    storage_client = MagicMock()
    storage_client.storage_accounts.get_properties.return_value = MagicMock(
        kind=kind
    )
    aca_client = MagicMock()
    aca_client.managed_environments.get.return_value = MagicMock(
        vnet_configuration=(
            MagicMock(infrastructure_subnet_id=subnet) if subnet else None
        )
    )
    return storage_client, aca_client


def test_premium_volume_requires_filestorage_account():
    from vystak.schema.volume import Volume

    provider = _make_provider_for(
        _agent_with_volume(Volume(name="fast", performance="premium"))
    )
    storage_client, aca_client = _premium_clients(kind="StorageV2")
    with pytest.raises(ValueError, match="kind='FileStorage'"):
        _run_add_workspace_nodes(
            provider, MagicMock(),
            storage_client=storage_client, aca_client=aca_client,
        )


def test_premium_volume_requires_vnet_injected_environment():
    from vystak.schema.volume import Volume

    provider = _make_provider_for(
        _agent_with_volume(Volume(name="fast", performance="premium"))
    )
    storage_client, aca_client = _premium_clients(subnet=None)
    with pytest.raises(ValueError, match="VNet"):
        _run_add_workspace_nodes(
            provider, MagicMock(),
            storage_client=storage_client, aca_client=aca_client,
        )


def test_premium_volume_wires_nfs_protocol():
    from vystak.schema.volume import Volume
    from vystak_provider_azure.nodes.aca_env_storage import ACAEnvStorageNode
    from vystak_provider_azure.nodes.files_share import AzureFilesShareNode

    provider = _make_provider_for(
        _agent_with_volume(Volume(name="fast", performance="premium"))
    )
    storage_client, aca_client = _premium_clients()
    graph = MagicMock()
    _run_add_workspace_nodes(
        provider, graph,
        storage_client=storage_client, aca_client=aca_client,
    )
    added = [call.args[0] for call in graph.add.call_args_list]
    share = next(n for n in added if isinstance(n, AzureFilesShareNode))
    env_storage = next(n for n in added if isinstance(n, ACAEnvStorageNode))
    assert share._enabled_protocols == "NFS"
    assert env_storage._protocol == "NFS"


def test_premium_volume_missing_storage_account_raises_actionable_error():
    """The premium precheck (get_properties) hits Azure before the
    AzureFilesShareNode's own precheck runs — its ResourceNotFoundError
    must be turned into the same actionable ValueError style, not left to
    bubble up as an opaque Azure SDK error."""
    from azure.core.exceptions import ResourceNotFoundError
    from vystak.schema.volume import Volume

    provider = _make_provider_for(
        _agent_with_volume(Volume(name="fast", performance="premium"))
    )
    storage_client, aca_client = _premium_clients()
    storage_client.storage_accounts.get_properties.side_effect = (
        ResourceNotFoundError("not found")
    )

    with pytest.raises(ValueError, match="not found"):
        _run_add_workspace_nodes(
            provider, MagicMock(),
            storage_client=storage_client, aca_client=aca_client,
        )
