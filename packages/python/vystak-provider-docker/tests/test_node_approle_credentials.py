from unittest.mock import MagicMock

import docker.errors
from vystak_provider_docker.nodes.approle_credentials import AppRoleCredentialsNode


def test_creates_volume_and_writes_files_via_throwaway_container():
    client = MagicMock()
    client.volumes.get.side_effect = docker.errors.NotFound("not found")

    node = AppRoleCredentialsNode(
        client=client,
        principal_name="assistant-agent",
    )
    context = {
        "approle:assistant-agent": MagicMock(
            info={"role_id": "rid-1", "secret_id": "sid-1"}
        ),
    }
    result = node.provision(context=context)
    client.volumes.create.assert_called_once_with(name="vystak-assistant-agent-approle")
    # A throwaway container is used to write files into the named volume
    client.containers.run.assert_called_once()
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["remove"] is True
    assert kwargs["image"] == "alpine:3.19"
    volumes = kwargs.get("volumes") or {}
    assert "vystak-assistant-agent-approle" in volumes
    cmd = kwargs["command"]
    # The command writes both role_id and secret_id into the volume
    joined = " ".join(cmd) if isinstance(cmd, list) else cmd
    assert "rid-1" in joined
    assert "sid-1" in joined
    assert result.success is True
    assert result.info["volume_name"] == "vystak-assistant-agent-approle"


def test_reuses_existing_volume():
    client = MagicMock()
    node = AppRoleCredentialsNode(client=client, principal_name="assistant-agent")
    context = {
        "approle:assistant-agent": MagicMock(
            info={"role_id": "rid-1", "secret_id": "sid-1"}
        ),
    }
    node.provision(context=context)
    client.volumes.create.assert_not_called()


def test_destroy_removes_volume():
    client = MagicMock()
    node = AppRoleCredentialsNode(client=client, principal_name="assistant-agent")
    node.destroy()
    client.volumes.get.assert_called()
