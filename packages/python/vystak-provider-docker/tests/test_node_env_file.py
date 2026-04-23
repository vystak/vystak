"""Unit tests for DockerEnvFileNode."""



from vystak_provider_docker.nodes.env_file import DockerEnvFileNode


def test_writes_env_file_with_declared_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    node = DockerEnvFileNode(
        principal_name="assistant-agent",
        declared_secret_names=["ANTHROPIC_API_KEY"],
        env_values={"ANTHROPIC_API_KEY": "sk-test", "OTHER": "ignored"},
    )
    result = node.provision(context={})
    assert result.success
    env_file = tmp_path / ".vystak" / "env" / "assistant-agent.env"
    assert env_file.exists()
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert env_file.read_text() == "ANTHROPIC_API_KEY=sk-test\n"
    assert result.info["env"] == {"ANTHROPIC_API_KEY": "sk-test"}
    assert result.info["env_file_path"] == ".vystak/env/assistant-agent.env"


def test_declared_but_missing_from_env_aborts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    node = DockerEnvFileNode(
        principal_name="assistant-agent",
        declared_secret_names=["ANTHROPIC_API_KEY", "MISSING_KEY"],
        env_values={"ANTHROPIC_API_KEY": "sk-test"},
    )
    result = node.provision(context={})
    assert not result.success
    assert "MISSING_KEY" in (result.error or "")


def test_allow_missing_does_not_abort(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    node = DockerEnvFileNode(
        principal_name="assistant-agent",
        declared_secret_names=["ANTHROPIC_API_KEY", "MISSING_KEY"],
        env_values={"ANTHROPIC_API_KEY": "sk-test"},
        allow_missing=True,
    )
    result = node.provision(context={})
    assert result.success
    assert result.info["missing"] == ["MISSING_KEY"]
    assert result.info["env"] == {"ANTHROPIC_API_KEY": "sk-test"}


def test_empty_declared_is_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    node = DockerEnvFileNode(
        principal_name="assistant-agent",
        declared_secret_names=[],
        env_values={"WHATEVER": "x"},
    )
    result = node.provision(context={})
    assert result.success
    assert result.info["env"] == {}
    env_file = tmp_path / ".vystak" / "env" / "assistant-agent.env"
    assert not env_file.exists()


def test_node_name():
    node = DockerEnvFileNode(
        principal_name="assistant-agent",
        declared_secret_names=[],
        env_values={},
    )
    assert node.name == "env-file:assistant-agent"
