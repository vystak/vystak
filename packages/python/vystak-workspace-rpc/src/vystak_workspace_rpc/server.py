"""JSON-RPC 2.0 server over stdio, with per-channel dispatch.

Reads newline-delimited JSON from stdin, writes responses to stdout.
One instance per SSH channel (one process spawned by sshd for each
`subsystem vystak-rpc` request).
"""

import asyncio
import json
import sys
from collections.abc import Callable

# JSON-RPC 2.0 error codes
ERROR_PARSE = -32700
ERROR_INVALID_REQUEST = -32600
ERROR_METHOD_NOT_FOUND = -32601
ERROR_INVALID_PARAMS = -32602
ERROR_INTERNAL = -32603
ERROR_SERVER = -32000  # implementation-defined server error


class JsonRpcServer:
    """Minimal JSON-RPC 2.0 handler.

    Register methods via register(); call handle_line() to process one
    request line and get the response line (or None for notifications).
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable] = {}

    def register(self, method: str, handler: Callable) -> None:
        """Register an async handler(params: dict) -> Any."""
        self._handlers[method] = handler

    async def handle_line(self, line: str) -> str | None:
        """Process one JSON-RPC request line. Returns response line or None."""
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            return self._error_response(None, ERROR_PARSE, f"Parse error: {e}")

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method is None:
            return self._error_response(req_id, ERROR_INVALID_REQUEST,
                                        "Invalid Request: method missing")

        handler = self._handlers.get(method)
        if handler is None:
            if req_id is None:
                return None  # notification to unknown method, silent
            return self._error_response(req_id, ERROR_METHOD_NOT_FOUND,
                                        f"Method not found: {method}")

        try:
            result = await handler(params)
        except Exception as e:  # noqa: BLE001
            if req_id is None:
                return None  # notification errors are silent
            return self._error_response(req_id, ERROR_SERVER, str(e))

        if req_id is None:
            return None  # notification: no response

        return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})

    def _error_response(self, req_id, code: int, message: str,
                        data: dict | None = None) -> str:
        err = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return json.dumps({"jsonrpc": "2.0", "id": req_id, "error": err})


async def run_stdio(server: JsonRpcServer) -> None:
    """Read JSONL from stdin, write JSONL responses to stdout."""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line_bytes = await reader.readline()
        if not line_bytes:
            return  # EOF
        line = line_bytes.decode("utf-8").rstrip("\n")
        if not line:
            continue
        resp = await server.handle_line(line)
        if resp is not None:
            sys.stdout.write(resp + "\n")
            sys.stdout.flush()
