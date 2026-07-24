# Workspace Tools + Seed Folders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the workspace SSH-RPC services (`fs`/`exec`/`git`) as built-in LLM tools in the agent template, fix the default-path `known_hosts` gap, and add `workspaces/<name>/` seed folders copied into `/workspace` with copy-if-absent semantics.

**Architecture:** Two new managed modules in the template runtime (`workspace_client.py`, `workspace.py`) wired into `app_factory` at both `build_graph` call sites. Both providers converge on SSH material as files at `/vystak/ssh/*` (Docker default path gains a generated `known_hosts`; the Azure entrypoint shim already materializes env → files and gains a host-prefix fix). Seeding is image-staged at `/vystak/seed/` and applied by a new always-present workspace entrypoint via `cp -rn`.

**Tech Stack:** Python 3.11+, asyncssh, LangChain `@tool`, docker SDK, pytest.

**Spec:** `docs/superpowers/specs/2026-07-24-workspace-tools-and-seed-design.md`

**Spec deviation (recorded):** the spec's §1 "SSH material resolution" described an env-var branch for Azure. Investigation showed the entrypoint shim (`templates.py:generate_entrypoint_shim`) *already* materializes `VYSTAK_SSH_CLIENT_KEY` → `/vystak/ssh/id_ed25519` and `VYSTAK_SSH_KNOWN_HOSTS_PUB` → `/vystak/ssh/known_hosts`. The runtime therefore reads **file paths only** (same as the prototype), and the shim gets a fix instead: its known_hosts write lacks the required `<host> ` prefix (Task 5). Same one-client-serves-both-providers outcome, less code.

## Global Constraints

- Run all commands from repo root. Lint gate: `just lint-python` only (pyright has ~370 pre-existing failures — not a gate).
- Template runtime import style is absolute: `from _vystak.runtime.<mod> import <name>`. Template tests live in `packages/python/vystak-template-langchain-python/tests/` and import the same way.
- New runtime files MUST live under `_vystak/` (managed, refreshed by `vystak update`); the `asyncssh` dependency goes in `_vystak/requirements.txt`, NEVER the user-owned `requirements.txt`.
- Tool errors are returned as strings, never raised (LLM turn must survive).
- Canonical SSH paths inside the agent container: `/vystak/ssh/id_ed25519`, `/vystak/ssh/known_hosts`. Env var: `VYSTAK_WORKSPACE_HOST`.
- Seed source folder: `workspaces/<workspace-name>/` in the project dir; image staging dir `/vystak/seed/`; semantics **copy-if-absent** (`cp -rn`); absent folder → zero behavior change.
- `packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py` has an E501 per-file-ignore for emitted strings — do not mechanically wrap lines inside emitted scripts.
- Public repo: examples use placeholder values only.

---

### Task 1: `WorkspaceRpcClient` runtime module + asyncssh dependency

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/workspace_client.py`
- Modify: `packages/python/vystak-template-langchain-python/_vystak/requirements.txt` (append one line)
- Test: `packages/python/vystak-template-langchain-python/tests/test_workspace_client.py`

**Interfaces:**
- Produces: `class WorkspaceRpcClient` with keyword-only ctor `(host: str, port: int = 22, username: str = "vystak-agent", client_keys: list[str], known_hosts: str | None)`; `async connect()`, `async close()`, `async invoke(method, **params) -> object`, `async invoke_stream(method, **params) -> AsyncIterator[object]`. Task 2 imports it as `from _vystak.runtime.workspace_client import WorkspaceRpcClient`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/python/vystak-template-langchain-python/tests/test_workspace_client.py
"""WorkspaceRpcClient framing + reconnect tests (no real SSH)."""

import json

import pytest
from _vystak.runtime.workspace_client import WorkspaceRpcClient


class FakeStream:
    def __init__(self, lines: list[str]):
        self._lines = list(lines)
        self.written: list[str] = []

    def write(self, data: str) -> None:
        self.written.append(data)

    def write_eof(self) -> None:
        self.written.append("<EOF>")

    async def readline(self) -> str:
        return self._lines.pop(0) if self._lines else ""


class FakeProcess:
    def __init__(self, out_lines: list[str]):
        self.stdin = FakeStream([])
        self.stdout = FakeStream(out_lines)
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


class FakeConn:
    def __init__(self, out_lines: list[str], fail_first: bool = False):
        self._out_lines = out_lines
        self._fail_first = fail_first
        self.processes: list[FakeProcess] = []

    async def create_process(self, subsystem: str):
        assert subsystem == "vystak-rpc"
        if self._fail_first:
            self._fail_first = False
            raise OSError("connection lost")
        proc = FakeProcess(list(self._out_lines))
        self.processes.append(proc)
        return proc

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


def _client() -> WorkspaceRpcClient:
    return WorkspaceRpcClient(
        host="ws", client_keys=["/vystak/ssh/id_ed25519"],
        known_hosts="/vystak/ssh/known_hosts",
    )


@pytest.mark.asyncio
async def test_invoke_returns_result_and_skips_progress():
    c = _client()
    c._conn = FakeConn([
        json.dumps({"jsonrpc": "2.0", "method": "$/progress", "params": {"chunk": "x"}}) + "\n",
        json.dumps({"jsonrpc": "2.0", "id": "1", "result": {"ok": True}}) + "\n",
    ])
    assert await c.invoke("fs.exists", path="a.txt") == {"ok": True}
    req = json.loads(c._conn.processes[0].stdin.written[0])
    assert req["method"] == "fs.exists"
    assert req["params"] == {"path": "a.txt"}


@pytest.mark.asyncio
async def test_invoke_raises_on_rpc_error():
    c = _client()
    c._conn = FakeConn([
        json.dumps({"jsonrpc": "2.0", "id": "1", "error": {"message": "no such file"}}) + "\n",
    ])
    with pytest.raises(RuntimeError, match="no such file"):
        await c.invoke("fs.readFile", path="missing.txt")


@pytest.mark.asyncio
async def test_invoke_stream_yields_progress_then_result():
    c = _client()
    c._conn = FakeConn([
        json.dumps({"jsonrpc": "2.0", "method": "$/progress", "params": {"channel": "stdout", "chunk": "hi"}}) + "\n",
        json.dumps({"jsonrpc": "2.0", "id": "1", "result": {"exit_code": 0}}) + "\n",
    ])
    items = [item async for item in c.invoke_stream("exec.run", cmd="echo hi")]
    assert items == [{"channel": "stdout", "chunk": "hi"}, {"exit_code": 0}]


@pytest.mark.asyncio
async def test_open_process_reconnects_once_on_dropped_connection(monkeypatch):
    c = _client()
    dead = FakeConn([], fail_first=True)
    fresh = FakeConn([
        json.dumps({"jsonrpc": "2.0", "id": "1", "result": []}) + "\n",
    ])
    c._conn = dead

    async def fake_connect():
        c._conn = fresh

    monkeypatch.setattr(c, "connect", fake_connect)
    assert await c.invoke("fs.listDir", path=".") == []
    assert len(fresh.processes) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_workspace_client.py -v`
Expected: ERROR — `ModuleNotFoundError: No module named '_vystak.runtime.workspace_client'`
(If `pytest.mark.asyncio` errors instead: check `tests/conftest.py` / template dev deps for the async test plugin the existing template tests use, and match it.)

- [ ] **Step 3: Write the module**

```python
# packages/python/vystak-template-langchain-python/_vystak/runtime/workspace_client.py
"""Agent-side SSH client for the workspace JSON-RPC subsystem.

Manages one persistent asyncssh connection; opens a channel per tool
call to the vystak-rpc subsystem; reads JSONL responses. If the cached
connection has died (e.g. ACA idle-timeout RST), reconnects once.
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
```

Append to `packages/python/vystak-template-langchain-python/_vystak/requirements.txt`:

```
asyncssh>=2.14
```

(Also check whether the template's dev/test environment installs `_vystak/requirements.txt` — if the repo test env lacks asyncssh, add `asyncssh>=2.14` to the template package's test extras/dev deps the same way its other test-only deps are declared, so `uv sync` provides it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv sync && uv run pytest packages/python/vystak-template-langchain-python/tests/test_workspace_client.py -v`
Expected: 4 passed

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-template-langchain-python/
git commit -m "feat(template): WorkspaceRpcClient runtime module with reconnect-once"
```

---

### Task 2: `build_workspace_tools` + app_factory wiring

**Files:**
- Create: `packages/python/vystak-template-langchain-python/_vystak/runtime/workspace.py`
- Modify: `packages/python/vystak-template-langchain-python/_vystak/runtime/app_factory.py` (lines ~96-98 TODO block; tool lists at the `build_graph` calls ~line 120 and ~line 166 — `workspace_tools` is already present in both lists, so only the TODO block changes)
- Test: `packages/python/vystak-template-langchain-python/tests/test_workspace_tools.py`

**Interfaces:**
- Consumes: `WorkspaceRpcClient` from Task 1.
- Produces: `build_workspace_tools(agent) -> list[Any]` in `_vystak.runtime.workspace`. Tool names (exact): `read_file, write_file, list_dir, edit_file, run, shell, git_status, git_diff, git_commit`. Module-level `_make_client()` factory (patchable in tests and reused by nothing else).

- [ ] **Step 1: Write the failing tests**

```python
# packages/python/vystak-template-langchain-python/tests/test_workspace_tools.py
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

    class FakeClient:
        async def invoke_stream(self, method, **params):
            assert method == "exec.run"
            yield {"channel": "stdout", "chunk": "hello\n"}
            yield {"channel": "stderr", "chunk": "warn\n"}
            yield {"exit_code": 0, "duration_ms": 3}

    monkeypatch.setattr(ws_mod, "_make_client", lambda host: FakeClient())
    tools = {t.name: t for t in build_workspace_tools(_agent())}
    result = await tools["run"].ainvoke({"cmd": "echo hello"})
    assert "hello" in result and "exit_code=0" in result


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/test_workspace_tools.py -v`
Expected: ERROR — `ModuleNotFoundError: No module named '_vystak.runtime.workspace'`

- [ ] **Step 3: Write the module**

```python
# packages/python/vystak-template-langchain-python/_vystak/runtime/workspace.py
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


def _make_client(host: str):
    from _vystak.runtime.workspace_client import WorkspaceRpcClient

    return WorkspaceRpcClient(
        host=host,
        client_keys=["/vystak/ssh/id_ed25519"],
        known_hosts="/vystak/ssh/known_hosts",
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
        """Write a text file in the workspace (creates or overwrites). Path is relative to /workspace."""
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
        """Replace one occurrence of old_str with new_str in a workspace file. Returns a unified diff."""
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
```

In `app_factory.py`, add the import (alphabetical among the `_vystak.runtime` imports):

```python
from _vystak.runtime.workspace import build_workspace_tools
```

and replace the TODO block (lines ~96-98):

```python
    workspace_tools = build_workspace_tools(agent)
```

(The tool lists at both `build_graph` call sites already include `workspace_tools` — verify both still do; no other change.)

- [ ] **Step 4: Run the template test suite**

Run: `uv run pytest packages/python/vystak-template-langchain-python/tests/ -q`
Expected: all pass (existing `test_app_factory.py` agents have no `workspace` attribute or it is None → `build_workspace_tools` returns `[]`; if a `SimpleNamespace` fixture lacks the attribute entirely, `getattr(..., None)` covers it).

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-template-langchain-python/
git commit -m "feat(template): wire workspace SSH-RPC tools into the agent graph"
```

---

### Task 3: Docker default-path `known_hosts`

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/agent.py` (default-path SSH mounts block, ~lines 254-266)
- Test: `packages/python/vystak-provider-docker/tests/test_agent_workspace.py` (append)

**Interfaces:**
- Consumes: `self._workspace_host` (set by `set_workspace_context`), `self._default_path_ssh_host_dir` (contains keygen output `host-key.pub`).
- Produces: `.vystak/ssh/<agent>/known_hosts` on the host with content `f"{workspace_host} {host_key_pub}\n"`, bind-mounted ro at `/shared/ssh/known_hosts`. Closes test_plan.md gap #2 (V11 on default path).

- [ ] **Step 1: Write the failing test** (append to `test_agent_workspace.py`, reusing its existing fixture/mock style — read the file's existing `test_set_workspace_context_populates_env` for the node-construction pattern and mirror it)

```python
def test_default_path_writes_and_mounts_known_hosts(tmp_path, monkeypatch):
    """Default path assembles known_hosts from host-key.pub + workspace host."""
    monkeypatch.chdir(tmp_path)
    ssh_dir = tmp_path / ".vystak" / "ssh" / "assistant"
    ssh_dir.mkdir(parents=True)
    (ssh_dir / "client-key").write_text("PRIVATE")
    (ssh_dir / "host-key.pub").write_text("ssh-ed25519 AAAATESTKEY comment\n")

    # Build the node exactly as the neighboring default-path test does,
    # then:
    node.set_workspace_context(workspace_host="vystak-assistant-workspace")
    node.set_default_path_context(env={}, ssh_host_dir=str(ssh_dir))
    result = node.provision(context=make_context())  # same helper as neighbors

    known_hosts = ssh_dir / "known_hosts"
    assert known_hosts.read_text() == (
        "vystak-assistant-workspace ssh-ed25519 AAAATESTKEY comment\n"
    )
    run_kwargs = docker_client.containers.run.call_args.kwargs
    assert run_kwargs["volumes"][str(known_hosts)] == {
        "bind": "/shared/ssh/known_hosts", "mode": "ro",
    }
```

**Implementer note:** the exact node-construction/`make_context` shape must come from the existing tests in this file (`test_set_workspace_context_populates_env` at ~line 27) — mirror it precisely; the assertions above are the contract. Check the actual method name(s) that configure the default path on `DockerAgentNode` (grep `_default_path_ssh_host_dir` for the setter) and use them.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_agent_workspace.py -v -k known_hosts`
Expected: FAIL — no `known_hosts` file written / not in volumes.

- [ ] **Step 3: Implement**

In `nodes/agent.py`, inside the default-path SSH mounts block (after the `host-key.pub` mount, ~line 266), add:

```python
                # Assemble known_hosts so the agent's asyncssh client can
                # verify the workspace host key (test_plan gap #2 / V11).
                host_key_pub_path = ssh_dir / "host-key.pub"
                if self._workspace_host and host_key_pub_path.exists():
                    known_hosts_path = ssh_dir / "known_hosts"
                    host_key_pub = host_key_pub_path.read_text().strip()
                    known_hosts_path.write_text(
                        f"{self._workspace_host} {host_key_pub}\n"
                    )
                    volumes[str(known_hosts_path)] = {
                        "bind": "/shared/ssh/known_hosts",
                        "mode": "ro",
                    }
```

- [ ] **Step 4: Run the provider suite**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/ -q`
Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-provider-docker/
git commit -m "fix(docker): assemble known_hosts on the default path (V11 gap)"
```

---

### Task 4: Workspace entrypoint + seed staging (generator + Docker node)

**Files:**
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py` (add `generate_workspace_entrypoint()`)
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/workspace_image.py` (`generate_workspace_dockerfile`)
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/nodes/workspace.py` (`provision()` staging)
- Test: `packages/python/vystak-provider-docker/tests/test_workspace_image.py` (append), `packages/python/vystak-provider-docker/tests/test_node_workspace.py` (append)

**Interfaces:**
- Produces: `generate_workspace_entrypoint() -> str` in `templates.py` (emitted shell script — E501-exempt file). Dockerfile now always contains `COPY seed/ /vystak/seed/`, `COPY workspace-entrypoint.sh /vystak/workspace-entrypoint.sh`; entrypoint chain: default path `ENTRYPOINT ["/vystak/workspace-entrypoint.sh"]` + `CMD ["/usr/sbin/sshd","-D","-e"]`; vault path `ENTRYPOINT ["/vystak/entrypoint-shim.sh"]` + `CMD ["/vystak/workspace-entrypoint.sh", "/usr/sbin/sshd", "-D", "-e"]` (the shim ends in `exec "$@"`, so it chains into the workspace entrypoint, which seeds then execs sshd). Docker node stages `workspaces/<ws.name>/` → `build_dir/seed/` (empty dir when absent) and writes `workspace-entrypoint.sh` into the build context. Task 5 reuses both from the Azure build.

- [ ] **Step 1: Write the failing tests**

Append to `test_workspace_image.py` (mirror its existing call style for `generate_workspace_dockerfile`):

```python
def test_dockerfile_stages_seed_and_workspace_entrypoint_default_path():
    df = generate_workspace_dockerfile(
        image="python:3.12-slim", provision=[], copy={},
        tool_deps_manager=None, use_entrypoint_shim=False,
    )
    assert "COPY seed/ /vystak/seed/" in df
    assert "COPY workspace-entrypoint.sh /vystak/workspace-entrypoint.sh" in df
    assert 'ENTRYPOINT ["/vystak/workspace-entrypoint.sh"]' in df
    assert 'CMD ["/usr/sbin/sshd", "-D", "-e"]' in df


def test_dockerfile_vault_path_chains_shim_then_workspace_entrypoint():
    df = generate_workspace_dockerfile(
        image="python:3.12-slim", provision=[], copy={},
        tool_deps_manager=None, use_entrypoint_shim=True,
    )
    assert 'ENTRYPOINT ["/vystak/entrypoint-shim.sh"]' in df
    assert 'CMD ["/vystak/workspace-entrypoint.sh", "/usr/sbin/sshd", "-D", "-e"]' in df


def test_workspace_entrypoint_script_copy_if_absent():
    from vystak_provider_docker.templates import generate_workspace_entrypoint

    script = generate_workspace_entrypoint()
    assert "cp -rn /vystak/seed/. /workspace/" in script
    assert 'exec "$@"' in script
```

Append to `test_node_workspace.py` (reuse its `_workspace`/provision invocation pattern):

```python
def test_provision_stages_seed_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seed_src = tmp_path / "workspaces" / "dev"
    seed_src.mkdir(parents=True)
    (seed_src / "hello.txt").write_text("seeded\n")
    # ... construct node exactly as neighboring tests (workspace name "dev"),
    # invoke provision ...
    build_dir = tmp_path / ".vystak" / "assistant-workspace"
    assert (build_dir / "seed" / "hello.txt").read_text() == "seeded\n"
    assert (build_dir / "workspace-entrypoint.sh").exists()


def test_provision_without_seed_folder_stages_empty_seed_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # ... construct node + provision as above, WITHOUT creating workspaces/dev ...
    build_dir = tmp_path / ".vystak" / "assistant-workspace"
    assert (build_dir / "seed").is_dir()
    assert list((build_dir / "seed").iterdir()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/test_workspace_image.py packages/python/vystak-provider-docker/tests/test_node_workspace.py -v -k "seed or entrypoint"`
Expected: new tests FAIL (no seed staging, no entrypoint function).

- [ ] **Step 3: Implement**

`templates.py` — add (emitted string; file is E501-exempt):

```python
def generate_workspace_entrypoint() -> str:
    """Workspace container entrypoint: seed /workspace (copy-if-absent),
    then exec the CMD (sshd).

    Runs on BOTH delivery paths — default path as ENTRYPOINT, Vault path
    chained after the secrets shim via CMD. `cp -rn` never overwrites
    existing files, so workspace-side edits and agent-written files
    survive re-applies; new seed files land on the next apply.
    """
    return """\
#!/bin/sh
# vystak workspace entrypoint — seed /workspace, then exec CMD
set -e

if [ -d /vystak/seed ] && [ -n "$(ls -A /vystak/seed 2>/dev/null)" ]; then
  cp -rn /vystak/seed/. /workspace/ 2>/dev/null || true
  chown -R vystak-agent /workspace 2>/dev/null || true
fi

exec "$@"
"""
```

`workspace_image.py` — in `generate_workspace_dockerfile`, after the tools/tool-deps block (~line 107) and before the entrypoint block, add:

```python
    # Seed folder — staged into the image; the workspace entrypoint copies
    # it into /workspace (copy-if-absent) at container start. A Dockerfile
    # COPY straight to /workspace would be shadowed by the volume mount.
    lines.append("COPY seed/ /vystak/seed/")
    lines.append("COPY workspace-entrypoint.sh /vystak/workspace-entrypoint.sh")
    lines.append(
        "RUN chmod +x /vystak/workspace-entrypoint.sh && "
        "chown -R vystak-agent /vystak/seed"
    )
```

and replace the entrypoint block (lines ~108-115):

```python
    # Entrypoint chain. Vault path: secrets shim first (ends in `exec "$@"`),
    # chaining into the workspace entrypoint via CMD. Default path: the
    # workspace entrypoint IS the entrypoint.
    if use_entrypoint_shim:
        lines.append("COPY entrypoint-shim.sh /vystak/entrypoint-shim.sh")
        lines.append("RUN chmod +x /vystak/entrypoint-shim.sh")
        lines.append('ENTRYPOINT ["/vystak/entrypoint-shim.sh"]')
        lines.append(
            'CMD ["/vystak/workspace-entrypoint.sh", "/usr/sbin/sshd", "-D", "-e"]'
        )
    else:
        lines.append('ENTRYPOINT ["/vystak/workspace-entrypoint.sh"]')
        lines.append('CMD ["/usr/sbin/sshd", "-D", "-e"]')
```

`nodes/workspace.py` — in `provision()`, after the tools staging block (~line 127), add:

```python
        # Seed folder — workspaces/<workspace-name>/ from the project dir.
        from vystak_provider_docker.templates import generate_workspace_entrypoint

        seed_dst = build_dir / "seed"
        if seed_dst.exists():
            shutil.rmtree(seed_dst)
        seed_src = Path("workspaces") / ws.name
        if seed_src.exists():
            shutil.copytree(seed_src, seed_dst)
        else:
            seed_dst.mkdir()
        (build_dir / "workspace-entrypoint.sh").write_text(
            generate_workspace_entrypoint()
        )
```

**Caveat for the user-provided-`dockerfile` path** (`ws.dockerfile`, ~line 85-87): the build context now always contains `seed/` and `workspace-entrypoint.sh`, but a custom Dockerfile controls its own COPY/ENTRYPOINT — seeding is a generated-Dockerfile feature. Do not fail custom-dockerfile builds; leave them untouched.

- [ ] **Step 4: Run the provider suite**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/ -q`
Expected: all pass (existing Dockerfile-content assertions in `test_workspace_image.py` may need the new lines accounted for **only if** they assert full-file equality — adjust those assertions, never weaken the new behavior).

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-provider-docker/
git commit -m "feat(docker): workspaces/<name> seed folders via workspace entrypoint (copy-if-absent)"
```

---

### Task 5: Azure parity — seed + tools staging, shim known_hosts host-prefix

**Files:**
- Modify: `packages/python/vystak-provider-azure/src/vystak_provider_azure/nodes/aca_workspace_app.py` (`_build_and_push_image`, ~lines 283-310)
- Modify: `packages/python/vystak-provider-docker/src/vystak_provider_docker/templates.py` (`generate_entrypoint_shim`, the `VYSTAK_SSH_KNOWN_HOSTS_PUB` block ~line 221-227)
- Test: `packages/python/vystak-provider-azure/tests/test_aca_workspace_app.py` (append), `packages/python/vystak-provider-docker/tests/test_templates.py` (append; if shim tests live elsewhere, colocate with the existing `generate_entrypoint_shim` tests — grep for it)

**Interfaces:**
- Consumes: `generate_workspace_entrypoint()` from Task 4.
- Produces: Azure workspace build context contains `tools/`, `seed/`, and `workspace-entrypoint.sh` (fixing the pre-existing missing-`tools/` staging). The shim writes `/vystak/ssh/known_hosts` as `"$VYSTAK_WORKSPACE_HOST $VYSTAK_SSH_KNOWN_HOSTS_PUB"` (a valid known_hosts entry) when the host var is set, falling back to the raw pub line otherwise.

- [ ] **Step 1: Write the failing tests**

Append to `test_aca_workspace_app.py` (mirror how existing tests in the file construct the node; if none drive `_build_and_push_image` directly, test the staging behavior by invoking it with a MagicMock docker client whose `images.build`/`images.push`/`login` are inert, from a tmp cwd):

```python
def test_build_context_stages_tools_seed_and_entrypoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "t.py").write_text("def t(): pass\n")
    seed = tmp_path / "workspaces" / "dev"
    seed.mkdir(parents=True)
    (seed / "hello.txt").write_text("seeded\n")

    node = _make_node()  # follow the file's existing node-construction helper/pattern; workspace name "dev", agent name "assistant"
    node._docker.images.push.return_value = [{}]
    node._build_and_push_image(
        acr_login_server="acr.azurecr.io",
        acr_username="acr",
        acr_password="pw",
    )
    build_dir = tmp_path / ".vystak" / "assistant-workspace-azure"
    assert (build_dir / "tools" / "t.py").exists()
    assert (build_dir / "seed" / "hello.txt").read_text() == "seeded\n"
    assert (build_dir / "workspace-entrypoint.sh").exists()
```

Shim test (colocate with existing `generate_entrypoint_shim` assertions):

```python
def test_shim_known_hosts_entry_is_host_prefixed():
    from vystak_provider_docker.templates import generate_entrypoint_shim

    shim = generate_entrypoint_shim()
    assert '"$VYSTAK_WORKSPACE_HOST" "$VYSTAK_SSH_KNOWN_HOSTS_PUB"' in shim
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/test_aca_workspace_app.py packages/python/vystak-provider-docker/tests/ -v -k "stages_tools or known_hosts_entry"`
Expected: FAIL (no tools/seed staging on Azure; shim writes unprefixed pub line).

- [ ] **Step 3: Implement**

`aca_workspace_app.py` `_build_and_push_image` — after the rpc bundle staging (~line 310), add:

```python
        # Tools + seed + workspace entrypoint — parity with the Docker
        # workspace node's build context (the generated Dockerfile COPYs
        # all three unconditionally).
        from vystak_provider_docker.templates import (
            generate_workspace_entrypoint,
        )

        tools_src = Path("tools")
        tools_dst = build_dir / "tools"
        if tools_dst.exists():
            shutil.rmtree(tools_dst)
        if tools_src.exists():
            shutil.copytree(tools_src, tools_dst)
        else:
            tools_dst.mkdir()

        seed_dst = build_dir / "seed"
        if seed_dst.exists():
            shutil.rmtree(seed_dst)
        seed_src = Path("workspaces") / ws.name
        if seed_src.exists():
            shutil.copytree(seed_src, seed_dst)
        else:
            seed_dst.mkdir()
        (build_dir / "workspace-entrypoint.sh").write_text(
            generate_workspace_entrypoint()
        )
```

`templates.py` `generate_entrypoint_shim` — replace the `VYSTAK_SSH_KNOWN_HOSTS_PUB` block's write line:

```sh
if [ -n "${VYSTAK_SSH_KNOWN_HOSTS_PUB:-}" ]; then
  mkdir -p /vystak/ssh
  if [ -n "${VYSTAK_WORKSPACE_HOST:-}" ]; then
    printf '%s %s\\n' "$VYSTAK_WORKSPACE_HOST" "$VYSTAK_SSH_KNOWN_HOSTS_PUB" > /vystak/ssh/known_hosts
  else
    printf '%s\\n' "$VYSTAK_SSH_KNOWN_HOSTS_PUB" > /vystak/ssh/known_hosts
  fi
  chmod 444 /vystak/ssh/known_hosts
  unset VYSTAK_SSH_KNOWN_HOSTS_PUB
fi
```

(A known_hosts line requires `<host> <keytype> <key>`; the raw pub line alone can never match. The agent app always has `VYSTAK_WORKSPACE_HOST` set when the pub secretRef is wired — the fallback branch just preserves old behavior for any other consumer.)

- [ ] **Step 4: Run both provider suites**

Run: `uv run pytest packages/python/vystak-provider-azure/tests/ packages/python/vystak-provider-docker/tests/ -q`
Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-provider-azure/ packages/python/vystak-provider-docker/
git commit -m "fix(azure): stage tools/seed into workspace image; host-prefixed known_hosts in shim"
```

---

### Task 6: V11 release cell (Docker default path, no LLM)

**Files:**
- Create: `packages/python/vystak-provider-docker/tests/release/test_workspace_tools_v11.py`

**Interfaces:**
- Consumes: everything above, plus the release `conftest.py` helpers (`project` fixture, `run`, `docker_exec`, `assert_apply_ok`, `assert_destroy_ok`, `docker_running`).

- [ ] **Step 1: Write the cell**

```python
# packages/python/vystak-provider-docker/tests/release/test_workspace_tools_v11.py
"""V11 + seed-folder cell — Docker default path, no LLM.

Proves the full agent→workspace SSH-RPC path (keys, known_hosts,
subsystem, jail) by running the shipped WorkspaceRpcClient INSIDE the
agent container, plus seed-folder copy-if-absent semantics across
re-applies. Sentinel API keys throughout.
"""

from __future__ import annotations

import pytest

from .conftest import (
    assert_apply_ok,
    assert_destroy_ok,
    docker_exec,
    docker_running,
    run,
)

pytestmark = [pytest.mark.release_smoke, pytest.mark.docker]


WS_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: wstools
    default_model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
      - {name: ANTHROPIC_API_URL}
    workspace:
      name: dev
      image: python:3.12-slim
"""

V11_SNIPPET = """\
import asyncio, os, sys
sys.path.insert(0, "/app")
from _vystak.runtime.workspace_client import WorkspaceRpcClient

async def main():
    c = WorkspaceRpcClient(
        host=os.environ["VYSTAK_WORKSPACE_HOST"],
        client_keys=["/vystak/ssh/id_ed25519"],
        known_hosts="/vystak/ssh/known_hosts",
    )
    entries = await c.invoke("fs.listDir", path=".")
    print(sorted(e["name"] for e in entries))
    await c.close()

asyncio.run(main())
"""


def test_workspace_tools_v11_and_seed(project):
    (project / "vystak.yaml").write_text(WS_YAML)
    seed = project / "workspaces" / "dev"
    seed.mkdir(parents=True)
    (seed / "hello.txt").write_text("seeded-v1\n")

    assert_apply_ok(project)
    assert docker_running("vystak-wstools")
    assert docker_running("vystak-wstools-workspace")

    # Seed landed in /workspace
    assert docker_exec(
        "vystak-wstools-workspace", "cat /workspace/hello.txt"
    ).strip() == "seeded-v1"

    # V11 — shipped client, inside the agent container, over real SSH.
    result = run(
        ["docker", "exec", "-i", "vystak-wstools", "python3", "-"],
        input=V11_SNIPPET,
    )
    assert "hello.txt" in result.stdout, (
        f"V11 fs.listDir failed:\n{result.stdout}\n{result.stderr}"
    )

    # Copy-if-absent across re-apply: mutate the seeded file in the
    # workspace, re-apply (rebuilds + restarts the workspace container),
    # assert the mutation survived and a NEW seed file arrived.
    docker_exec(
        "vystak-wstools-workspace",
        "sh -c 'echo mutated > /workspace/hello.txt'",
    )
    (seed / "extra.txt").write_text("new-file\n")
    assert_apply_ok(project)
    assert docker_exec(
        "vystak-wstools-workspace", "cat /workspace/hello.txt"
    ).strip() == "mutated"
    assert docker_exec(
        "vystak-wstools-workspace", "cat /workspace/extra.txt"
    ).strip() == "new-file"

    assert_destroy_ok(project)
```

**Implementer notes:** check `conftest.run`'s signature passes `**kw` through to `subprocess.run` (it does — `input=` works); check `assert_destroy_ok` exists in conftest (if the helper has a different name, use the one D1 uses). The workspace declaration intentionally has no channel — agents deploy fine without one (mirror D1 minus `channels:`).

- [ ] **Step 2: Run the cell against the local daemon**

Run: `uv run pytest packages/python/vystak-provider-docker/tests/release/test_workspace_tools_v11.py -v -m release_smoke`
Expected: PASS (this is the live gate for the whole feature — first run builds images, allow several minutes). If it fails, debug the actual gap; do not weaken assertions.

- [ ] **Step 3: Lint and commit**

```bash
just lint-python
git add packages/python/vystak-provider-docker/tests/release/
git commit -m "test(release): V11 workspace-tools + seed-folder cell (no LLM)"
```

---

### Task 7: Example + spec status

**Files:**
- Create: `examples/docker-workspace-tools/vystak.yaml`, `examples/docker-workspace-tools/workspaces/dev/analyze.sh`, `examples/docker-workspace-tools/workspaces/dev/data.csv`, `examples/docker-workspace-tools/README.md`
- Modify: `docs/superpowers/specs/2026-07-24-workspace-tools-and-seed-design.md` (status line)

- [ ] **Step 1: Write the example**

`vystak.yaml` (base provider/platform/model blocks on `examples/docker-shared-volume/vystak.yaml` — same shapes):

```yaml
# One agent with a workspace, seeded from workspaces/dev/, driven through
# the built-in workspace tools (read_file, write_file, run, git_*, ...).
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}

platforms:
  local: {type: docker, provider: docker}

models:
  sonnet:
    provider: anthropic
    model_name: claude-sonnet-5

agents:
  - name: analyst
    framework: langchain-python
    instructions: |
      You are a data analyst. Your workspace (/workspace) is seeded with
      data.csv and analyze.sh. Use the built-in workspace tools:
      list_dir to see files, read_file to inspect them, and
      run ("sh analyze.sh") to compute results. Write findings to
      /workspace/report.md with write_file.
    default_model: sonnet
    platform: local
    secrets:
      - {name: ANTHROPIC_API_KEY}
    workspace:
      name: dev
      image: python:3.12-slim
```

`workspaces/dev/analyze.sh`:

```sh
#!/bin/sh
# Toy analysis the agent can run via the `run` workspace tool.
echo "rows: $(tail -n +2 data.csv | wc -l | tr -d ' ')"
awk -F, 'NR>1 {sum+=$2} END {printf "total: %s\n", sum}' data.csv
```

`workspaces/dev/data.csv`:

```csv
item,amount
widgets,12
gadgets,30
gizmos,7
```

README.md: what it demonstrates (seed folder convention `workspaces/<workspace-name>/`, copy-if-absent on re-apply, the nine built-in tools by name), run steps copied from the sibling example's style (`.env` with `ANTHROPIC_API_KEY`, `vystak init/plan/apply`, chat via `vystak-chat` or the A2A endpoint, destroy notes).

- [ ] **Step 2: Validate the example loads**

Run: `uv run python -c "import yaml; from vystak.schema.multi_loader import load_multi_yaml; agents,_,_ = load_multi_yaml(yaml.safe_load(open('examples/docker-workspace-tools/vystak.yaml'))); print(agents[0].workspace.name)"`
Expected: `dev`

- [ ] **Step 3: Update spec status + full gates**

Spec header: `**Status:** Approved design, pending implementation plan` → `**Status:** Implemented (see plan 2026-07-24-workspace-tools-and-seed.md)`.

Run: `just test-python && just lint-python`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add examples/docker-workspace-tools/ docs/superpowers/specs/2026-07-24-workspace-tools-and-seed-design.md
git commit -m "feat(examples): docker-workspace-tools — seeded workspace driven by built-in tools"
```

---

## Self-review notes

- Spec coverage: runtime modules + wiring (T1-T2), known_hosts fix (T3), seed folders both providers + entrypoint restructure (T4-T5), Azure tools-staging parity + shim host-prefix fix (T5), V11 cell incl. copy-if-absent re-apply check (T6), example (T7). Spec's env-var branch for Azure replaced by the shim-materialization discovery — recorded as a deviation in the header.
- The `chown -R vystak-agent /workspace` in the entrypoint runs on every boot; acceptable for realistic workspace sizes and idempotent. `cp -rn` requires coreutils or busybox ≥1.34 — both true for the supported base images (debian-slim, alpine ≥3.15).
- Tests that reach into private attrs (`c._conn`) are deliberate seams for no-SSH unit testing.
- T3/T5 test steps reference neighboring-test construction patterns rather than inlining them — the exact fixture shapes live in those files and briefs point at the specific functions to mirror; assertions (the contract) are fully specified.
