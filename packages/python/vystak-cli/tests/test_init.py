from pathlib import Path

import yaml
from click.testing import CliRunner
from vystak.schema.agent import Agent
from vystak_cli.commands.init import init


class TestInit:
    def test_creates_yaml(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            result = runner.invoke(init)
            assert result.exit_code == 0
            assert (Path(td) / "vystak.yaml").exists()

    def test_yaml_content_valid(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            runner.invoke(init)
            content = (Path(td) / "vystak.yaml").read_text()
            data = yaml.safe_load(content)
            agent = Agent.model_validate(data)
            assert agent.name == "my-agent"
            assert agent.model.provider.type == "anthropic"

    def test_no_overwrite(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            (Path(td) / "vystak.yaml").write_text("existing")
            result = runner.invoke(init)
            assert result.exit_code != 0 or "already exists" in result.output.lower()
            assert (Path(td) / "vystak.yaml").read_text() == "existing"

    def test_output_message(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(init)
            assert "vystak.yaml" in result.output
