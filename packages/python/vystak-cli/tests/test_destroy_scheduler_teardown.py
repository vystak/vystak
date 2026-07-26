"""Tests for `vystak destroy` scheduler (vystak-heartbeat) teardown.

The scheduler container is auto-spawned by `apply` under a three-way
condition (see `apply.py::_agents_needing_scheduler` + its call site):
an agent declares `heartbeat`, an agent has non-empty `schedules`, or the
platform declares `scheduler.enabled=True` (zero declaring agents). destroy
must tear it down under all three — the old gate only checked `heartbeat`,
orphaning the container (and blocking `docker volume rm
vystak-scheduler-data`) for schedules-only and toggle-only deployments.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from vystak.schema.agent import Agent
from vystak.schema.model import Model
from vystak.schema.platform import Platform, SchedulerConfig
from vystak.schema.provider import Provider
from vystak.schema.schedule import ScheduledTask
from vystak_cli.commands.destroy import _needs_scheduler_teardown
from vystak_cli.commands.destroy import destroy as destroy_cmd

HEARTBEAT_ONLY_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: assistant
    framework: langchain-python
    default_model: sonnet
    platform: local
    secrets: [{name: ANTHROPIC_API_KEY}]
    heartbeat:
      schedule: "*/30 * * * *"
      target_channel: chat-main.channels.default
channels:
  - name: chat-main
    type: chat
    platform: local
    config: {port: 8080}
    agents: [assistant]
    default_agent: assistant
"""

SCHEDULES_ONLY_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: worker
    framework: langchain-python
    default_model: sonnet
    platform: local
    secrets: [{name: ANTHROPIC_API_KEY}]
    schedules:
      - {name: digest, cron: "0 9 * * 1"}
"""

TOGGLE_ONLY_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker, scheduler: {enabled: true}}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: idle
    framework: langchain-python
    default_model: sonnet
    platform: local
    secrets: [{name: ANTHROPIC_API_KEY}]
"""

NONE_YAML = """\
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker}
models:
  sonnet: {provider: anthropic, model_name: claude-sonnet-4-20250514}
agents:
  - name: idle
    framework: langchain-python
    default_model: sonnet
    platform: local
    secrets: [{name: ANTHROPIC_API_KEY}]
"""


def _write_yaml(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "vystak.yaml"
    p.write_text(text)
    return p


def _run_destroy(tmp_path: Path, yaml_text: str) -> tuple[MagicMock, object]:
    """Invoke `vystak destroy` against `yaml_text`, with `get_provider`
    patched to return a MagicMock (so `hasattr(provider, "destroy_heartbeat")`
    is True and the call is recordable — a bare stub class without the
    attribute would make the negative case pass vacuously)."""
    config = _write_yaml(tmp_path, yaml_text)
    provider = MagicMock()
    provider.list_resources.return_value = []
    runner = CliRunner()
    with patch("vystak_cli.commands.destroy.get_provider", return_value=provider):
        result = runner.invoke(destroy_cmd, ["--file", str(config)])
    return provider, result


class TestDestroySchedulerTeardownCLI:
    def test_heartbeat_only_tears_down_scheduler(self, tmp_path):
        provider, result = _run_destroy(tmp_path, HEARTBEAT_ONLY_YAML)
        assert result.exit_code == 0, result.output
        assert provider.destroy_heartbeat.called

    def test_schedules_only_tears_down_scheduler(self, tmp_path):
        provider, result = _run_destroy(tmp_path, SCHEDULES_ONLY_YAML)
        assert result.exit_code == 0, result.output
        assert provider.destroy_heartbeat.called

    def test_toggle_only_tears_down_scheduler(self, tmp_path):
        """Zero agents declare heartbeat/schedules; the platform's
        scheduler.enabled=True toggle alone must still trigger teardown."""
        provider, result = _run_destroy(tmp_path, TOGGLE_ONLY_YAML)
        assert result.exit_code == 0, result.output
        assert provider.destroy_heartbeat.called

    def test_no_scheduler_signal_skips_teardown(self, tmp_path):
        provider, result = _run_destroy(tmp_path, NONE_YAML)
        assert result.exit_code == 0, result.output
        assert not provider.destroy_heartbeat.called


def _model():
    return Model(
        name="sonnet",
        provider=Provider(name="anthropic", type="anthropic"),
        model_name="claude-sonnet-4-6",
    )


def _agent(name, *, heartbeat=None, schedules=(), platform=None):
    return Agent(
        name=name,
        framework="langchain-python",
        default_model=_model(),
        heartbeat=heartbeat,
        schedules=list(schedules),
        platform=platform,
    )


def _docker_platform(*, scheduler_enabled=False):
    return Platform(
        name="local",
        type="docker",
        provider=Provider(name="docker", type="docker"),
        scheduler=SchedulerConfig(enabled=scheduler_enabled),
    )


class TestNeedsSchedulerTeardownHelper:
    def test_heartbeat_only_true(self):
        from vystak.schema.heartbeat import Heartbeat

        agents = [
            _agent(
                "bot",
                heartbeat=Heartbeat(
                    schedule="*/30 * * * *", target_channel="x.channels.dev"
                ),
            )
        ]
        assert _needs_scheduler_teardown(agents, None) is True

    def test_schedules_only_true(self):
        agents = [
            _agent("worker", schedules=[ScheduledTask(name="digest", cron="0 9 * * 1")])
        ]
        assert _needs_scheduler_teardown(agents, None) is True

    def test_toggle_only_true(self):
        platform = _docker_platform(scheduler_enabled=True)
        agents = [_agent("idle", platform=platform)]
        assert _needs_scheduler_teardown(agents, platform) is True

    def test_none_false(self):
        platform = _docker_platform(scheduler_enabled=False)
        agents = [_agent("idle", platform=platform)]
        assert _needs_scheduler_teardown(agents, platform) is False

    def test_empty_agents_and_no_platform_false(self):
        assert _needs_scheduler_teardown([], None) is False
