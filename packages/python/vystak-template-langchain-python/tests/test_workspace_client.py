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
    prog_msg = {
        "jsonrpc": "2.0",
        "method": "$/progress",
        "params": {"channel": "stdout", "chunk": "hi"},
    }
    result_msg = {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {"exit_code": 0},
    }
    c._conn = FakeConn([
        json.dumps(prog_msg) + "\n",
        json.dumps(result_msg) + "\n",
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
        if c._conn is None:
            c._conn = fresh

    monkeypatch.setattr(c, "connect", fake_connect)
    assert await c.invoke("fs.listDir", path=".") == []
    assert len(fresh.processes) == 1
    assert c._conn is fresh


@pytest.mark.asyncio
async def test_connect_passes_expected_kwargs(monkeypatch):
    import _vystak.runtime.workspace_client as wc_mod

    captured = {}

    async def fake_asyncssh_connect(host, **kwargs):
        captured["host"] = host
        captured.update(kwargs)
        return FakeConn([])

    monkeypatch.setattr(wc_mod.asyncssh, "connect", fake_asyncssh_connect)
    c = _client()
    await c.connect()
    assert captured["host"] == "ws"
    assert captured["username"] == "vystak-agent"
    assert captured["client_keys"] == ["/vystak/ssh/id_ed25519"]
    assert captured["known_hosts"] == "/vystak/ssh/known_hosts"
    assert captured["keepalive_interval"] == 30
