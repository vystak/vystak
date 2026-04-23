"""Tests for workspace Dockerfile generation."""

from vystak_provider_docker.workspace_image import (
    detect_tool_deps_manager,
    generate_workspace_dockerfile,
)


def test_generates_minimal_dockerfile():
    df = generate_workspace_dockerfile(
        image="python:3.12-slim",
        provision=[],
        copy={},
        tool_deps_manager=None,
    )
    assert df.startswith("FROM python:3.12-slim")
    assert "openssh-server" in df  # vystak appendix
    assert "vystak-workspace-rpc" in df
    assert "ENTRYPOINT" in df


def test_includes_provision_run_layers():
    df = generate_workspace_dockerfile(
        image="python:3.12-slim",
        provision=["apt-get update", "pip install ruff"],
        copy={},
        tool_deps_manager=None,
    )
    assert "RUN apt-get update" in df
    assert "RUN pip install ruff" in df


def test_includes_copy_statements():
    df = generate_workspace_dockerfile(
        image="python:3.12-slim",
        provision=[],
        copy={"./config.toml": "/workspace/config.toml"},
        tool_deps_manager=None,
    )
    assert "COPY ./config.toml /workspace/config.toml" in df


def test_pip_auto_detected_for_python_image():
    assert detect_tool_deps_manager("python:3.12-slim") == "pip"
    assert detect_tool_deps_manager("python:3.11") == "pip"
    assert detect_tool_deps_manager("python:3.12-alpine") == "pip"


def test_npm_auto_detected_for_node_image():
    assert detect_tool_deps_manager("node:20") == "npm"
    assert detect_tool_deps_manager("node:22-alpine") == "npm"


def test_none_when_unknown_base():
    assert detect_tool_deps_manager("ubuntu:24.04") is None
    assert detect_tool_deps_manager("rust:1.80") is None


def test_explicit_tool_deps_manager_overrides_detection():
    df = generate_workspace_dockerfile(
        image="ubuntu:24.04",
        provision=["apt-get install -y python3 python3-pip"],
        copy={},
        tool_deps_manager="pip",
    )
    # pip3 is emitted (Debian/Ubuntu naming); enough to confirm the pip path was taken.
    assert "pip3 install --break-system-packages -r /workspace/tools/requirements.txt" in df


def test_tool_deps_none_skips_install():
    df = generate_workspace_dockerfile(
        image="python:3.12-slim",
        provision=[],
        copy={},
        tool_deps_manager="none",
    )
    # Neither the pip3 tools install nor the npm install line is emitted.
    assert "pip3 install --break-system-packages -r /workspace/tools/requirements.txt" not in df
    assert "npm install" not in df


def test_entrypoint_shim_emitted_by_default():
    """Vault path (default) wires the shim that waits for
    /shared/secrets.env."""
    from vystak_provider_docker.workspace_image import generate_workspace_dockerfile

    df = generate_workspace_dockerfile(
        image="python:3.12-slim",
        provision=[],
        copy={},
        tool_deps_manager=None,
    )
    assert "COPY entrypoint-shim.sh /vystak/entrypoint-shim.sh" in df
    assert 'ENTRYPOINT ["/vystak/entrypoint-shim.sh"]' in df
    assert 'CMD ["/usr/sbin/sshd"' in df


def test_no_entrypoint_shim_on_default_path():
    """Default path: no Vault Agent, no /shared/secrets.env, no shim.
    sshd becomes CMD directly so the container doesn't block on a file
    that will never appear."""
    from vystak_provider_docker.workspace_image import generate_workspace_dockerfile

    df = generate_workspace_dockerfile(
        image="node:20-slim",
        provision=[],
        copy={},
        tool_deps_manager=None,
        use_entrypoint_shim=False,
    )
    assert "entrypoint-shim" not in df
    assert "ENTRYPOINT" not in df
    assert 'CMD ["/usr/sbin/sshd"' in df
