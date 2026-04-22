"""Tests for WorkspaceSshKeygenNode — generates SSH keypairs and pushes to Vault."""

import pathlib
from unittest.mock import MagicMock

from vystak_provider_docker.nodes.workspace_ssh_keygen import WorkspaceSshKeygenNode


def _fake_keygen_side_effect(**kwargs):
    """Simulate the throwaway alpine writing the four files into the bind-mounted
    host tmpdir — real ssh-keygen is not available in unit tests."""
    bind = next(iter(kwargs["volumes"].keys()))
    out = pathlib.Path(bind)
    (out / "client-key").write_text("FAKE-CLIENT-PRIV\n")
    (out / "client-key.pub").write_text("ssh-ed25519 FAKE-CLIENT-PUB\n")
    (out / "host-key").write_text("FAKE-HOST-PRIV\n")
    (out / "host-key.pub").write_text("ssh-ed25519 FAKE-HOST-PUB\n")
    return MagicMock()


def test_generates_and_pushes_when_missing_from_vault():
    vault_client = MagicMock()
    vault_client.kv_get.return_value = None  # missing
    docker_client = MagicMock()
    docker_client.containers.run.side_effect = _fake_keygen_side_effect

    node = WorkspaceSshKeygenNode(
        vault_client=vault_client,
        docker_client=docker_client,
        agent_name="assistant",
    )
    result = node.provision(context={})
    # Four kv_put calls: client-key, host-key, client-key-pub, host-key-pub
    assert vault_client.kv_put.call_count == 4
    paths_put = {c.args[0] for c in vault_client.kv_put.call_args_list}
    assert paths_put == {
        "_vystak/workspace-ssh/assistant/client-key",
        "_vystak/workspace-ssh/assistant/host-key",
        "_vystak/workspace-ssh/assistant/client-key-pub",
        "_vystak/workspace-ssh/assistant/host-key-pub",
    }
    assert result.success is True


def test_skips_when_all_four_keys_present():
    vault_client = MagicMock()
    vault_client.kv_get.return_value = "existing-value"  # present
    docker_client = MagicMock()

    node = WorkspaceSshKeygenNode(
        vault_client=vault_client,
        docker_client=docker_client,
        agent_name="assistant",
    )
    node.provision(context={})
    vault_client.kv_put.assert_not_called()


def test_regenerates_when_some_missing():
    vault_client = MagicMock()

    # Only client-key exists, others missing
    def kv_get_side(name):
        return "val" if name.endswith("/client-key") else None

    vault_client.kv_get.side_effect = kv_get_side
    docker_client = MagicMock()
    docker_client.containers.run.side_effect = _fake_keygen_side_effect

    node = WorkspaceSshKeygenNode(
        vault_client=vault_client,
        docker_client=docker_client,
        agent_name="assistant",
    )
    node.provision(context={})
    # Any missing => regenerate ALL four (keypair integrity)
    assert vault_client.kv_put.call_count == 4
