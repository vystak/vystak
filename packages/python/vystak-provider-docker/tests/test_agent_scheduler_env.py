"""Tests for DockerAgentNode's scheduler env injection (VYSTAK_SCHEDULER_URL /
VYSTAK_AGENT_CANONICAL), gated by the `scheduler_enabled` constructor flag."""

from unittest.mock import MagicMock

import docker as _docker
import pytest
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak_provider_docker.nodes.agent import DockerAgentNode


def _make_node(monkeypatch, tmp_path, agent, *, scheduler_enabled):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    new_container = MagicMock()
    new_container.ports = {"8000/tcp": [{"HostPort": "9000"}]}
    client.containers.get.side_effect = [
        _docker.errors.NotFound("x"),
        new_container,
    ]
    code = type(
        "_GC",
        (),
        {
            "files": {"server.py": "print('ok')", "requirements.txt": ""},
            "entrypoint": "server.py",
        },
    )()
    plan = type("_Plan", (), {"target_hash": "abc"})()
    node = DockerAgentNode(
        client, agent, code, plan, scheduler_enabled=scheduler_enabled
    )
    network_info = MagicMock()
    network_info.name = "vystak-net"
    context = {"network": MagicMock(info={"network": network_info})}
    result = node.provision(context)
    assert result.success, result.error
    _, kwargs = client.containers.run.call_args
    return kwargs


@pytest.fixture()
def agent():
    return Agent(
        name="worker",
        framework="langchain-python",
        default_model=Model(
            name="sonnet",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-6",
        ),
    )


class TestSchedulerEnvInjection:
    def test_scheduler_enabled_injects_env(self, tmp_path, monkeypatch, agent):
        kwargs = _make_node(monkeypatch, tmp_path, agent, scheduler_enabled=True)
        assert kwargs["environment"]["VYSTAK_SCHEDULER_URL"] == (
            "http://vystak-heartbeat:8081"
        )
        assert kwargs["environment"]["VYSTAK_AGENT_CANONICAL"] == agent.canonical_name

    def test_scheduler_disabled_omits_env(self, tmp_path, monkeypatch, agent):
        kwargs = _make_node(monkeypatch, tmp_path, agent, scheduler_enabled=False)
        assert "VYSTAK_SCHEDULER_URL" not in kwargs["environment"]
        assert "VYSTAK_AGENT_CANONICAL" not in kwargs["environment"]

    def test_scheduler_enabled_defaults_to_false(self, tmp_path, monkeypatch, agent):
        """Constructor default (no scheduler_enabled kwarg passed) must not
        inject the scheduler env — backward compatible with existing
        DockerAgentNode(...) call sites that don't pass it."""
        monkeypatch.chdir(tmp_path)
        client = MagicMock()
        new_container = MagicMock()
        new_container.ports = {"8000/tcp": [{"HostPort": "9000"}]}
        client.containers.get.side_effect = [
            _docker.errors.NotFound("x"),
            new_container,
        ]
        code = type(
            "_GC",
            (),
            {
                "files": {"server.py": "print('ok')", "requirements.txt": ""},
                "entrypoint": "server.py",
            },
        )()
        plan = type("_Plan", (), {"target_hash": "abc"})()
        node = DockerAgentNode(client, agent, code, plan)  # no scheduler_enabled
        network_info = MagicMock()
        network_info.name = "vystak-net"
        context = {"network": MagicMock(info={"network": network_info})}
        result = node.provision(context)
        assert result.success, result.error
        _, kwargs = client.containers.run.call_args
        assert "VYSTAK_SCHEDULER_URL" not in kwargs["environment"]
