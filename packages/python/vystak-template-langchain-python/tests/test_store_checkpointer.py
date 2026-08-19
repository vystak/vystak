import os
from unittest import mock

from _vystak.runtime.store import _LazyCheckpointer, build_checkpointer, resolve_sessions_path


class _Agent:
    def __init__(self, sessions=None):
        self.sessions = sessions


class _Sessions:
    def __init__(self, engine, path=None, connection_string=None):
        self.engine = engine
        self.path = path
        self.connection_string = connection_string


def test_env_override_wins(tmp_path):
    target = tmp_path / "custom.db"
    with mock.patch.dict(os.environ, {"VYSTAK_SESSIONS_PATH": str(target)}):
        assert resolve_sessions_path() == str(target)


def test_data_dir_used_when_writable(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    with (
        mock.patch.dict(os.environ, {}, clear=True),
        mock.patch("_vystak.runtime.store._DATA_DIR", str(data)),
    ):
        assert resolve_sessions_path() == str(data / "sessions.db")


def test_falls_back_to_local_when_data_dir_missing(tmp_path):
    missing = tmp_path / "nope"
    with (
        mock.patch.dict(os.environ, {}, clear=True),
        mock.patch("_vystak.runtime.store._DATA_DIR", str(missing)),
    ):
        resolved = resolve_sessions_path()
    assert resolved.endswith("sessions.db")
    assert not resolved.startswith(str(missing))


def test_no_sessions_still_yields_durable_checkpointer(tmp_path):
    with mock.patch.dict(os.environ, {"VYSTAK_SESSIONS_PATH": str(tmp_path / "s.db")}):
        cp = build_checkpointer(_Agent())
    assert isinstance(cp, _LazyCheckpointer)


def test_memory_saver_is_gone(tmp_path):
    with mock.patch.dict(os.environ, {"VYSTAK_SESSIONS_PATH": str(tmp_path / "s.db")}):
        cp = build_checkpointer(_Agent())
    assert type(cp).__name__ != "MemorySaver"
