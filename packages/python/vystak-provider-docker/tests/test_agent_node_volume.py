"""Tests for DockerAgentNode._build_volumes — default per-agent data volume.

Agents that don't declare `sessions:` still need a durable /data mount
(the langchain template now writes /data/sessions.db and /data/turns.db by
default). A declared sessions volume still wins — no double-mount.
"""

from unittest.mock import MagicMock

import pytest
from vystak.provisioning.node import ProvisionResult
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.provider import Provider
from vystak.schema.service import Sqlite
from vystak_provider_docker.nodes.agent import DockerAgentNode


def _result(volume_name: str) -> ProvisionResult:
    return ProvisionResult(
        name="sessions",
        success=True,
        info={"engine": "sqlite", "volume_name": volume_name},
    )


@pytest.fixture()
def agent_node_factory():
    def _factory(*, sessions, name):
        kwargs = dict(
            name=name,
            framework="langchain-python",
            default_model=Model(
                name="sonnet",
                provider=Provider(name="anthropic", type="anthropic"),
                model_name="claude-sonnet-4-6",
            ),
        )
        if sessions is not None:
            kwargs["sessions"] = Sqlite(name="sessions")
        agent = Agent(**kwargs)

        client = MagicMock()
        code = type(
            "_GC",
            (),
            {
                "files": {"server.py": "print('ok')", "requirements.txt": ""},
                "entrypoint": "server.py",
            },
        )()
        plan = type("_Plan", (), {"target_hash": "abc"})()
        return DockerAgentNode(client, agent, code, plan)

    return _factory


def test_sessionless_agent_gets_a_data_volume(agent_node_factory):
    node = agent_node_factory(sessions=None, name="solo")
    volumes = node._build_volumes(context={})
    assert volumes["vystak-agent-solo-data"] == {"bind": "/data", "mode": "rw"}


def test_declared_sessions_volume_still_wins(agent_node_factory):
    node = agent_node_factory(sessions="declared", name="solo")
    volumes = node._build_volumes(context={"sessions": _result("vystak-sessions-vol")})
    assert volumes["vystak-sessions-vol"]["bind"] == "/data"
    assert "vystak-agent-solo-data" not in volumes


def test_memory_sqlite_volume_also_wins_no_double_mount(agent_node_factory):
    """An agent with a sqlite `memory:` service (and no `sessions:`) already
    gets /data bound via depends_on -> memory. The fallback must not add a
    second volume at the same bind path (memory-agent example config)."""
    node = agent_node_factory(sessions=None, name="solo")
    node._agent.memory = Sqlite(name="memory")
    volumes = node._build_volumes(
        context={"memory": _result("vystak-data-memory")}
    )
    data_binds = [v for v in volumes.values() if v["bind"] == "/data"]
    assert len(data_binds) == 1
    assert volumes["vystak-data-memory"]["bind"] == "/data"
    assert "vystak-agent-solo-data" not in volumes


def test_provision_creates_fallback_volume_when_missing(agent_node_factory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    node = agent_node_factory(sessions=None, name="solo")
    client = node._client
    client.volumes.list.return_value = []
    client.containers.get.side_effect = [
        __import__("docker").errors.NotFound("x"),
        MagicMock(ports={"8000/tcp": [{"HostPort": "9000"}]}),
    ]
    network_info = MagicMock()
    network_info.name = "vystak-net"
    context = {"network": MagicMock(info={"network": network_info})}

    result = node.provision(context)

    assert result.success, result.error
    client.volumes.create.assert_called_once_with("vystak-agent-solo-data")
    _, kwargs = client.containers.run.call_args
    assert kwargs["volumes"]["vystak-agent-solo-data"] == {"bind": "/data", "mode": "rw"}
