"""Schema-level tests for the Heartbeat model."""

import pytest
from pydantic import ValidationError
from vystak.schema import Agent, Heartbeat, Model, Provider


def test_minimal_heartbeat_round_trips():
    hb = Heartbeat(
        schedule="*/30 * * * *",
        target_channel="slack-main.channels.dev",
    )
    assert hb.schedule == "*/30 * * * *"
    assert hb.timezone == "UTC"
    assert hb.target_channel == "slack-main.channels.dev"
    assert hb.target_thread is None
    assert hb.prompt is None
    assert hb.isolated_session is True
    assert hb.skip_when_busy is True
    assert hb.ack_max_chars == 300
    assert hb.enabled is True


def test_full_heartbeat_round_trips():
    hb = Heartbeat(
        schedule="0 9 * * 1-5",
        timezone="America/New_York",
        target_channel="slack-main.channels.dev",
        target_thread="C0123456789",
        prompt="Custom prompt",
        isolated_session=False,
        skip_when_busy=False,
        ack_max_chars=500,
        enabled=False,
    )
    dumped = hb.model_dump()
    restored = Heartbeat.model_validate(dumped)
    assert restored == hb


def test_invalid_cron_rejected():
    with pytest.raises(ValidationError) as exc:
        Heartbeat(
            schedule="every 30 minutes",
            target_channel="x.channels.dev",
        )
    # "every 30 minutes" has 3 words so the 5-field check fires first;
    # either message confirms the schedule was rejected.
    assert "cron expression" in str(exc.value)


def test_target_channel_required():
    with pytest.raises(ValidationError):
        Heartbeat(schedule="*/30 * * * *")  # type: ignore[call-arg]


def test_complex_cron_accepted():
    """5-field cron with day-of-week ranges should validate."""
    hb = Heartbeat(
        schedule="*/15 9-22 * * 1-5",
        target_channel="x.channels.dev",
    )
    assert hb.schedule == "*/15 9-22 * * 1-5"


def test_six_field_cron_rejected():
    """6-field (second-precision) cron should be rejected — runtime is 5-field only."""
    with pytest.raises(ValidationError) as exc:
        Heartbeat(
            schedule="*/10 * * * * *",
            target_channel="x.channels.dev",
        )
    assert "5 fields" in str(exc.value)


def test_ack_max_chars_must_be_positive():
    with pytest.raises(ValidationError):
        Heartbeat(
            schedule="*/30 * * * *",
            target_channel="x.channels.dev",
            ack_max_chars=0,
        )


def test_invalid_timezone_rejected():
    with pytest.raises(ValidationError) as exc:
        Heartbeat(
            schedule="*/30 * * * *",
            target_channel="x.channels.dev",
            timezone="Americka/New_York",   # typo
        )
    assert "unknown IANA timezone" in str(exc.value)


def _model() -> Model:
    return Model(
        name="claude",
        provider=Provider(name="anthropic", type="anthropic"),
        model_name="claude-sonnet-4-6",
    )


def test_agent_without_heartbeat_default_none():
    agent = Agent(name="bot", framework="langchain-python", default_model=_model())
    assert agent.heartbeat is None


def test_agent_with_heartbeat_round_trips():
    agent = Agent(
        name="bot",
        framework="langchain-python",
        default_model=_model(),
        heartbeat=Heartbeat(
            schedule="*/5 * * * *",
            target_channel="x.channels.dev",
        ),
    )
    dumped = agent.model_dump()
    restored = Agent.model_validate(dumped)
    assert restored.heartbeat is not None
    assert restored.heartbeat.schedule == "*/5 * * * *"


def test_heartbeat_exported_from_schema():
    """Importable from the top-level schema package."""
    from vystak.schema import Heartbeat as Exported

    assert Exported is Heartbeat


def _write(tmp_path, content: str):
    """Helper: write content to tmp_path/vystak.yaml and return Path."""
    path = tmp_path / "vystak.yaml"
    path.write_text(content)
    return path


def test_target_channel_typo_rejected(tmp_path):
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml

    yaml_text = """
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker, namespace: dev}
models:
  c: {provider: anthropic, model_name: claude-sonnet-4-6}
agents:
  - name: ops-bot
    framework: langchain-python
    default_model: c
    platform: local
    heartbeat:
      schedule: "*/30 * * * *"
      target_channel: nonexistent.channels.dev
channels:
  - name: slack-main
    type: slack
    platform: local
    agents: [ops-bot]
"""
    data = yaml.safe_load(yaml_text)
    with pytest.raises(ValueError, match="target_channel"):
        load_multi_yaml(data)


def test_target_channel_does_not_route_agent_rejected(tmp_path):
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml

    yaml_text = """
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker, namespace: dev}
models:
  c: {provider: anthropic, model_name: claude-sonnet-4-6}
agents:
  - name: ops-bot
    framework: langchain-python
    default_model: c
    platform: local
    heartbeat:
      schedule: "*/30 * * * *"
      target_channel: discord-main.channels.dev
channels:
  - name: slack-main
    type: slack
    platform: local
    agents: [ops-bot]
  - name: discord-main
    type: discord
    platform: local
    agents: []
"""
    data = yaml.safe_load(yaml_text)
    with pytest.raises(ValueError, match="does not route"):
        load_multi_yaml(data)


def test_valid_heartbeat_target_passes(tmp_path):
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml

    yaml_text = """
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker, namespace: dev}
models:
  c: {provider: anthropic, model_name: claude-sonnet-4-6}
agents:
  - name: ops-bot
    framework: langchain-python
    default_model: c
    platform: local
    heartbeat:
      schedule: "*/30 * * * *"
      target_channel: slack-main.channels.dev
channels:
  - name: slack-main
    type: slack
    platform: local
    agents: [ops-bot]
"""
    data = yaml.safe_load(yaml_text)
    agents, channels, _vault = load_multi_yaml(data)
    agent = next(a for a in agents if a.name == "ops-bot")
    assert agent.heartbeat is not None
    assert agent.heartbeat.target_channel == "slack-main.channels.dev"


def test_heartbeat_model_default_none():
    hb = Heartbeat(schedule="*/30 * * * *", target_channel="x.channels.dev")
    assert hb.model is None


def test_heartbeat_model_round_trips():
    hb = Heartbeat(
        schedule="*/30 * * * *",
        target_channel="x.channels.dev",
        model="haiku",
    )
    restored = Heartbeat.model_validate(hb.model_dump())
    assert restored.model == "haiku"


def test_heartbeat_model_in_pool_passes(tmp_path):
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml
    text = """
providers: {anthropic: {type: anthropic}, docker: {type: docker}}
platforms: {local: {type: docker, provider: docker, namespace: dev}}
models:
  opus:   {provider: anthropic, model_name: claude-opus-4-7}
  haiku:  {provider: anthropic, model_name: claude-haiku-4-5-20251001}
agents:
  - name: bot
    framework: langchain-python
    default_model: opus
    models: [haiku]
    platform: local
    heartbeat:
      schedule: "*/30 * * * *"
      target_channel: chat-main.channels.dev
      model: haiku
channels:
  - {name: chat-main, type: chat, platform: local, agents: [bot]}
"""
    load_multi_yaml(yaml.safe_load(text))   # must not raise


def test_heartbeat_model_not_in_pool_rejected():
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml
    text = """
providers: {anthropic: {type: anthropic}, docker: {type: docker}}
platforms: {local: {type: docker, provider: docker, namespace: dev}}
models:
  opus:  {provider: anthropic, model_name: claude-opus-4-7}
agents:
  - name: bot
    framework: langchain-python
    default_model: opus
    platform: local
    heartbeat:
      schedule: "*/30 * * * *"
      target_channel: chat-main.channels.dev
      model: ghost
channels:
  - {name: chat-main, type: chat, platform: local, agents: [bot]}
"""
    with pytest.raises(ValueError, match="not in agent's model pool"):
        load_multi_yaml(yaml.safe_load(text))


def test_schedule_target_channel_typo_rejected():
    """schedules[<name>].target_channel naming an undeclared channel is rejected."""
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml

    yaml_text = """
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker, namespace: dev}
models:
  c: {provider: anthropic, model_name: claude-sonnet-4-6}
agents:
  - name: ops-bot
    framework: langchain-python
    default_model: c
    platform: local
    schedules:
      - name: digest
        cron: "*/30 * * * *"
        target_channel: nonexistent.channels.dev
channels:
  - name: slack-main
    type: slack
    platform: local
    agents: [ops-bot]
"""
    data = yaml.safe_load(yaml_text)
    with pytest.raises(ValueError, match=r"schedules\[digest\].target_channel"):
        load_multi_yaml(data)


def test_schedule_target_channel_does_not_route_agent_rejected():
    """schedules[<name>].target_channel naming a channel that exists but
    does not route this agent is rejected."""
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml

    yaml_text = """
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker, namespace: dev}
models:
  c: {provider: anthropic, model_name: claude-sonnet-4-6}
agents:
  - name: ops-bot
    framework: langchain-python
    default_model: c
    platform: local
    schedules:
      - name: digest
        cron: "*/30 * * * *"
        target_channel: discord-main.channels.dev
channels:
  - name: slack-main
    type: slack
    platform: local
    agents: [ops-bot]
  - name: discord-main
    type: discord
    platform: local
    agents: []
"""
    data = yaml.safe_load(yaml_text)
    with pytest.raises(ValueError, match="does not route"):
        load_multi_yaml(data)


def test_schedule_target_channel_null_ok():
    """schedules[<name>].target_channel=null (log-only delivery) loads fine."""
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml

    yaml_text = """
providers:
  docker: {type: docker}
  anthropic: {type: anthropic}
platforms:
  local: {type: docker, provider: docker, namespace: dev}
models:
  c: {provider: anthropic, model_name: claude-sonnet-4-6}
agents:
  - name: ops-bot
    framework: langchain-python
    default_model: c
    platform: local
    schedules:
      - name: digest
        cron: "*/30 * * * *"
        target_channel: null
"""
    data = yaml.safe_load(yaml_text)
    agents, _channels, _vault = load_multi_yaml(data)
    agent = next(a for a in agents if a.name == "ops-bot")
    assert agent.schedules[0].target_channel is None


def test_schedule_model_not_in_pool_rejected():
    """schedules[<name>].model naming a model outside the agent's pool is rejected."""
    import yaml
    from vystak.schema.multi_loader import load_multi_yaml

    text = """
providers: {anthropic: {type: anthropic}, docker: {type: docker}}
platforms: {local: {type: docker, provider: docker, namespace: dev}}
models:
  opus:  {provider: anthropic, model_name: claude-opus-4-7}
agents:
  - name: bot
    framework: langchain-python
    default_model: opus
    platform: local
    schedules:
      - name: digest
        cron: "*/30 * * * *"
        target_channel: chat-main.channels.dev
        model: ghost
channels:
  - {name: chat-main, type: chat, platform: local, agents: [bot]}
"""
    with pytest.raises(ValueError, match=r"schedules\[digest\].model"):
        load_multi_yaml(yaml.safe_load(text))
