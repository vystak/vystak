from unittest.mock import MagicMock, patch

from vystak_provider_azure.nodes.workspace_ssh_keygen import (
    AzureWorkspaceSshKeygenNode,
    _kv_secret_name,
)


def test_kv_secret_names_match_spec():
    """Spec mandates these exact KV secret names (dashes, not slashes)."""
    assert _kv_secret_name("assistant", "client-key") == (
        "vystak-workspace-ssh-assistant-client-key"
    )
    assert _kv_secret_name("assistant", "host-key") == (
        "vystak-workspace-ssh-assistant-host-key"
    )
    assert _kv_secret_name("assistant", "client-key-pub") == (
        "vystak-workspace-ssh-assistant-client-key-pub"
    )
    assert _kv_secret_name("assistant", "host-key-pub") == (
        "vystak-workspace-ssh-assistant-host-key-pub"
    )


def test_provision_pushes_four_secrets_to_keyvault():
    """First provision generates keys and uploads all 4 to KV."""
    secret_client = MagicMock()
    secret_client.get_secret.side_effect = Exception("ResourceNotFound")
    docker_client = MagicMock()

    node = AzureWorkspaceSshKeygenNode(
        agent_name="assistant",
        secret_client=secret_client,
        docker_client=docker_client,
    )

    with patch.object(
        node,
        "_keygen_via_docker",
        return_value=("CLIENT_PRIV", "CLIENT_PUB", "HOST_PRIV", "HOST_PUB"),
    ):
        result = node.provision({})

    assert result.success is True
    assert result.info["regenerated"] is True
    assert secret_client.set_secret.call_count == 4
    set_calls = {
        c.args[0]: c.args[1] for c in secret_client.set_secret.call_args_list
    }
    assert set_calls["vystak-workspace-ssh-assistant-client-key"] == "CLIENT_PRIV"
    assert set_calls["vystak-workspace-ssh-assistant-client-key-pub"] == "CLIENT_PUB"
    assert set_calls["vystak-workspace-ssh-assistant-host-key"] == "HOST_PRIV"
    assert set_calls["vystak-workspace-ssh-assistant-host-key-pub"] == "HOST_PUB"


def test_provision_idempotent_when_all_four_keys_exist():
    """Second provision is a no-op when all 4 secrets already in KV."""
    secret_client = MagicMock()
    secret_client.get_secret.return_value = MagicMock(value="exists")
    docker_client = MagicMock()

    node = AzureWorkspaceSshKeygenNode(
        agent_name="assistant",
        secret_client=secret_client,
        docker_client=docker_client,
    )

    with patch.object(node, "_keygen_via_docker") as mock_keygen:
        result = node.provision({})

    assert result.success is True
    assert result.info["regenerated"] is False
    mock_keygen.assert_not_called()
    secret_client.set_secret.assert_not_called()
