"""Smoke test for __main__ wiring all services."""

from vystak_workspace_rpc.__main__ import build_server


def test_build_server_registers_all_services(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    srv = build_server(workspace_root=tmp_path, tools_dir=tools_dir)
    registered = set(srv._handlers.keys())
    # fs.*
    assert "fs.readFile" in registered
    assert "fs.writeFile" in registered
    # exec.*
    assert "exec.run" in registered
    assert "exec.shell" in registered
    # git.*
    assert "git.status" in registered
    # tool.*
    assert "tool.invoke" in registered
    assert "tool.list" in registered
