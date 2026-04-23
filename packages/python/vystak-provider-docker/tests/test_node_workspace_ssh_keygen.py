"""Tests for WorkspaceSshKeygenNode — generates SSH keypairs (Vault and default paths)."""

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


def _make_mock_docker_client():
    """Returns a mock docker client whose containers.run simulates keygen."""
    client = MagicMock()
    client.containers.run.side_effect = _fake_keygen_side_effect
    return client


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


def test_default_path_writes_keypair_to_host(tmp_path, monkeypatch):
    """When vault_client is None, keypair is written to .vystak/ssh/<agent>/
    with chmod 600 on private keys and 644 on public keys. Nothing pushed to
    Vault."""
    monkeypatch.chdir(tmp_path)

    mock_docker = _make_mock_docker_client()
    node = WorkspaceSshKeygenNode(
        vault_client=None,
        docker_client=mock_docker,
        agent_name="assistant",
    )
    result = node.provision(context={})
    assert result.success

    ssh_dir = tmp_path / ".vystak" / "ssh" / "assistant"
    assert (ssh_dir / "client-key").exists()
    assert (ssh_dir / "client-key.pub").exists()
    assert (ssh_dir / "host-key").exists()
    assert (ssh_dir / "host-key.pub").exists()

    assert (ssh_dir / "client-key").stat().st_mode & 0o777 == 0o600
    assert (ssh_dir / "host-key").stat().st_mode & 0o777 == 0o600
    assert (ssh_dir / "client-key.pub").stat().st_mode & 0o777 == 0o644
    assert (ssh_dir / "host-key.pub").stat().st_mode & 0o777 == 0o644


def test_default_path_noop_on_second_apply(tmp_path, monkeypatch):
    """Re-running should preserve existing keys."""
    monkeypatch.chdir(tmp_path)

    mock_docker = _make_mock_docker_client()
    node = WorkspaceSshKeygenNode(
        vault_client=None, docker_client=mock_docker, agent_name="assistant"
    )
    node.provision(context={})
    first = (tmp_path / ".vystak" / "ssh" / "assistant" / "client-key").read_bytes()

    # Second provision should not regenerate
    result = node.provision(context={})
    assert result.success
    assert result.info["regenerated"] is False
    second = (tmp_path / ".vystak" / "ssh" / "assistant" / "client-key").read_bytes()
    assert first == second


def test_default_path_depends_on_is_network():
    """On the default path, the keygen node depends on 'network' rather than
    the Hashi KV-setup node."""
    node = WorkspaceSshKeygenNode(
        vault_client=None, docker_client=None, agent_name="assistant"
    )
    assert node.depends_on == ["network"]


def test_vault_path_depends_on_is_kv_setup():
    """Sanity check: Vault-path dependency is unchanged."""
    node = WorkspaceSshKeygenNode(
        vault_client=MagicMock(), docker_client=None, agent_name="assistant"
    )
    assert node.depends_on == ["hashi-vault:kv-setup"]
