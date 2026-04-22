"""Tests for DockerWorkspaceNode."""

from unittest.mock import MagicMock

from vystak.schema.workspace import Workspace
from vystak_provider_docker.nodes.workspace import DockerWorkspaceNode


def _workspace(**kwargs):
    defaults = {"name": "dev", "image": "python:3.12-slim", "provision": []}
    defaults.update(kwargs)
    return Workspace(**defaults)


def test_builds_image_runs_container(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docker_client = MagicMock()
    import docker.errors

    docker_client.containers.get.side_effect = docker.errors.NotFound("nope")

    node = DockerWorkspaceNode(
        client=docker_client,
        agent_name="assistant",
        workspace=_workspace(),
        tools_dir=tmp_path / "tools",
    )
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "sample.py").write_text("def sample(): return 1\n")

    context = {"network": MagicMock(info={"network": MagicMock(name="vystak-net")})}
    result = node.provision(context=context)

    assert docker_client.images.build.called
    assert docker_client.containers.run.called
    run_kwargs = docker_client.containers.run.call_args.kwargs
    assert run_kwargs["name"] == "vystak-assistant-workspace"
    # /shared mount (vault agent secret+ssh volume; wired from a sibling node)
    # /workspace data volume
    volumes = run_kwargs["volumes"]
    assert "vystak-assistant-workspace-data" in volumes
    assert result.info["container_name"] == "vystak-assistant-workspace"


def test_persistence_ephemeral_uses_tmpfs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docker_client = MagicMock()
    import docker.errors

    docker_client.containers.get.side_effect = docker.errors.NotFound("nope")

    (tmp_path / "tools").mkdir()
    node = DockerWorkspaceNode(
        client=docker_client,
        agent_name="assistant",
        workspace=_workspace(persistence="ephemeral"),
        tools_dir=tmp_path / "tools",
    )
    context = {"network": MagicMock(info={"network": MagicMock(name="vystak-net")})}
    node.provision(context=context)
    run_kwargs = docker_client.containers.run.call_args.kwargs
    # No named volume for data; uses tmpfs
    assert "vystak-assistant-workspace-data" not in run_kwargs.get("volumes", {})
    assert run_kwargs.get("tmpfs", {}).get("/workspace") is not None


def test_persistence_bind_uses_host_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docker_client = MagicMock()
    import docker.errors

    docker_client.containers.get.side_effect = docker.errors.NotFound("nope")

    host_proj = tmp_path / "my_project"
    host_proj.mkdir()
    (tmp_path / "tools").mkdir()
    node = DockerWorkspaceNode(
        client=docker_client,
        agent_name="assistant",
        workspace=_workspace(persistence="bind", path=str(host_proj)),
        tools_dir=tmp_path / "tools",
    )
    context = {"network": MagicMock(info={"network": MagicMock(name="vystak-net")})}
    node.provision(context=context)
    run_kwargs = docker_client.containers.run.call_args.kwargs
    volumes = run_kwargs["volumes"]
    assert str(host_proj.resolve()) in volumes
    assert volumes[str(host_proj.resolve())]["bind"] == "/workspace"
