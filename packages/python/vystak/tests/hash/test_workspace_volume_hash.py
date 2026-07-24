"""Volume fields join the workspace hash — except retention."""

from vystak.hash.tree import hash_agent
from vystak.schema import Agent, Model, Platform, Provider
from vystak.schema.volume import Volume
from vystak.schema.workspace import Workspace


def _agent(volume: Volume) -> Agent:
    return Agent(
        name="bot",
        framework="langchain-python",
        default_model=Model(
            name="claude",
            provider=Provider(name="anthropic", type="anthropic"),
            model_name="claude-sonnet-4-6",
        ),
        platform=Platform(
            name="local",
            type="docker",
            provider=Provider(name="docker", type="docker"),
            namespace="dev",
        ),
        workspace=Workspace(name="dev", image="python:3.12-slim", volume=volume),
    )


def test_volume_mode_changes_workspace_hash():
    a1 = _agent(Volume(name="team-code", mode="persistent"))
    a2 = _agent(Volume(name="team-code", mode="ephemeral"))
    assert hash_agent(a1).workspace != hash_agent(a2).workspace


def test_volume_performance_changes_workspace_hash():
    a1 = _agent(Volume(name="team-code", performance="standard"))
    a2 = _agent(Volume(name="team-code", performance="premium"))
    assert hash_agent(a1).workspace != hash_agent(a2).workspace


def test_volume_retention_does_not_change_hash():
    a1 = _agent(Volume(name="team-code", retention="retain"))
    a2 = _agent(Volume(name="team-code", retention="delete"))
    assert hash_agent(a1).root == hash_agent(a2).root


def test_seed_folder_content_changes_workspace_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agent = _agent(Volume(name="team-code"))
    h_no_seed = hash_agent(agent).workspace

    seed = tmp_path / "workspaces" / "dev"
    seed.mkdir(parents=True)
    (seed / "a.txt").write_text("v1")
    h_v1 = hash_agent(agent).workspace
    assert h_v1 != h_no_seed

    (seed / "a.txt").write_text("v2")
    h_v2 = hash_agent(agent).workspace
    assert h_v2 != h_v1

    (seed / "b.txt").write_text("new")
    assert hash_agent(agent).workspace != h_v2


def test_no_seed_folder_keeps_hash_stable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agent = _agent(Volume(name="team-code"))
    assert hash_agent(agent).workspace == hash_agent(agent).workspace
