"""Tests for vystak_channel_runtime.launcher."""

from vystak.schema.common import ChannelType
from vystak_channel_runtime.launcher import build_runtime
from vystak_channel_runtime.runtime import ChannelRuntime
from vystak_channel_runtime.store import MemoryChannelStore, SqliteChannelStore
from vystak_channel_runtime.types import InboundEvent


class _Trivial(ChannelRuntime):
    async def start(self): pass
    async def stop(self): pass
    def parse_event(self, raw): return InboundEvent(
        channel_type=ChannelType.SLACK, scope_id="x", thread_id=None,
        user_id="U", text="hi", is_dm=False, mentions_bot=True,
    )
    async def post_reply(self, e, r, reply): pass
    async def deliver_message(self, *args, **kwargs): pass


def test_build_runtime_with_no_state_returns_memory_store():
    rt = build_runtime(_Trivial, config={"channel_type": "slack"}, routes={})
    assert isinstance(rt, _Trivial)
    assert isinstance(rt.store, MemoryChannelStore)


def test_build_runtime_with_sqlite_state(tmp_path):
    cfg = {
        "channel_type": "slack",
        "state": {"type": "sqlite", "path": str(tmp_path / "x.db")},
    }
    rt = build_runtime(_Trivial, config=cfg, routes={})
    assert isinstance(rt.store, SqliteChannelStore)


def test_launch_skips_test_endpoint_when_env_unset(monkeypatch):
    """Without VYSTAK_TEST_EVENTS=1, the sidecar isn't spawned."""
    monkeypatch.delenv("VYSTAK_TEST_EVENTS", raising=False)
    from vystak_channel_runtime.test_endpoint import is_test_endpoint_enabled
    assert is_test_endpoint_enabled() is False
    # _start_test_endpoint is a private helper; just confirm the gate works.


def test_launch_test_endpoint_gate_enabled(monkeypatch):
    monkeypatch.setenv("VYSTAK_TEST_EVENTS", "1")
    from vystak_channel_runtime.test_endpoint import is_test_endpoint_enabled
    assert is_test_endpoint_enabled() is True
