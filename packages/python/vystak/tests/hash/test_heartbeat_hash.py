"""Hash-tree tests verifying heartbeat changes propagate to agent root."""

from vystak.hash.tree import hash_agent
from vystak.schema import Agent, Channel, ChannelType, Heartbeat, Model, Platform, Provider


def _model() -> Model:
    return Model(
        name="claude",
        provider=Provider(name="anthropic", type="anthropic"),
        model_name="claude-sonnet-4-6",
    )


def _platform() -> Platform:
    return Platform(
        name="local",
        type="docker",
        provider=Provider(name="docker", type="docker"),
        namespace="dev",
    )


def test_no_heartbeat_field_present():
    agent = Agent(
        name="bot", framework="langchain-python", default_model=_model(), platform=_platform()
    )
    tree = hash_agent(agent)
    assert tree.heartbeat == hash_agent(agent).heartbeat  # deterministic


def test_adding_heartbeat_changes_root():
    agent_no = Agent(
        name="bot", framework="langchain-python", default_model=_model(), platform=_platform()
    )
    agent_yes = Agent(
        name="bot",
        framework="langchain-python",
        default_model=_model(),
        platform=_platform(),
        heartbeat=Heartbeat(
            schedule="*/30 * * * *",
            target_channel="x.channels.dev",
        ),
    )
    assert hash_agent(agent_no).root != hash_agent(agent_yes).root
    assert hash_agent(agent_no).heartbeat != hash_agent(agent_yes).heartbeat


def test_changing_schedule_changes_root():
    def with_schedule(s: str) -> Agent:
        return Agent(
            name="bot",
            framework="langchain-python",
            default_model=_model(),
            platform=_platform(),
            heartbeat=Heartbeat(schedule=s, target_channel="x.channels.dev"),
        )

    h1 = hash_agent(with_schedule("*/30 * * * *"))
    h2 = hash_agent(with_schedule("*/15 * * * *"))
    assert h1.root != h2.root
    assert h1.heartbeat != h2.heartbeat


def test_toggling_enabled_changes_root():
    def with_enabled(e: bool) -> Agent:
        return Agent(
            name="bot",
            framework="langchain-python",
            default_model=_model(),
            platform=_platform(),
            heartbeat=Heartbeat(
                schedule="*/30 * * * *",
                target_channel="x.channels.dev",
                enabled=e,
            ),
        )

    assert hash_agent(with_enabled(True)).root != hash_agent(with_enabled(False)).root


def test_channel_hash_picks_up_routed_agent_heartbeat_change():
    """When a routed agent's heartbeat changes, the channel's hash changes."""
    from vystak.hash.tree import hash_channel

    def channel_with_schedule(s: str) -> Channel:
        agent = Agent(
            name="bot",
            framework="langchain-python",
            default_model=_model(),
            platform=_platform(),
            heartbeat=Heartbeat(schedule=s, target_channel="x.channels.dev"),
        )
        return Channel(
            name="x",
            type=ChannelType.CHAT,
            platform=_platform(),
            agents=[agent],
        )

    h1 = hash_channel(channel_with_schedule("*/30 * * * *"))
    h2 = hash_channel(channel_with_schedule("*/15 * * * *"))
    assert h1.root != h2.root
