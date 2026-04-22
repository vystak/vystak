"""Tests for exec.* service."""

import pytest
from vystak_workspace_rpc.services.exec import register_exec


def _build_server(workspace_root, chunks_out):
    from vystak_workspace_rpc.server import JsonRpcServer

    srv = JsonRpcServer()

    async def progress_sink(channel: str, data: dict):
        chunks_out.append((channel, data))

    register_exec(srv, workspace_root, progress_emitter=progress_sink)
    return srv


@pytest.mark.asyncio
async def test_exec_run_success(tmp_path):
    chunks = []
    srv = _build_server(tmp_path, chunks)
    result = await srv._handlers["exec.run"]({
        "cmd": ["echo", "hello"], "cwd": "."
    })
    assert result["exit_code"] == 0
    assert any("hello" in c[1].get("chunk", "") for c in chunks)


@pytest.mark.asyncio
async def test_exec_run_nonzero_exit(tmp_path):
    chunks = []
    srv = _build_server(tmp_path, chunks)
    result = await srv._handlers["exec.run"]({
        "cmd": ["sh", "-c", "exit 3"]
    })
    assert result["exit_code"] == 3


@pytest.mark.asyncio
async def test_exec_run_streams_stdout(tmp_path):
    chunks = []
    srv = _build_server(tmp_path, chunks)
    await srv._handlers["exec.run"]({
        "cmd": ["sh", "-c", "echo line1; echo line2"]
    })
    stdout_chunks = [c[1]["chunk"] for c in chunks if c[0] == "stdout"]
    combined = "".join(stdout_chunks)
    assert "line1" in combined and "line2" in combined


@pytest.mark.asyncio
async def test_exec_shell_runs_script(tmp_path):
    chunks = []
    srv = _build_server(tmp_path, chunks)
    result = await srv._handlers["exec.shell"]({
        "script": "echo hi && false || echo recovered"
    })
    assert result["exit_code"] == 0
    combined = "".join(c[1].get("chunk", "") for c in chunks)
    assert "hi" in combined and "recovered" in combined


@pytest.mark.asyncio
async def test_exec_run_timeout(tmp_path):
    chunks = []
    srv = _build_server(tmp_path, chunks)
    with pytest.raises(TimeoutError):
        await srv._handlers["exec.run"]({
            "cmd": ["sleep", "10"], "timeout_s": 0.2
        })


@pytest.mark.asyncio
async def test_exec_which_found(tmp_path):
    chunks = []
    srv = _build_server(tmp_path, chunks)
    result = await srv._handlers["exec.which"]({"name": "sh"})
    assert result is not None
    assert "sh" in result


@pytest.mark.asyncio
async def test_exec_which_not_found(tmp_path):
    chunks = []
    srv = _build_server(tmp_path, chunks)
    result = await srv._handlers["exec.which"]({"name": "definitely_not_a_real_command_12345"})
    assert result is None
