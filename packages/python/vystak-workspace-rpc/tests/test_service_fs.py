"""Tests for the fs.* service."""

from pathlib import Path

import pytest
from vystak_workspace_rpc.services.fs import register_fs


def _build_server(workspace_root: Path):
    from vystak_workspace_rpc.server import JsonRpcServer

    srv = JsonRpcServer()
    register_fs(srv, workspace_root)
    return srv


@pytest.mark.asyncio
async def test_fs_write_and_read(tmp_path):
    srv = _build_server(tmp_path)
    await srv._handlers["fs.writeFile"]({"path": "a.txt", "content": "hello"})
    result = await srv._handlers["fs.readFile"]({"path": "a.txt"})
    assert result == "hello"


@pytest.mark.asyncio
async def test_fs_exists(tmp_path):
    srv = _build_server(tmp_path)
    (tmp_path / "foo").write_text("x")
    r = await srv._handlers["fs.exists"]({"path": "foo"})
    assert r is True
    r = await srv._handlers["fs.exists"]({"path": "nope"})
    assert r is False


@pytest.mark.asyncio
async def test_fs_list_dir(tmp_path):
    (tmp_path / "a.py").write_text("1")
    (tmp_path / "b.md").write_text("2")
    (tmp_path / "sub").mkdir()
    srv = _build_server(tmp_path)
    entries = await srv._handlers["fs.listDir"]({"path": "."})
    names = {e["name"] for e in entries}
    assert names == {"a.py", "b.md", "sub"}
    sub = next(e for e in entries if e["name"] == "sub")
    assert sub["type"] == "directory"
    a = next(e for e in entries if e["name"] == "a.py")
    assert a["type"] == "file"
    assert a["size"] == 1


@pytest.mark.asyncio
async def test_fs_delete_file(tmp_path):
    (tmp_path / "gone.txt").write_text("bye")
    srv = _build_server(tmp_path)
    await srv._handlers["fs.deleteFile"]({"path": "gone.txt"})
    assert not (tmp_path / "gone.txt").exists()


@pytest.mark.asyncio
async def test_fs_mkdir_with_parents(tmp_path):
    srv = _build_server(tmp_path)
    await srv._handlers["fs.mkdir"]({"path": "a/b/c", "parents": True})
    assert (tmp_path / "a" / "b" / "c").is_dir()


@pytest.mark.asyncio
async def test_fs_move(tmp_path):
    (tmp_path / "src.txt").write_text("x")
    srv = _build_server(tmp_path)
    await srv._handlers["fs.move"]({"src": "src.txt", "dst": "dst.txt"})
    assert not (tmp_path / "src.txt").exists()
    assert (tmp_path / "dst.txt").read_text() == "x"


@pytest.mark.asyncio
async def test_fs_edit_replaces(tmp_path):
    (tmp_path / "f.py").write_text("hello world")
    srv = _build_server(tmp_path)
    result = await srv._handlers["fs.edit"]({
        "path": "f.py", "old_str": "world", "new_str": "vystak"
    })
    assert (tmp_path / "f.py").read_text() == "hello vystak"
    assert "diff" in result


@pytest.mark.asyncio
async def test_fs_edit_old_str_not_found_raises(tmp_path):
    (tmp_path / "f.py").write_text("hello world")
    srv = _build_server(tmp_path)
    with pytest.raises(ValueError, match="old_str not found"):
        await srv._handlers["fs.edit"]({
            "path": "f.py", "old_str": "missing", "new_str": "x"
        })


@pytest.mark.asyncio
async def test_fs_readFile_escape_attempt_raises(tmp_path):
    """Paths outside workspace root are rejected."""
    srv = _build_server(tmp_path)
    with pytest.raises(ValueError, match="outside workspace root"):
        await srv._handlers["fs.readFile"]({"path": "../../../etc/passwd"})
