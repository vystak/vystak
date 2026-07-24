"""Tests that DockerAgentNode gets workspace context wired correctly."""

from unittest.mock import MagicMock, patch

from vystak.providers.base import DeployPlan, FileBundle
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak_provider_docker.nodes.agent import DockerAgentNode


def _agent_fixture():
    docker_p = Provider(name="docker", type="docker")
    platform = Platform(name="local", type="docker", provider=docker_p)
    anthropic = Provider(name="anthropic", type="anthropic")
    return Agent(
        name="assistant",
        framework="langchain-python",
        default_model=Model(
            name="m", provider=anthropic, model_name="claude-sonnet-4-20250514"
        ),
        platform=platform,
    )


def test_set_workspace_context_populates_env(tmp_path, monkeypatch):
    """When set_workspace_context is called, the generated container run
    carries a VYSTAK_WORKSPACE_HOST env var and mounts the secrets volume
    at /vystak/ssh (ro) so the agent-side code can read the SSH key files
    rendered by the vault-agent sidecar."""
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    import docker.errors

    fake_container = MagicMock()
    fake_container.ports = {"8000/tcp": [{"HostPort": "8000"}]}
    client.containers.get.side_effect = [
        docker.errors.NotFound("nope"),
        fake_container,
    ]

    gc = FileBundle(
        files={"server.py": "print('hi')", "requirements.txt": ""},
        entrypoint="server.py",
    )
    node = DockerAgentNode(
        client=client,
        agent=_agent_fixture(),
        generated_code=gc,
        plan=DeployPlan(
            agent_name="assistant",
            current_hash=None,
            target_hash="h",
            actions=[],
            changes={},
        ),
    )
    # Real deployments always set both contexts (Spec 1: workspace requires
    # vault). The /shared mount is added by set_vault_context; SSH keys for
    # the agent are rendered into that same volume via vault-agent file
    # templates. Test the combined path.
    node.set_vault_context(secrets_volume_name="vystak-assistant-agent-secrets")
    node.set_workspace_context(workspace_host="vystak-assistant-workspace")
    with patch("vystak_provider_docker.nodes.agent.shutil.copytree"), patch(
        "vystak_provider_docker.nodes.agent.shutil.rmtree"
    ):
        node.provision(
            context={"network": MagicMock(info={"network": MagicMock(name="n")})}
        )

    run_kwargs = client.containers.run.call_args.kwargs
    env = run_kwargs.get("environment", {})
    assert env.get("VYSTAK_WORKSPACE_HOST") == "vystak-assistant-workspace"
    volumes = run_kwargs.get("volumes", {})
    assert any(
        v.get("bind") == "/shared" and v.get("mode") == "ro"
        for v in volumes.values()
    )


def test_set_workspace_context_adds_dockerfile_symlink(tmp_path, monkeypatch):
    """The agent Dockerfile must symlink /vystak/ssh → /shared/ssh when
    workspace context is set, so agent-side code can read key files via
    /vystak/ssh/* while the underlying volume is mounted at /shared."""
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    import docker.errors

    fake_container = MagicMock()
    fake_container.ports = {"8000/tcp": [{"HostPort": "8000"}]}
    client.containers.get.side_effect = [
        docker.errors.NotFound("nope"),
        fake_container,
    ]

    gc = FileBundle(
        files={"server.py": "print('hi')", "requirements.txt": ""},
        entrypoint="server.py",
    )
    node = DockerAgentNode(
        client=client,
        agent=_agent_fixture(),
        generated_code=gc,
        plan=DeployPlan(
            agent_name="assistant",
            current_hash=None,
            target_hash="h",
            actions=[],
            changes={},
        ),
    )
    # Enable both vault context (for /shared mount) and workspace context.
    node.set_vault_context(secrets_volume_name="vystak-assistant-agent-secrets")
    node.set_workspace_context(workspace_host="vystak-assistant-workspace")
    with patch("vystak_provider_docker.nodes.agent.shutil.copytree"), patch(
        "vystak_provider_docker.nodes.agent.shutil.rmtree"
    ):
        node.provision(
            context={"network": MagicMock(info={"network": MagicMock(name="n")})}
        )

    dockerfile = (tmp_path / ".vystak" / "assistant" / "Dockerfile").read_text()
    assert "ln -sf /shared/ssh /vystak/ssh" in dockerfile


def test_default_path_writes_and_mounts_known_hosts(tmp_path, monkeypatch):
    """Default path assembles known_hosts from host-key.pub + workspace host
    so the agent's asyncssh client can verify the workspace host key
    (test_plan.md gap #2 / V11 on the default, no-Vault path)."""
    monkeypatch.chdir(tmp_path)
    ssh_dir = tmp_path / ".vystak" / "ssh" / "assistant"
    ssh_dir.mkdir(parents=True)
    (ssh_dir / "client-key").write_text("PRIVATE")
    (ssh_dir / "host-key.pub").write_text("ssh-ed25519 AAAATESTKEY comment\n")

    client = MagicMock()
    import docker.errors

    fake_container = MagicMock()
    fake_container.ports = {"8000/tcp": [{"HostPort": "8000"}]}
    client.containers.get.side_effect = [
        docker.errors.NotFound("nope"),
        fake_container,
    ]

    gc = FileBundle(
        files={"server.py": "print('hi')", "requirements.txt": ""},
        entrypoint="server.py",
    )
    node = DockerAgentNode(
        client=client,
        agent=_agent_fixture(),
        generated_code=gc,
        plan=DeployPlan(
            agent_name="assistant",
            current_hash=None,
            target_hash="h",
            actions=[],
            changes={},
        ),
    )
    # Default (no-Vault) path: SSH files delivered via individual bind
    # mounts rather than the /shared Vault-agent volume.
    node.set_workspace_context(workspace_host="vystak-assistant-workspace")
    node.set_default_path_context(env={}, ssh_host_dir=str(ssh_dir))
    with patch("vystak_provider_docker.nodes.agent.shutil.copytree"), patch(
        "vystak_provider_docker.nodes.agent.shutil.rmtree"
    ):
        node.provision(
            context={"network": MagicMock(info={"network": MagicMock(name="n")})}
        )

    known_hosts = ssh_dir / "known_hosts"
    assert known_hosts.read_text() == (
        "vystak-assistant-workspace ssh-ed25519 AAAATESTKEY comment\n"
    )
    run_kwargs = client.containers.run.call_args.kwargs
    assert run_kwargs["volumes"][str(known_hosts)] == {
        "bind": "/shared/ssh/known_hosts",
        "mode": "ro",
    }
