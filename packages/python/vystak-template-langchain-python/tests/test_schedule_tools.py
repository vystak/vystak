"""build_schedule_tools — gating, POST/GET/DELETE mapping, turn-metadata delivery."""

from types import SimpleNamespace

import httpx
import pytest
from _vystak.runtime import schedules as sched_mod
from _vystak.runtime.schedules import CURRENT_TURN_METADATA, build_schedule_tools


def _agent():
    return SimpleNamespace(name="bot")


@pytest.fixture(autouse=True)
def _reset_turn_metadata():
    """Every test starts (and ends) with empty turn metadata — ContextVar
    state otherwise leaks across sequential sync test calls in this thread."""
    token = CURRENT_TURN_METADATA.set({})
    yield
    CURRENT_TURN_METADATA.reset(token)


class _FakeSyncClient:
    """Stand-in for httpx.Client — records requests, returns canned responses.

    Mirrors the Fake-class convention in test_nats_bridge.py rather than
    httpx.MockTransport: monkeypatching httpx.Client with a factory that
    itself calls httpx.Client(transport=MockTransport(...)) would re-enter
    the patched attribute and recurse forever, since `sched_mod.httpx` IS
    the global httpx module.
    """

    def __init__(self, handler):
        self._handler = handler
        self.requests: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None):
        self.requests.append({"method": "POST", "url": url, "json": json})
        return self._handler("POST", url, json, None)

    def get(self, url, params=None):
        self.requests.append({"method": "GET", "url": url, "params": params})
        return self._handler("GET", url, None, params)

    def delete(self, url):
        self.requests.append({"method": "DELETE", "url": url})
        return self._handler("DELETE", url, None, None)


def _patch_client(monkeypatch, handler):
    fake = _FakeSyncClient(handler)
    monkeypatch.setattr(sched_mod.httpx, "Client", lambda base_url, timeout: fake)
    return fake


def _set_env(monkeypatch, base_url="http://vystak-heartbeat:8081", canonical="bot.agents.default"):
    monkeypatch.setenv("VYSTAK_SCHEDULER_URL", base_url)
    monkeypatch.setenv("VYSTAK_AGENT_CANONICAL", canonical)


# ---------------------------------------------------------------------------
# (a) gating
# ---------------------------------------------------------------------------


def test_no_env_returns_empty(monkeypatch):
    monkeypatch.delenv("VYSTAK_SCHEDULER_URL", raising=False)
    monkeypatch.delenv("VYSTAK_AGENT_CANONICAL", raising=False)
    assert build_schedule_tools(_agent()) == []


def test_missing_scheduler_url_returns_empty(monkeypatch):
    monkeypatch.delenv("VYSTAK_SCHEDULER_URL", raising=False)
    monkeypatch.setenv("VYSTAK_AGENT_CANONICAL", "bot.agents.default")
    assert build_schedule_tools(_agent()) == []


def test_missing_agent_canonical_returns_empty(monkeypatch):
    monkeypatch.setenv("VYSTAK_SCHEDULER_URL", "http://vystak-heartbeat:8081")
    monkeypatch.delenv("VYSTAK_AGENT_CANONICAL", raising=False)
    assert build_schedule_tools(_agent()) == []


def test_tool_names(monkeypatch):
    _set_env(monkeypatch)
    tools = build_schedule_tools(_agent())
    assert [t.name for t in tools] == [
        "schedule_task", "list_scheduled_tasks", "cancel_scheduled_task",
    ]


# ---------------------------------------------------------------------------
# (b) schedule_task — POST body + returned id
# ---------------------------------------------------------------------------


def test_schedule_task_posts_expected_body_and_returns_id(monkeypatch):
    _set_env(monkeypatch)

    def handler(method, url, json, params):
        assert method == "POST"
        assert url == "/tasks"
        return httpx.Response(201, json={"id": "task-123", "agent": "bot.agents.default"})

    fake = _patch_client(monkeypatch, handler)
    tools = {t.name: t for t in build_schedule_tools(_agent())}

    result = tools["schedule_task"].invoke(
        {"name": "r", "every": "1h", "prompt": "check"}
    )

    body = fake.requests[0]["json"]
    assert body["agent"] == "bot.agents.default"
    assert body["name"] == "r"
    assert body["every"] == "1h"
    assert body["prompt"] == "check"
    assert body["created_by"] == "agent:bot.agents.default"
    assert body["timezone"] == "UTC"
    # cron/at not passed -> not present in body
    assert "cron" not in body and "at" not in body
    assert "task-123" in result


# ---------------------------------------------------------------------------
# (c) deliver_here=True + CURRENT_TURN_METADATA set -> target_channel/target_thread
# ---------------------------------------------------------------------------


def test_schedule_task_includes_targets_when_turn_metadata_set(monkeypatch):
    _set_env(monkeypatch)
    CURRENT_TURN_METADATA.set({"channel_canonical": "c.channels.d", "thread_id": "t9"})

    def handler(method, url, json, params):
        return httpx.Response(201, json={"id": "task-456"})

    fake = _patch_client(monkeypatch, handler)
    tools = {t.name: t for t in build_schedule_tools(_agent())}

    result = tools["schedule_task"].invoke(
        {"name": "r", "every": "1h", "prompt": "check", "deliver_here": True}
    )

    body = fake.requests[0]["json"]
    assert body["target_channel"] == "c.channels.d"
    assert body["target_thread"] == "t9"
    assert "not delivered" not in result and "no originating" not in result


# ---------------------------------------------------------------------------
# (d) deliver_here=True + empty metadata -> omit targets + note
# ---------------------------------------------------------------------------


def test_schedule_task_omits_targets_and_notes_when_metadata_empty(monkeypatch):
    _set_env(monkeypatch)
    # Autouse fixture already reset CURRENT_TURN_METADATA to {}.

    def handler(method, url, json, params):
        return httpx.Response(201, json={"id": "task-789"})

    fake = _patch_client(monkeypatch, handler)
    tools = {t.name: t for t in build_schedule_tools(_agent())}

    result = tools["schedule_task"].invoke(
        {"name": "r", "every": "1h", "prompt": "check", "deliver_here": True}
    )

    body = fake.requests[0]["json"]
    assert "target_channel" not in body
    assert "target_thread" not in body
    assert "task-789" in result
    assert "no originating channel/thread known" in result
    assert "will be logged, not delivered" in result


# ---------------------------------------------------------------------------
# (e) list_scheduled_tasks — GET with agent= filter
# ---------------------------------------------------------------------------


def test_list_scheduled_tasks_filters_by_agent(monkeypatch):
    _set_env(monkeypatch)

    def handler(method, url, json, params):
        assert method == "GET"
        assert url == "/tasks"
        assert params == {"agent": "bot.agents.default"}
        return httpx.Response(200, json={"tasks": [
            {
                "id": "t1", "name": "r", "status": "active",
                "task": {"every": "1h"}, "next_fire_at": "2026-01-01T00:00:00+00:00",
            },
        ]})

    _patch_client(monkeypatch, handler)
    tools = {t.name: t for t in build_schedule_tools(_agent())}

    result = tools["list_scheduled_tasks"].invoke({})
    assert "t1" in result and "r" in result and "active" in result


def test_list_scheduled_tasks_empty(monkeypatch):
    _set_env(monkeypatch)

    def handler(method, url, json, params):
        return httpx.Response(200, json={"tasks": []})

    _patch_client(monkeypatch, handler)
    tools = {t.name: t for t in build_schedule_tools(_agent())}

    result = tools["list_scheduled_tasks"].invoke({})
    assert result == "no scheduled tasks"


# ---------------------------------------------------------------------------
# (f) cancel_scheduled_task — 409 / cross-agent mismatch -> readable strings
# ---------------------------------------------------------------------------


def test_cancel_scheduled_task_rejects_other_agents_task(monkeypatch):
    _set_env(monkeypatch, canonical="bot.agents.default")

    def handler(method, url, json, params):
        if method == "GET":
            return httpx.Response(200, json={"id": "task-1", "agent": "other.agents.default"})
        raise AssertionError("DELETE should not be called on mismatch")

    _patch_client(monkeypatch, handler)
    tools = {t.name: t for t in build_schedule_tools(_agent())}

    result = tools["cancel_scheduled_task"].invoke({"task_id": "task-1"})
    assert result == "not your task"


def test_cancel_scheduled_task_maps_409_to_readable_string(monkeypatch):
    _set_env(monkeypatch, canonical="bot.agents.default")

    def handler(method, url, json, params):
        if method == "GET":
            return httpx.Response(200, json={"id": "task-1", "agent": "bot.agents.default"})
        if method == "DELETE":
            return httpx.Response(409, text="declarative task — change the YAML definition")
        raise AssertionError(f"unexpected method {method}")

    _patch_client(monkeypatch, handler)
    tools = {t.name: t for t in build_schedule_tools(_agent())}

    result = tools["cancel_scheduled_task"].invoke({"task_id": "task-1"})
    assert "failed" in result and "409" in result
    assert "declarative task" in result


def test_cancel_scheduled_task_succeeds(monkeypatch):
    _set_env(monkeypatch, canonical="bot.agents.default")

    def handler(method, url, json, params):
        if method == "GET":
            return httpx.Response(200, json={"id": "task-1", "agent": "bot.agents.default"})
        if method == "DELETE":
            return httpx.Response(204)
        raise AssertionError(f"unexpected method {method}")

    _patch_client(monkeypatch, handler)
    tools = {t.name: t for t in build_schedule_tools(_agent())}

    result = tools["cancel_scheduled_task"].invoke({"task_id": "task-1"})
    assert result == "cancelled"


# ---------------------------------------------------------------------------
# scheduler unreachable -> error string, never raises
# ---------------------------------------------------------------------------


def test_schedule_task_scheduler_unreachable_returns_string(monkeypatch):
    _set_env(monkeypatch)

    class _RaisingClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json=None):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(sched_mod.httpx, "Client", lambda base_url, timeout: _RaisingClient())
    tools = {t.name: t for t in build_schedule_tools(_agent())}

    result = tools["schedule_task"].invoke({"name": "r", "every": "1h"})
    assert isinstance(result, str)
    assert "scheduler unreachable" in result
