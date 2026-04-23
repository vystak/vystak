"""Tests for git.* service. Uses a real temp git repo."""

import subprocess

import pytest
from vystak_workspace_rpc.services.git import register_git


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)


def _build_server(workspace_root):
    from vystak_workspace_rpc.server import JsonRpcServer

    srv = JsonRpcServer()
    register_git(srv, workspace_root)
    return srv


@pytest.mark.asyncio
async def test_git_status_clean(tmp_path):
    _init_repo(tmp_path)
    srv = _build_server(tmp_path)
    result = await srv._handlers["git.status"]({})
    assert "branch" in result
    assert result["dirty"] is False
    assert result["staged"] == []
    assert result["unstaged"] == []
    assert result["untracked"] == []


@pytest.mark.asyncio
async def test_git_status_with_untracked_file(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "new.txt").write_text("hi")
    srv = _build_server(tmp_path)
    result = await srv._handlers["git.status"]({})
    assert result["dirty"] is True
    assert "new.txt" in result["untracked"]


@pytest.mark.asyncio
async def test_git_add_and_commit(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "f.txt").write_text("hello")
    srv = _build_server(tmp_path)
    await srv._handlers["git.add"]({"paths": ["f.txt"]})
    status = await srv._handlers["git.status"]({})
    assert "f.txt" in status["staged"]
    commit = await srv._handlers["git.commit"]({"message": "add f"})
    assert "sha" in commit
    assert len(commit["sha"]) >= 7


@pytest.mark.asyncio
async def test_git_log(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "first"], cwd=tmp_path, check=True)
    srv = _build_server(tmp_path)
    result = await srv._handlers["git.log"]({"limit": 10})
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["message"] == "first"
    assert "sha" in result[0]
    assert "author" in result[0]


@pytest.mark.asyncio
async def test_git_branch(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a").write_text("x")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    srv = _build_server(tmp_path)
    branch = await srv._handlers["git.branch"]({})
    # Default branch is either "main" or "master" depending on git version config
    assert branch in ("main", "master")


@pytest.mark.asyncio
async def test_git_not_a_repo_returns_error(tmp_path):
    # No git init
    srv = _build_server(tmp_path)
    with pytest.raises(RuntimeError, match="not a git repo"):
        await srv._handlers["git.status"]({})
