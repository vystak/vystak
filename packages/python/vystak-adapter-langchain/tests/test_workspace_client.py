"""Tests for the agent-side WorkspaceRpcClient."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from vystak_adapter_langchain.workspace_client import WorkspaceRpcClient


def _mock_process(readline_values):
    """Return a mocked SSHClientProcess with readline producing the given
    values in order (values can be a single string or a list via side_effect)."""
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.write_eof = MagicMock()
    proc.stdout = MagicMock()
    if isinstance(readline_values, list):
        proc.stdout.readline = AsyncMock(side_effect=readline_values)
    else:
        proc.stdout.readline = AsyncMock(return_value=readline_values)
    proc.close = MagicMock()
    proc.wait_closed = AsyncMock(return_value=None)
    return proc


@pytest.mark.asyncio
async def test_invoke_sends_jsonrpc_and_returns_result():
    """Non-streaming call sends one request, reads one response line."""
    client = WorkspaceRpcClient(
        host="test-workspace",
        port=22,
        username="vystak-agent",
        client_keys=["/fake/key"],
        known_hosts="/fake/known_hosts",
    )
    client._conn = AsyncMock()

    response_line = json.dumps({"jsonrpc": "2.0", "id": "x", "result": "hi"}) + "\n"
    proc = _mock_process(response_line)

    with patch.object(client, "_open_process", AsyncMock(return_value=proc)):
        result = await client.invoke("fs.readFile", path="foo.py")

    assert result == "hi"
    proc.stdin.write.assert_called_once()
    proc.stdin.write_eof.assert_called_once()
    proc.close.assert_called_once()


@pytest.mark.asyncio
async def test_invoke_raises_on_error_response():
    client = WorkspaceRpcClient(
        host="x",
        port=22,
        username="u",
        client_keys=["/k"],
        known_hosts="/kh",
    )
    client._conn = AsyncMock()

    err_line = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "x",
                "error": {"code": -32000, "message": "disk full"},
            }
        )
        + "\n"
    )
    proc = _mock_process(err_line)

    with (
        patch.object(client, "_open_process", AsyncMock(return_value=proc)),
        pytest.raises(Exception, match="disk full"),
    ):
        await client.invoke("fs.readFile", path="foo.py")


@pytest.mark.asyncio
async def test_invoke_stream_yields_progress_then_result():
    """Streaming call: multiple progress notifications then final result."""
    progress = json.dumps(
        {"jsonrpc": "2.0", "method": "$/progress", "params": {"chunk": "hello\n"}}
    )
    final = json.dumps({"jsonrpc": "2.0", "id": "x", "result": {"exit_code": 0}})

    client = WorkspaceRpcClient(
        host="x",
        port=22,
        username="u",
        client_keys=["/k"],
        known_hosts="/kh",
    )
    client._conn = AsyncMock()

    proc = _mock_process([progress + "\n", final + "\n", ""])

    with patch.object(client, "_open_process", AsyncMock(return_value=proc)):
        chunks = []
        async for item in client.invoke_stream("exec.run", cmd=["echo", "hello"]):
            chunks.append(item)

    assert chunks[-1] == {"exit_code": 0}
    assert any(
        "hello" in (c.get("chunk", "") if isinstance(c, dict) else "")
        for c in chunks[:-1]
    )
