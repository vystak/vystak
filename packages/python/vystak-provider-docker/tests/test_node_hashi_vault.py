"""Tests for Vault server/init/unseal nodes."""

from unittest.mock import MagicMock

import pytest
from vystak_provider_docker.nodes.hashi_vault import (
    HashiVaultInitNode,
    HashiVaultServerNode,
    HashiVaultUnsealNode,
)


def _fake_docker_client():
    client = MagicMock()
    existing_volume = MagicMock()
    client.volumes.get.return_value = existing_volume
    client.containers.get.side_effect = __import__(
        "docker.errors", fromlist=["NotFound"]
    ).NotFound("not found")
    return client


def test_server_node_starts_container_with_persistent_volume(tmp_path):
    client = _fake_docker_client()
    node = HashiVaultServerNode(
        client=client,
        image="hashicorp/vault:1.17",
        port=8200,
        host_port=None,
    )
    result = node.provision(
        context={"network": MagicMock(info={"network": MagicMock(name="vystak-net")})}
    )
    client.volumes.create.assert_called_once_with(name="vystak-vault-data")
    client.containers.run.assert_called_once()
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["name"] == "vystak-vault"
    assert kwargs["detach"] is True
    assert kwargs["image"] == "hashicorp/vault:1.17"
    # Volume mount
    volumes = kwargs.get("volumes") or {}
    assert "vystak-vault-data" in volumes
    assert volumes["vystak-vault-data"]["bind"] == "/vault/file"
    assert result.success is True


def test_server_node_reuses_existing_container_if_running():
    client = MagicMock()
    running = MagicMock()
    running.status = "running"
    client.containers.get.return_value = running
    node = HashiVaultServerNode(
        client=client, image="hashicorp/vault:1.17", port=8200, host_port=None
    )
    result = node.provision(
        context={"network": MagicMock(info={"network": MagicMock(name="vystak-net")})}
    )
    client.containers.run.assert_not_called()
    assert result.info["vault_address"] == "http://vystak-vault:8200"
    assert result.success is True


def test_init_node_writes_init_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_vc = MagicMock()
    fake_vc.is_initialized.return_value = False
    from vystak_provider_docker.vault_client import VaultInitResult

    fake_vc.initialize.return_value = VaultInitResult(
        unseal_keys=["k1", "k2", "k3", "k4", "k5"],
        root_token="hvs.xxx",
    )
    node = HashiVaultInitNode(
        vault_client=fake_vc,
        key_shares=5,
        key_threshold=3,
        init_path=tmp_path / ".vystak/vault/init.json",
    )
    result = node.provision(context={})
    init_path = tmp_path / ".vystak/vault/init.json"
    assert init_path.exists()
    import json

    data = json.loads(init_path.read_text())
    assert data["root_token"] == "hvs.xxx"
    assert len(data["unseal_keys_b64"]) == 5
    assert (init_path.stat().st_mode & 0o777) == 0o600
    assert result.info["root_token"] == "hvs.xxx"
    assert result.info["unseal_keys"] == ["k1", "k2", "k3", "k4", "k5"]


def test_init_node_skips_when_already_initialized(tmp_path):
    init_path = tmp_path / ".vystak/vault/init.json"
    init_path.parent.mkdir(parents=True)
    import json

    init_path.write_text(
        json.dumps({"root_token": "existing", "unseal_keys_b64": ["k1", "k2", "k3", "k4", "k5"]})
    )
    init_path.chmod(0o600)
    fake_vc = MagicMock()
    fake_vc.is_initialized.return_value = True
    node = HashiVaultInitNode(
        vault_client=fake_vc, key_shares=5, key_threshold=3, init_path=init_path
    )
    result = node.provision(context={})
    fake_vc.initialize.assert_not_called()
    assert result.info["root_token"] == "existing"


def test_init_node_raises_when_vault_initialized_but_init_json_missing(tmp_path):
    fake_vc = MagicMock()
    fake_vc.is_initialized.return_value = True
    node = HashiVaultInitNode(
        vault_client=fake_vc, key_shares=5, key_threshold=3,
        init_path=tmp_path / "does-not-exist.json",
    )
    with pytest.raises(RuntimeError, match="state mismatch"):
        node.provision(context={})


def test_unseal_node_submits_threshold_keys():
    fake_vc = MagicMock()
    fake_vc.is_sealed.return_value = True
    node = HashiVaultUnsealNode(
        vault_client=fake_vc,
        unseal_keys=["k1", "k2", "k3", "k4", "k5"],
        key_threshold=3,
    )
    result = node.provision(context={})
    fake_vc.unseal.assert_called_once_with(["k1", "k2", "k3"])
    assert result.success is True


def test_unseal_node_skips_when_unsealed():
    fake_vc = MagicMock()
    fake_vc.is_sealed.return_value = False
    node = HashiVaultUnsealNode(
        vault_client=fake_vc, unseal_keys=["k1", "k2", "k3"], key_threshold=3
    )
    result = node.provision(context={})
    fake_vc.unseal.assert_not_called()
    assert result.success is True
