"""Agent-side SSH client for the workspace JSON-RPC subsystem.

Manages one persistent asyncssh connection; opens a channel per tool
call to the vystak-rpc subsystem; reads JSONL responses.
"""

import json
import uuid
from collections.abc import AsyncIterator

import asyncssh


class WorkspaceRpcClient:
    def __init__(
        self,
        *,
        host: str,
        port: int = 22,
        username: str = "vystak-agent",
        client_keys: list[str],
        known_hosts: str | None,
    ):
        self._host = host
        self._port = port
        self._username = username
        self._client_keys = list(client_keys)
        self._known_hosts = known_hosts
        self._conn: asyncssh.SSHClientConnection | None = None

    async def connect(self) -> None:
        if self._conn is not None:
            return
        self._conn = await asyncssh.connect(
            self._host,
            port=self._port,
            username=self._username,
            client_keys=self._client_keys,
            known_hosts=self._known_hosts,
        )

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None

    async def _open_channel(self):
        """Open one SSH channel to the vystak-rpc subsystem."""
        assert self._conn is not None, "connect() first"
        # asyncssh: use create_session for subsystem access
        chan, _session = await self._conn.create_session(
            asyncssh.SSHClientSession,
            subsystem="vystak-rpc",
        )
        return chan

    async def invoke(self, method: str, **params) -> object:
        """Single-shot call. Returns result or raises on error."""
        await self.connect()
        chan = await self._open_channel()
        req = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": method,
            "params": params,
        }
        chan.write(json.dumps(req) + "\n")
        chan.write_eof()

        while True:
            line = await chan.readline()
            if not line:
                raise RuntimeError(f"RPC channel closed without response for {method}")
            msg = json.loads(line)
            if msg.get("method") == "$/progress":
                continue  # skip progress for non-streaming invoke
            if "error" in msg:
                err = msg["error"]
                raise RuntimeError(f"{method}: {err.get('message')}")
            if "result" in msg:
                return msg["result"]

    async def invoke_stream(self, method: str, **params) -> AsyncIterator[object]:
        """Streaming call. Yields progress chunks (dicts from params) then
        the final result. Caller consumes via `async for`."""
        await self.connect()
        chan = await self._open_channel()
        req = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": method,
            "params": params,
        }
        chan.write(json.dumps(req) + "\n")
        chan.write_eof()

        while True:
            line = await chan.readline()
            if not line:
                return
            msg = json.loads(line)
            if msg.get("method") == "$/progress":
                yield msg.get("params", {})
                continue
            if "error" in msg:
                raise RuntimeError(f"{method}: {msg['error'].get('message')}")
            if "result" in msg:
                yield msg["result"]
                return
