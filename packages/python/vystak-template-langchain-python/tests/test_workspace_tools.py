"""build_workspace_tools — gating, RPC mapping, error-string behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from _vystak.runtime import workspace as ws_mod
from _vystak.runtime.workspace import build_workspace_tools


def _agent(with_workspace: bool = True):
    return SimpleNamespace(
        name="bot",
        workspace=SimpleNamespace(name="dev") if with_workspace else None,
    )


def test_no_workspace_returns_empty():
    assert build_workspace_tools(_agent(with_workspace=False)) == []


def test_no_host_env_returns_empty(monkeypatch):
    monkeypatch.delenv("VYSTAK_WORKSPACE_HOST", raising=False)
    assert build_workspace_tools(_agent()) == []


def test_tool_names(monkeypatch):
    monkeypatch.setenv("VYSTAK_WORKSPACE_HOST", "ws-host")
    tools = build_workspace_tools(_agent())
    assert [t.name for t in tools] == [
        "read_file", "write_file", "list_dir", "edit_file",
        "run", "shell", "git_status", "git_diff", "git_commit",
    ]


@pytest.mark.asyncio
async def test_read_file_maps_to_fs_read(monkeypatch):
    monkeypatch.setenv("VYSTAK_WORKSPACE_HOST", "ws-host")
    fake = AsyncMock()
    fake.invoke.return_value = "contents"
    monkeypatch.setattr(ws_mod, "_make_client", lambda host: fake)
    tools = {t.name: t for t in build_workspace_tools(_agent())}
    result = await tools["read_file"].ainvoke({"path": "notes.md"})
    assert result == "contents"
    fake.invoke.assert_awaited_once_with("fs.readFile", path="notes.md")


@pytest.mark.asyncio
async def test_run_streams_and_returns_output_with_exit_code(monkeypatch):
    monkeypatch.setenv("VYSTAK_WORKSPACE_HOST", "ws-host")

    captured = {}

    class FakeClient:
        async def invoke_stream(self, method, **params):
            captured["method"] = method
            captured["params"] = params
            yield {"channel": "stdout", "chunk": "hello\n"}
            yield {"channel": "stderr", "chunk": "warn\n"}
            yield {"exit_code": 0, "duration_ms": 3}

    monkeypatch.setattr(ws_mod, "_make_client", lambda host: FakeClient())
    tools = {t.name: t for t in build_workspace_tools(_agent())}
    result = await tools["run"].ainvoke({"cmd": "echo hello world"})
    assert "hello" in result and "exit_code=0" in result
    # The RPC server (exec.py) builds argv via create_subprocess_exec with
    # no shell — the client must split the command itself and send it as
    # cmd + args, matching the server's actual contract.
    assert captured["method"] == "exec.run"
    assert captured["params"] == {"cmd": "echo", "args": ["hello", "world"]}


@pytest.mark.asyncio
async def test_run_empty_command_is_an_error_string(monkeypatch):
    monkeypatch.setenv("VYSTAK_WORKSPACE_HOST", "ws-host")
    monkeypatch.setattr(ws_mod, "_make_client", lambda host: AsyncMock())
    tools = {t.name: t for t in build_workspace_tools(_agent())}
    result = await tools["run"].ainvoke({"cmd": "   "})
    assert isinstance(result, str) and "empty command" in result


@pytest.mark.asyncio
async def test_errors_become_strings_not_exceptions(monkeypatch):
    monkeypatch.setenv("VYSTAK_WORKSPACE_HOST", "ws-host")
    fake = AsyncMock()
    fake.invoke.side_effect = RuntimeError("fs.readFile: no such file")
    monkeypatch.setattr(ws_mod, "_make_client", lambda host: fake)
    tools = {t.name: t for t in build_workspace_tools(_agent())}
    result = await tools["read_file"].ainvoke({"path": "nope"})
    assert isinstance(result, str) and "no such file" in result


@pytest.mark.asyncio
async def test_git_commit_stages_then_commits(monkeypatch):
    monkeypatch.setenv("VYSTAK_WORKSPACE_HOST", "ws-host")
    fake = AsyncMock()
    fake.invoke.side_effect = [None, {"sha": "abc123"}]
    monkeypatch.setattr(ws_mod, "_make_client", lambda host: fake)
    tools = {t.name: t for t in build_workspace_tools(_agent())}
    result = await tools["git_commit"].ainvoke(
        {"message": "save", "paths": ["a.py"]}
    )
    assert "abc123" in str(result)
    assert fake.invoke.await_args_list[0].args == ("git.add",)
    assert fake.invoke.await_args_list[0].kwargs == {"paths": ["a.py"]}
    assert fake.invoke.await_args_list[1].args == ("git.commit",)


def test_make_client_falls_back_to_shared_ssh(monkeypatch, tmp_path):
    shared = tmp_path / "shared-ssh"
    shared.mkdir()
    key = shared / "id_ed25519"
    key.write_text("KEY")
    kh = shared / "known_hosts"
    kh.write_text("host ssh-ed25519 AAAA")
    monkeypatch.setattr(
        ws_mod, "_SSH_KEY_CANDIDATES", ["/nonexistent/id_ed25519", str(key)]
    )
    monkeypatch.setattr(
        ws_mod, "_KNOWN_HOSTS_CANDIDATES", ["/nonexistent/known_hosts", str(kh)]
    )
    client = ws_mod._make_client("ws-host")
    assert client._client_keys == [str(key)]
    assert client._known_hosts == str(kh)


def test_make_client_prefers_canonical_path(monkeypatch, tmp_path):
    canonical = tmp_path / "vystak-ssh" / "id_ed25519"
    canonical.parent.mkdir()
    canonical.write_text("KEY")
    monkeypatch.setattr(
        ws_mod, "_SSH_KEY_CANDIDATES", [str(canonical), "/other/id_ed25519"]
    )
    client = ws_mod._make_client("ws-host")
    assert client._client_keys == [str(canonical)]
