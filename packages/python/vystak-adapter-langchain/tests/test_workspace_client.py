"""Tests for the agent-side WorkspaceRpcClient."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from vystak_adapter_langchain.workspace_client import WorkspaceRpcClient


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

    mock_channel = AsyncMock()
    # The response will be written to the write side; we simulate it on read
    response_line = json.dumps({"jsonrpc": "2.0", "id": "x", "result": "hi"})
    mock_channel.readline = AsyncMock(return_value=response_line + "\n")

    mock_conn = AsyncMock()
    mock_conn.create_session = AsyncMock(return_value=(mock_channel, None))

    with patch.object(client, "_conn", mock_conn):
        client._conn = mock_conn

        # Short-circuit _open_channel to return mock_channel
        with patch.object(client, "_open_channel", AsyncMock(return_value=mock_channel)):
            result = await client.invoke("fs.readFile", path="foo.py")
    assert result == "hi"


@pytest.mark.asyncio
async def test_invoke_raises_on_error_response():
    client = WorkspaceRpcClient(
        host="x",
        port=22,
        username="u",
        client_keys=["/k"],
        known_hosts="/kh",
    )
    # Short-circuit connect() by pre-populating _conn
    client._conn = AsyncMock()
    err_line = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "x",
            "error": {"code": -32000, "message": "disk full"},
        }
    )
    mock_channel = AsyncMock()
    mock_channel.readline = AsyncMock(return_value=err_line + "\n")
    with (
        patch.object(client, "_open_channel", AsyncMock(return_value=mock_channel)),
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
    # Short-circuit connect() by pre-populating _conn
    client._conn = AsyncMock()

    lines = [progress + "\n", final + "\n", ""]
    mock_channel = AsyncMock()
    mock_channel.readline = AsyncMock(side_effect=lines)

    with patch.object(client, "_open_channel", AsyncMock(return_value=mock_channel)):
        chunks = []
        async for item in client.invoke_stream("exec.run", cmd=["echo", "hello"]):
            chunks.append(item)

    # Last item is the result; earlier items are progress chunks
    assert chunks[-1] == {"exit_code": 0}
    assert any(
        "hello" in (c.get("chunk", "") if isinstance(c, dict) else "") for c in chunks[:-1]
    )
