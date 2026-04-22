"""Entry point. sshd runs this as the `vystak-rpc` subsystem.

Reads WORKSPACE_ROOT and TOOLS_DIR from env; defaults to /workspace and
/workspace/tools. Builds a JsonRpcServer with all services registered,
runs it against stdin/stdout.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from vystak_workspace_rpc.server import JsonRpcServer, run_stdio
from vystak_workspace_rpc.services.exec import register_exec
from vystak_workspace_rpc.services.fs import register_fs
from vystak_workspace_rpc.services.git import register_git
from vystak_workspace_rpc.services.tool import register_tool


def build_server(workspace_root: Path, tools_dir: Path) -> JsonRpcServer:
    """Build a JsonRpcServer with all services registered."""
    srv = JsonRpcServer()

    async def progress_emitter(channel: str, data: dict) -> None:
        """Forward to stdout as a JSON-RPC $/progress notification."""
        note = {
            "jsonrpc": "2.0",
            "method": "$/progress",
            "params": {"channel": channel, **data},
        }
        sys.stdout.write(json.dumps(note) + "\n")
        sys.stdout.flush()

    register_fs(srv, workspace_root)
    register_exec(srv, workspace_root, progress_emitter=progress_emitter)
    register_git(srv, workspace_root)
    register_tool(srv, tools_dir)
    return srv


def main() -> None:
    workspace_root = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))
    tools_dir = Path(os.environ.get("TOOLS_DIR", str(workspace_root / "tools")))
    srv = build_server(workspace_root, tools_dir)
    asyncio.run(run_stdio(srv))


if __name__ == "__main__":
    main()
