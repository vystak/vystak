"""The packaged setup.py shim providers copy into workspace build contexts."""

from vystak_workspace_rpc.build_files import setup_py_path


def test_setup_py_ships_with_package():
    path = setup_py_path()
    assert path.exists()
    content = path.read_text()
    assert "vystak-workspace-rpc" in content
    assert "find_packages" in content
