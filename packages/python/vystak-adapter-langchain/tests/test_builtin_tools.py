"""Tests that generate_builtin_tools produces wrapped @tool functions
that delegate to WorkspaceRpcClient."""

from vystak_adapter_langchain.builtin_tools import generate_builtin_tools


def test_generates_fs_read_file_tool():
    files = generate_builtin_tools(
        skill_tool_names=["fs.readFile", "exec.run", "git.status"],
    )
    content = files["builtin_tools.py"]
    # Each built-in method generates a wrapper
    assert "async def read_file" in content
    assert "async def run" in content
    assert "async def git_status" in content
    # Wrappers call the workspace client (through _require_client() alias)
    assert "c.invoke(" in content or "c.invoke_stream(" in content
    assert "workspace_client" in content
    # @tool decorator applied
    assert "@tool" in content


def test_skips_unrecognized_prefixes():
    files = generate_builtin_tools(
        skill_tool_names=["fs.readFile", "nope.something", "custom_tool"],
    )
    # Only fs.* built-in is rendered; nope.* is neither built-in nor user
    content = files["builtin_tools.py"]
    assert "async def read_file" in content
    assert "nope" not in content


def test_exec_run_is_streaming():
    files = generate_builtin_tools(skill_tool_names=["exec.run", "fs.readFile"])
    content = files["builtin_tools.py"]
    # exec.* uses invoke_stream
    assert "async def run" in content
    # The generated body for run() accumulates streamed chunks
    assert "invoke_stream" in content
