"""Tests that DockerAgentNode gets workspace context wired correctly."""

from unittest.mock import MagicMock, patch

from vystak.providers.base import DeployPlan, GeneratedCode
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
        model=Model(
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

    gc = GeneratedCode(
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
    # SSH volume mount for agent-side keys (written by agent's vault-agent sidecar).
    # Harmonized path: the same `vystak-<agent>-agent-secrets` volume is mounted
    # at /shared (for secrets.env delivery); the agent Dockerfile symlinks
    # /vystak/ssh → /shared/ssh. The test only validates the run-call binding.
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

    gc = GeneratedCode(
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
    assert "ln -s /shared/ssh /vystak/ssh" in dockerfile
