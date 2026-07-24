"""DockerWorkspaceNode volume mapping (Phase 1 named volumes)."""

from unittest.mock import MagicMock

from vystak.schema.volume import Volume
from vystak.schema.workspace import Workspace
from vystak_provider_docker.nodes.workspace import DockerWorkspaceNode


def _workspace(**kwargs):
    defaults = {"name": "dev", "image": "python:3.12-slim", "provision": []}
    defaults.update(kwargs)
    return Workspace(**defaults)


def _provisioned_node(tmp_path, monkeypatch, workspace):
    """Build a node with a fresh MagicMock client and run provision()."""
    monkeypatch.chdir(tmp_path)
    docker_client = MagicMock()
    import docker.errors

    docker_client.containers.get.side_effect = docker.errors.NotFound("nope")
    (tmp_path / "tools").mkdir(exist_ok=True)
    node = DockerWorkspaceNode(
        client=docker_client,
        agent_name="assistant",
        workspace=workspace,
        tools_dir=tmp_path / "tools",
    )
    context = {"network": MagicMock(info={"network": MagicMock(name="vystak-net")})}
    node.provision(context=context)
    return docker_client


def test_named_volume_resource_name():
    node = DockerWorkspaceNode(
        client=MagicMock(),
        agent_name="assistant",
        workspace=_workspace(volume=Volume(name="team-code")),
        tools_dir="tools",
    )
    assert node.data_volume_name == "vystak-volume-team-code"


def test_implicit_volume_keeps_legacy_name():
    node = DockerWorkspaceNode(
        client=MagicMock(),
        agent_name="assistant",
        workspace=_workspace(),
        tools_dir="tools",
    )
    assert node.data_volume_name == "vystak-assistant-workspace-data"


def test_provision_mounts_named_volume_and_labels(tmp_path, monkeypatch):
    client = _provisioned_node(
        tmp_path, monkeypatch,
        _workspace(volume=Volume(name="team-code", retention="delete")),
    )
    run_kwargs = client.containers.run.call_args.kwargs
    assert run_kwargs["volumes"]["vystak-volume-team-code"] == {
        "bind": "/workspace", "mode": "rw",
    }
    assert run_kwargs["labels"]["vystak.volume.name"] == "vystak-volume-team-code"
    assert run_kwargs["labels"]["vystak.volume.retention"] == "delete"
    assert run_kwargs["labels"]["vystak.workspace.persistence"] == "volume"


def test_provision_ephemeral_volume_uses_tmpfs(tmp_path, monkeypatch):
    client = _provisioned_node(
        tmp_path, monkeypatch,
        _workspace(volume=Volume(name="scratch", mode="ephemeral")),
    )
    run_kwargs = client.containers.run.call_args.kwargs
    assert run_kwargs["tmpfs"] == {"/workspace": "rw,size=512m"}
    assert run_kwargs["labels"]["vystak.volume.name"] == ""
