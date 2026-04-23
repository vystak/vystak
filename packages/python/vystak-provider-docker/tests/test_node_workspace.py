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


def test_workspace_default_path_env_and_ssh_mount(tmp_path, monkeypatch):
    """Default-path wiring: env dict goes to container environment;
    host-key and client-key.pub bind-mount into /shared/ssh_host_ed25519_key
    and /shared/authorized_keys_vystak-agent respectively. Vault secrets-volume
    mount is NOT present."""
    monkeypatch.chdir(tmp_path)

    from unittest.mock import MagicMock

    import docker as _docker
    from vystak.schema.workspace import Workspace
    from vystak_provider_docker.nodes.workspace import DockerWorkspaceNode

    client = MagicMock()
    new_container = MagicMock()
    new_container.ports = {}
    client.containers.get.side_effect = [
        _docker.errors.NotFound("x"),
        new_container,
    ]

    ws = Workspace(name="ws", image="python:3.12-slim", secrets=[], persistence="ephemeral")
    node = DockerWorkspaceNode(
        client=client,
        agent_name="assistant",
        workspace=ws,
        tools_dir=tmp_path / "tools",
    )
    node.set_default_path_context(
        env={"STRIPE_API_KEY": "sk-test"},
        ssh_host_dir=str(tmp_path / ".vystak" / "ssh" / "assistant"),
    )

    network_info = MagicMock()
    network_info.name = "vystak-net"
    context = {"network": MagicMock(info={"network": network_info})}

    result = node.provision(context)
    assert result.success, result.error

    _, kwargs = client.containers.run.call_args
    # Env from default path is set
    assert kwargs["environment"]["STRIPE_API_KEY"] == "sk-test"
    # SSH bind-mounts (workspace side)
    ssh_dir_host = str(tmp_path / ".vystak" / "ssh" / "assistant")
    assert f"{ssh_dir_host}/host-key" in kwargs["volumes"]
    assert kwargs["volumes"][f"{ssh_dir_host}/host-key"]["bind"] == "/shared/ssh_host_ed25519_key"
    assert kwargs["volumes"][f"{ssh_dir_host}/host-key"]["mode"] == "ro"
    assert f"{ssh_dir_host}/client-key.pub" in kwargs["volumes"]
    client_pub_bind = kwargs["volumes"][f"{ssh_dir_host}/client-key.pub"]["bind"]
    assert client_pub_bind == "/shared/authorized_keys_vystak-agent"
    # Vault secrets-volume mount is NOT in volumes
    assert "vystak-assistant-workspace-secrets" not in kwargs["volumes"]


def test_workspace_default_path_depends_on_drops_vault_agent():
    """depends_on drops 'vault-agent:<agent>-workspace' when default-path
    context is set; keeps the ssh-keygen dependency."""
    from unittest.mock import MagicMock

    from vystak.schema.workspace import Workspace
    from vystak_provider_docker.nodes.workspace import DockerWorkspaceNode

    ws = Workspace(name="ws", secrets=[])
    node = DockerWorkspaceNode(
        client=MagicMock(),
        agent_name="assistant",
        workspace=ws,
        tools_dir=MagicMock(),
    )
    # Vault path (default) — both deps present
    assert "vault-agent:assistant-workspace" in node.depends_on
    assert "workspace-ssh-keygen:assistant" in node.depends_on

    # Default path — vault-agent dep dropped
    node.set_default_path_context(
        env={}, ssh_host_dir="/tmp/stub"
    )
    assert "vault-agent:assistant-workspace" not in node.depends_on
    assert "workspace-ssh-keygen:assistant" in node.depends_on
