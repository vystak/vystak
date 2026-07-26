"""Tests for `vystak schedules` — CliRunner + httpx.MockTransport.

``respx`` isn't a repo dependency (checked: ``import respx`` fails), so instead
of decorating with a respx router we monkeypatch the module's internal
``_client()`` factory to return an ``httpx.Client`` wired to a
``httpx.MockTransport(handler)``. This is the fallback the task brief
describes.
"""

import json

import httpx
import pytest
from click.testing import CliRunner
from vystak_cli.cli import cli
from vystak_cli.commands import schedules as schedules_mod


def _mock_client(handler):
    """Build the same kind of client `_client()` normally returns, but
    routed through an in-process handler instead of a real socket."""

    def factory():
        return httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url=schedules_mod.DEFAULT_URL,
            timeout=10,
        )

    return factory


TASK_ROW = {
    "id": "11111111-2222-3333-4444-555555555555",
    "agent": "a.agents.default",
    "name": "report",
    "source": "runtime",
    "status": "active",
    "created_by": "cli",
    "next_fire_at": "2026-08-01T09:00:00+00:00",
    "last_fire_at": None,
    "last_result": None,
    "task": {"name": "report", "cron": "0 9 * * 1", "at": None, "every": None},
}

TASK_ROW_CANCELLED = {
    **TASK_ROW,
    "id": "99999999-8888-7777-6666-555555555555",
    "name": "old-one-off",
    "status": "cancelled",
    "task": {"name": "old-one-off", "cron": None, "at": "2026-01-01T00:00:00+00:00", "every": None},
}


def test_list_renders_one_row_per_task_and_hides_non_active(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/tasks"
        return httpx.Response(200, json={"tasks": [TASK_ROW, TASK_ROW_CANCELLED]})

    monkeypatch.setattr(schedules_mod, "_client", _mock_client(handler))

    runner = CliRunner()
    result = runner.invoke(cli, ["schedules", "list"])

    assert result.exit_code == 0, result.output
    assert TASK_ROW["id"][:8] in result.output
    assert "a.agents.default" in result.output
    assert "report" in result.output
    assert "runtime" in result.output
    assert "active" in result.output
    assert "0 9 * * 1" in result.output
    assert "2026-08-01T09:00:00+00:00" in result.output
    # cancelled row hidden by default
    assert "old-one-off" not in result.output


def test_list_all_shows_non_active_rows(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tasks": [TASK_ROW, TASK_ROW_CANCELLED]})

    monkeypatch.setattr(schedules_mod, "_client", _mock_client(handler))

    runner = CliRunner()
    result = runner.invoke(cli, ["schedules", "list", "--all"])

    assert result.exit_code == 0, result.output
    assert "old-one-off" in result.output
    assert "cancelled" in result.output


def test_add_posts_expected_json_and_prints_id(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/tasks"
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={**TASK_ROW, "id": "new-task-id"})

    monkeypatch.setattr(schedules_mod, "_client", _mock_client(handler))

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "schedules",
            "add",
            "--agent",
            "a.agents.default",
            "--name",
            "r",
            "--cron",
            "0 9 * * 1",
            "--prompt",
            "hi",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["body"] == {
        "agent": "a.agents.default",
        "name": "r",
        "cron": "0 9 * * 1",
        "timezone": "UTC",
        "prompt": "hi",
        "created_by": "cli",
    }
    assert result.output.strip() == "new-task-id"


def test_remove_sends_delete_and_prints_removed(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/tasks/abc123"
        return httpx.Response(204)

    monkeypatch.setattr(schedules_mod, "_client", _mock_client(handler))

    runner = CliRunner()
    result = runner.invoke(cli, ["schedules", "remove", "abc123"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "removed"


def test_pause_patches_enabled_false(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/tasks/abc123"
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=TASK_ROW)

    monkeypatch.setattr(schedules_mod, "_client", _mock_client(handler))

    runner = CliRunner()
    result = runner.invoke(cli, ["schedules", "pause", "abc123"])

    assert result.exit_code == 0, result.output
    assert captured["body"] == {"enabled": False}
    assert result.output.strip() == "ok"


def test_resume_patches_enabled_true(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=TASK_ROW)

    monkeypatch.setattr(schedules_mod, "_client", _mock_client(handler))

    runner = CliRunner()
    result = runner.invoke(cli, ["schedules", "resume", "abc123"])

    assert result.exit_code == 0, result.output
    assert captured["body"] == {"enabled": True}
    assert result.output.strip() == "ok"


def test_show_prints_json_detail(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/tasks/abc123"
        return httpx.Response(200, json=TASK_ROW)

    monkeypatch.setattr(schedules_mod, "_client", _mock_client(handler))

    runner = CliRunner()
    result = runner.invoke(cli, ["schedules", "show", "abc123"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == TASK_ROW


def test_409_surfaces_server_detail_and_exits_1(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"detail": "declarative task — change the YAML definition and re-apply"},
        )

    monkeypatch.setattr(schedules_mod, "_client", _mock_client(handler))

    runner = CliRunner()
    result = runner.invoke(cli, ["schedules", "pause", "abc123"])

    assert result.exit_code == 1
    assert "declarative task" in result.output


def test_connection_refused_on_list(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    monkeypatch.setattr(schedules_mod, "_client", _mock_client(handler))

    runner = CliRunner()
    result = runner.invoke(cli, ["schedules", "list"])

    assert result.exit_code == 1
    assert "scheduler is not running — is anything deployed with schedules?" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["schedules", "show", "abc123"],
        ["schedules", "pause", "abc123"],
        ["schedules", "resume", "abc123"],
        ["schedules", "remove", "abc123"],
        [
            "schedules",
            "add",
            "--agent",
            "a.agents.default",
            "--name",
            "r",
            "--cron",
            "0 9 * * 1",
        ],
    ],
)
def test_connection_refused_on_other_commands(monkeypatch, args):
    """The brief only wires ConnectError handling into `list`; this repo
    extends it to every subcommand via a shared helper (documented in the
    task report as an intentional improvement)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    monkeypatch.setattr(schedules_mod, "_client", _mock_client(handler))

    runner = CliRunner()
    result = runner.invoke(cli, args)

    assert result.exit_code == 1
    assert "scheduler is not running — is anything deployed with schedules?" in result.output
