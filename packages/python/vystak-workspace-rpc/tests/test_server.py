"""Tests for the JSON-RPC 2.0 server core."""

import json

import pytest
from vystak_workspace_rpc.server import JsonRpcServer


@pytest.mark.asyncio
async def test_server_handles_single_request():
    async def echo(params):
        return {"echoed": params.get("message", "")}

    srv = JsonRpcServer()
    srv.register("test.echo", echo)

    req = json.dumps({"jsonrpc": "2.0", "id": "1", "method": "test.echo",
                      "params": {"message": "hi"}})
    response_line = await srv.handle_line(req)
    assert response_line is not None
    resp = json.loads(response_line)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == "1"
    assert resp["result"] == {"echoed": "hi"}


@pytest.mark.asyncio
async def test_server_handles_unknown_method():
    srv = JsonRpcServer()
    req = json.dumps({"jsonrpc": "2.0", "id": "2", "method": "nope", "params": {}})
    line = await srv.handle_line(req)
    resp = json.loads(line)
    assert resp["error"]["code"] == -32601
    assert "Method not found" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_server_handles_handler_exception():
    async def boom(params):
        raise ValueError("kaboom")

    srv = JsonRpcServer()
    srv.register("test.boom", boom)

    req = json.dumps({"jsonrpc": "2.0", "id": "3", "method": "test.boom", "params": {}})
    line = await srv.handle_line(req)
    resp = json.loads(line)
    assert resp["error"]["code"] == -32000
    assert "kaboom" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_server_handles_malformed_json():
    srv = JsonRpcServer()
    line = await srv.handle_line("not json {")
    resp = json.loads(line)
    assert resp["error"]["code"] == -32700
    assert "Parse error" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_server_notification_has_no_response():
    """Requests without an id are notifications — no response expected."""
    async def noop(params):
        return None

    srv = JsonRpcServer()
    srv.register("test.noop", noop)
    req = json.dumps({"jsonrpc": "2.0", "method": "test.noop", "params": {}})
    line = await srv.handle_line(req)
    assert line is None
