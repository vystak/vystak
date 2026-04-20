from unittest.mock import MagicMock

import docker.errors
from vystak_provider_docker.nodes.vault_agent import VaultAgentSidecarNode


def test_starts_vault_agent_container_with_agent_config():
    client = MagicMock()
    client.containers.get.side_effect = docker.errors.NotFound("not found")
    node = VaultAgentSidecarNode(
        client=client,
        principal_name="assistant-agent",
        image="hashicorp/vault:1.17",
        secret_names=["ANTHROPIC_API_KEY"],
        vault_address="http://vystak-vault:8200",
    )
    context = {
        "network": MagicMock(info={"network": MagicMock(name="vystak-net")}),
        "approle-creds:assistant-agent": MagicMock(
            info={"volume_name": "vystak-assistant-agent-approle"}
        ),
    }
    result = node.provision(context=context)
    client.containers.run.assert_called_once()
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["name"] == "vystak-assistant-agent-vault-agent"
    assert kwargs["detach"] is True
    # Three volumes: approle (ro), secrets (rw to be read by main container), config (ro)
    volumes = kwargs["volumes"]
    assert any(
        v["bind"] == "/vault/approle" and v["mode"] == "ro"
        for v in volumes.values()
    )
    assert "vystak-assistant-agent-secrets" in volumes
    # Command starts vault agent
    cmd = kwargs["command"]
    assert "agent" in cmd
    assert "-config=" in " ".join(cmd)
    assert result.info["secrets_volume_name"] == "vystak-assistant-agent-secrets"


def test_restarts_if_container_exists():
    client = MagicMock()
    existing = MagicMock()
    client.containers.get.return_value = existing
    node = VaultAgentSidecarNode(
        client=client,
        principal_name="assistant-agent",
        image="hashicorp/vault:1.17",
        secret_names=["KEY"],
        vault_address="http://vystak-vault:8200",
    )
    context = {
        "network": MagicMock(info={"network": MagicMock(name="vystak-net")}),
        "approle-creds:assistant-agent": MagicMock(
            info={"volume_name": "vystak-assistant-agent-approle"}
        ),
    }
    node.provision(context=context)
    existing.stop.assert_called_once()
    existing.remove.assert_called_once()
    client.containers.run.assert_called_once()
