"""Tests that DockerAgentNode/DockerChannelNode inject entrypoint shim +
/shared volume when vault context is provided."""

from unittest.mock import MagicMock, patch

from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.platform import Platform
from vystak.schema.provider import Provider
from vystak.schema.secret import Secret
from vystak_provider_docker.nodes.agent import DockerAgentNode


def _agent_fixture():
    docker_p = Provider(name="docker", type="docker")
    platform = Platform(name="local", type="docker", provider=docker_p)
    anthropic = Provider(name="anthropic", type="anthropic")
    return Agent(
        name="assistant",
        model=Model(name="m", provider=anthropic, model_name="claude-sonnet-4-20250514"),
        secrets=[Secret(name="ANTHROPIC_API_KEY")],
        platform=platform,
    )


def test_no_vault_context_no_shim(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    import docker.errors

    fake_container = MagicMock()
    fake_container.ports = {"8000/tcp": [{"HostPort": "8000"}]}
    client.containers.get.side_effect = [
        docker.errors.NotFound("nope"),
        fake_container,
    ]
    from vystak.providers.base import DeployPlan, GeneratedCode

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
            actions=[],
            current_hash=None,
            target_hash="h",
            changes={},
        ),
    )
    # `shutil.copytree` / `shutil.rmtree` are the only module-level references we
    # need to neutralise so we don't recursively copy the whole vystak source
    # tree into the test tmpdir. Local `import vystak` statements inside
    # provision() don't need patching — the modules are already importable.
    with patch("vystak_provider_docker.nodes.agent.shutil.copytree"), patch(
        "vystak_provider_docker.nodes.agent.shutil.rmtree"
    ):
        node.provision(
            context={"network": MagicMock(info={"network": MagicMock(name="n")})}
        )
    dockerfile = (tmp_path / ".vystak" / "assistant" / "Dockerfile").read_text()
    assert "ENTRYPOINT" not in dockerfile  # legacy path uses CMD only
    assert "entrypoint-shim" not in dockerfile
    # No /shared volume mount on the run call when vault context is not set.
    kwargs = client.containers.run.call_args.kwargs
    volumes = kwargs.get("volumes") or {}
    assert not any(
        (v.get("bind") if isinstance(v, dict) else None) == "/shared"
        for v in volumes.values()
    )


def test_vault_context_injects_shim_and_entrypoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    import docker.errors

    fake_container = MagicMock()
    fake_container.ports = {"8000/tcp": [{"HostPort": "8000"}]}
    client.containers.get.side_effect = [
        docker.errors.NotFound("nope"),
        fake_container,
    ]
    from vystak.providers.base import DeployPlan, GeneratedCode

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
            actions=[],
            current_hash=None,
            target_hash="h",
            changes={},
        ),
    )
    node.set_vault_context(secrets_volume_name="vystak-assistant-secrets")
    with patch("vystak_provider_docker.nodes.agent.shutil.copytree"), patch(
        "vystak_provider_docker.nodes.agent.shutil.rmtree"
    ):
        node.provision(
            context={"network": MagicMock(info={"network": MagicMock(name="n")})}
        )
    build_dir = tmp_path / ".vystak" / "assistant"
    dockerfile = (build_dir / "Dockerfile").read_text()
    shim_path = build_dir / "entrypoint-shim.sh"
    assert shim_path.exists()
    assert 'ENTRYPOINT ["/vystak/entrypoint-shim.sh"]' in dockerfile
    assert 'CMD ["python", "server.py"]' in dockerfile
    # Check container run was passed the /shared volume mount
    kwargs = client.containers.run.call_args.kwargs
    volumes = kwargs["volumes"]
    assert "vystak-assistant-secrets" in volumes
    assert volumes["vystak-assistant-secrets"]["bind"] == "/shared"
    assert volumes["vystak-assistant-secrets"]["mode"] == "ro"


def test_channel_node_injects_shim(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from vystak.providers.base import GeneratedCode
    from vystak.schema.channel import Channel
    from vystak.schema.common import ChannelType
    from vystak_provider_docker.nodes.channel import DockerChannelNode

    client = MagicMock()
    import docker.errors

    fake_container = MagicMock()
    fake_container.ports = {"8080/tcp": [{"HostPort": "8080"}]}
    client.containers.get.side_effect = [
        docker.errors.NotFound("nope"),
        fake_container,
    ]
    docker_p = Provider(name="docker", type="docker")
    platform = Platform(name="local", type="docker", provider=docker_p)
    channel = Channel(
        name="chat",
        type=ChannelType.CHAT,
        platform=platform,
        config={"port": 8080},
    )
    gc = GeneratedCode(
        files={"server.py": "print('hi')", "requirements.txt": ""},
        entrypoint="server.py",
    )
    node = DockerChannelNode(
        client=client, channel=channel, generated_code=gc, target_hash="h"
    )
    node.set_vault_context(secrets_volume_name="vystak-chat-secrets")
    with patch("vystak_provider_docker.nodes.channel.shutil.copytree"), patch(
        "vystak_provider_docker.nodes.channel.shutil.rmtree"
    ):
        node.provision(
            context={"network": MagicMock(info={"network": MagicMock(name="n")})}
        )
    build_dir = tmp_path / ".vystak" / "channels" / "chat"
    dockerfile = (build_dir / "Dockerfile").read_text()
    assert 'ENTRYPOINT ["/vystak/entrypoint-shim.sh"]' in dockerfile
    assert (build_dir / "entrypoint-shim.sh").exists()
    kwargs = client.containers.run.call_args.kwargs
    assert "vystak-chat-secrets" in kwargs["volumes"]
    assert kwargs["volumes"]["vystak-chat-secrets"]["bind"] == "/shared"
