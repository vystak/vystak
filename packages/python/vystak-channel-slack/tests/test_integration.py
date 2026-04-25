"""Docker-marked integration tests for the Slack channel container.

Opt-in: ``uv run pytest -m docker``. Verifies that the channel container's
state volume is wired correctly and SQLite migrations + bindings persist
across container restarts. Does NOT exercise the live Slack flow (that
requires real Slack tokens and is run by the user manually).
"""

from __future__ import annotations

import contextlib
import sqlite3

import pytest


def _docker_available() -> bool:
    try:
        import docker as _docker

        _docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.mark.docker
@pytest.mark.skipif(not _docker_available(), reason="Docker not reachable")
def test_state_volume_survives_container_restart(tmp_path):
    """The named state volume holding channel-state.db persists across restarts.

    Strategy: spin up a tiny alpine container that writes a row to a
    SQLite db at /data/channel-state.db, stop+remove it, spin up a
    fresh container against the same named volume, verify the row is
    still there.
    """
    import docker as _docker

    client = _docker.from_env()
    volume_name = "vystak-test-channel-state"
    container_name = "vystak-test-channel"

    # Cleanup any leftover state from a prior aborted run.
    for n in (container_name,):
        with contextlib.suppress(_docker.errors.NotFound):
            c = client.containers.get(n)
            c.stop()
            c.remove()
    with contextlib.suppress(_docker.errors.NotFound):
        client.volumes.get(volume_name).remove()

    try:
        client.volumes.create(name=volume_name)

        # First container — write a binding.
        first = client.containers.run(
            image="python:3.11-slim",
            name=container_name,
            command=[
                "python",
                "-c",
                (
                    "import sqlite3, os; "
                    "os.makedirs('/data', exist_ok=True); "
                    "c = sqlite3.connect('/data/channel-state.db'); "
                    "c.execute('CREATE TABLE IF NOT EXISTS channel_bindings "
                    "(team_id TEXT, channel_id TEXT, agent_name TEXT, "
                    "PRIMARY KEY(team_id, channel_id))'); "
                    "c.execute('INSERT OR REPLACE INTO channel_bindings VALUES (?,?,?)', "
                    "('T1','C1','weather-agent')); c.commit(); c.close()"
                ),
            ],
            volumes={volume_name: {"bind": "/data", "mode": "rw"}},
            detach=False,
            remove=True,
        )
        # `first` is the captured stdout when remove=True. We don't need it.
        del first

        # Second container — read it back.
        second_output = client.containers.run(
            image="python:3.11-slim",
            name=container_name + "-2",
            command=[
                "python",
                "-c",
                (
                    "import sqlite3; "
                    "c = sqlite3.connect('/data/channel-state.db'); "
                    "row = c.execute('SELECT agent_name FROM channel_bindings "
                    "WHERE team_id=? AND channel_id=?', ('T1','C1')).fetchone(); "
                    "print(row[0] if row else 'MISSING')"
                ),
            ],
            volumes={volume_name: {"bind": "/data", "mode": "rw"}},
            detach=False,
            remove=True,
        )
        assert b"weather-agent" in second_output, second_output
    finally:
        with contextlib.suppress(_docker.errors.NotFound):
            client.volumes.get(volume_name).remove()


@pytest.mark.docker
@pytest.mark.skipif(not _docker_available(), reason="Docker not reachable")
def test_sqlite_store_migrate_runs_clean(tmp_path):
    """SqliteStore.migrate() creates the expected three tables."""
    from vystak_channel_slack.store import SqliteStore

    db_path = tmp_path / "state.db"
    store = SqliteStore(path=str(db_path))
    store.migrate()
    store.migrate()  # idempotent

    conn = sqlite3.connect(str(db_path))
    try:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()

    assert {"channel_bindings", "user_prefs", "inviters"} <= names


@pytest.mark.docker
@pytest.mark.skipif(not _docker_available(), reason="Docker not reachable")
def test_destroy_with_delete_channel_data_removes_volume(tmp_path):
    """`vystak destroy --delete-channel-data` removes the state volume.

    User runs this manually; here we just smoke-test that the
    DockerProvider.destroy_channel(delete_channel_data=True) path
    deletes the volume when one exists.
    """
    import docker as _docker
    from vystak.schema.channel import Channel
    from vystak.schema.common import ChannelType
    from vystak.schema.platform import Platform
    from vystak.schema.provider import Provider
    from vystak_provider_docker import DockerProvider

    client = _docker.from_env()
    volume_name = "vystak-slack-delete-test-state"

    with contextlib.suppress(_docker.errors.NotFound):
        client.volumes.get(volume_name).remove()
    client.volumes.create(name=volume_name)

    docker_provider = Provider(name="docker", type="docker")
    platform = Platform(name="local", type="docker", provider=docker_provider)
    channel = Channel(
        name="slack-delete-test",
        type=ChannelType.SLACK,
        platform=platform,
        config={"port": 8080},
    )

    provider = DockerProvider()
    provider.destroy_channel(channel, delete_channel_data=True)

    with pytest.raises(_docker.errors.NotFound):
        client.volumes.get(volume_name)
