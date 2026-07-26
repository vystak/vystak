"""Agent-side SSH client for the workspace JSON-RPC subsystem.

Manages one persistent asyncssh connection; opens a channel per tool
call to the vystak-rpc subsystem; reads JSONL responses. If the cached
connection has died (e.g. ACA idle-timeout RST), reconnects once.
"""

import asyncio
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
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._conn is not None:
            return
        async with self._connect_lock:
            if self._conn is not None:
                return
            self._conn = await asyncssh.connect(
                self._host,
                port=self._port,
                username=self._username,
                client_keys=self._client_keys,
                known_hosts=self._known_hosts,
                keepalive_interval=30,
            )

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None

    async def _open_process(self):
        """One SSH process per call. A dead cached connection (idle
        timeout, workspace restart) surfaces here — reconnect once."""
        await self.connect()
        assert self._conn is not None
        try:
            return await self._conn.create_process(subsystem="vystak-rpc")
        except (OSError, asyncssh.Error):
            self._conn = None
            await self.connect()
            assert self._conn is not None
            return await self._conn.create_process(subsystem="vystak-rpc")

    async def invoke(self, method: str, **params) -> object:
        """Single-shot call. Returns result or raises RuntimeError."""
        proc = await self._open_process()
        req = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": method,
            "params": params,
        }
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.write_eof()
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    raise RuntimeError(
                        f"RPC channel closed without response for {method}"
                    )
                msg = json.loads(line)
                if msg.get("method") == "$/progress":
                    continue
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                if "result" in msg:
                    return msg["result"]
        finally:
            proc.close()
            await proc.wait_closed()

    async def invoke_stream(self, method: str, **params) -> AsyncIterator[object]:
        """Streaming call. Yields `$/progress` params dicts, then the result."""
        proc = await self._open_process()
        req = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": method,
            "params": params,
        }
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.write_eof()
        try:
            while True:
                line = await proc.stdout.readline()
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
        finally:
            proc.close()
            await proc.wait_closed()
