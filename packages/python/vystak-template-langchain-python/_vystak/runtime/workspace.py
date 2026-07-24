"""Built-in workspace tools — SSH-RPC wrappers exposed to the LLM.

Follows the subagents/mcp builder pattern: returns [] when the agent has
no workspace (or the deploy didn't wire one), degrades to [] with a
warning when asyncssh is unavailable, and returns tool errors as strings
so the LLM turn survives.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_SSH_KEY_CANDIDATES = ["/vystak/ssh/id_ed25519", "/shared/ssh/id_ed25519"]
_KNOWN_HOSTS_CANDIDATES = ["/vystak/ssh/known_hosts", "/shared/ssh/known_hosts"]


def _first_existing(candidates: list[str]) -> str:
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


def _make_client(host: str):
    from _vystak.runtime.workspace_client import WorkspaceRpcClient

    return WorkspaceRpcClient(
        host=host,
        client_keys=[_first_existing(_SSH_KEY_CANDIDATES)],
        known_hosts=_first_existing(_KNOWN_HOSTS_CANDIDATES),
    )


def build_workspace_tools(agent: Any) -> list[Any]:
    if getattr(agent, "workspace", None) is None:
        return []
    host = os.environ.get("VYSTAK_WORKSPACE_HOST")
    if not host:
        return []
    try:
        import asyncssh  # noqa: F401
    except ImportError:
        logger.warning(
            "workspace tools disabled: asyncssh is not installed"
        )
        return []
    from langchain_core.tools import tool

    client = _make_client(host)

    def _err(method: str, e: Exception) -> str:
        return f"Error calling {method}: {type(e).__name__}: {e}"

    @tool
    async def read_file(path: str) -> object:
        """Read a text file from the workspace. Path is relative to /workspace."""
        try:
            return await client.invoke("fs.readFile", path=path)
        except Exception as e:
            return _err("fs.readFile", e)

    @tool
    async def write_file(path: str, content: str) -> object:
        """Write a text file in the workspace (creates or overwrites).
        Path is relative to /workspace."""
        try:
            return await client.invoke("fs.writeFile", path=path, content=content)
        except Exception as e:
            return _err("fs.writeFile", e)

    @tool
    async def list_dir(path: str = ".") -> object:
        """List a workspace directory. Returns name/type/size/mtime entries."""
        try:
            return await client.invoke("fs.listDir", path=path)
        except Exception as e:
            return _err("fs.listDir", e)

    @tool
    async def edit_file(path: str, old_str: str, new_str: str) -> object:
        """Replace one occurrence of old_str with new_str in a workspace file.
        Returns a unified diff."""
        try:
            return await client.invoke(
                "fs.edit", path=path, old_str=old_str, new_str=new_str
            )
        except Exception as e:
            return _err("fs.edit", e)

    async def _stream(method: str, **params) -> str:
        chunks: list[str] = []
        final: dict = {}
        async for item in client.invoke_stream(method, **params):
            if isinstance(item, dict) and "chunk" in item:
                chunks.append(item["chunk"])
            elif isinstance(item, dict):
                final = item
        output = "".join(chunks)
        return f"{output}\n[exit_code={final.get('exit_code')}]"

    @tool
    async def run(cmd: str) -> object:
        """Run a command in the workspace (cwd /workspace). Returns its output and exit code."""
        try:
            return await _stream("exec.run", cmd=cmd)
        except Exception as e:
            return _err("exec.run", e)

    @tool
    async def shell(script: str) -> object:
        """Run a shell script in the workspace. Returns its output and exit code."""
        try:
            return await _stream("exec.shell", script=script)
        except Exception as e:
            return _err("exec.shell", e)

    @tool
    async def git_status() -> object:
        """Git status of the workspace repo (branch, staged, unstaged, untracked)."""
        try:
            return await client.invoke("git.status")
        except Exception as e:
            return _err("git.status", e)

    @tool
    async def git_diff() -> object:
        """Unstaged git diff of the workspace repo."""
        try:
            return await client.invoke("git.diff")
        except Exception as e:
            return _err("git.diff", e)

    @tool
    async def git_commit(message: str, paths: list[str]) -> object:
        """Stage the given paths and commit them in the workspace repo."""
        try:
            await client.invoke("git.add", paths=paths)
            return await client.invoke("git.commit", message=message)
        except Exception as e:
            return _err("git.commit", e)

    return [
        read_file, write_file, list_dir, edit_file,
        run, shell, git_status, git_diff, git_commit,
    ]
