"""Hash-tree tests verifying declarative schedules changes propagate to
the agent root hash.

Mirrors test_heartbeat_hash.py's shape — schedules are declarative agent
config (deploy identity), same as heartbeat. Runtime-created tasks never
touch this: they don't exist on the Agent model.
"""

from vystak.hash.tree import hash_agent
from vystak.schema import Agent, Model, Platform, Provider, ScheduledTask


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


def test_no_schedules_present():
    agent = Agent(
        name="bot", framework="langchain-python", default_model=_model(), platform=_platform()
    )
    tree = hash_agent(agent)
    assert tree.schedules == hash_agent(agent).schedules  # deterministic


def test_schedules_affect_hash():
    a1 = Agent(
        name="bot", framework="langchain-python", default_model=_model(), platform=_platform()
    )
    a2 = Agent(
        name="bot",
        framework="langchain-python",
        default_model=_model(),
        platform=_platform(),
        schedules=[ScheduledTask(name="digest", cron="0 9 * * 1")],
    )
    assert hash_agent(a1).root != hash_agent(a2).root
    assert hash_agent(a1).schedules != hash_agent(a2).schedules


def test_schedule_field_change_changes_hash():
    def with_cron(cron: str) -> Agent:
        return Agent(
            name="bot",
            framework="langchain-python",
            default_model=_model(),
            platform=_platform(),
            schedules=[ScheduledTask(name="d", cron=cron)],
        )

    h1 = hash_agent(with_cron("0 9 * * 1"))
    h2 = hash_agent(with_cron("0 10 * * 1"))
    assert h1.root != h2.root
    assert h1.schedules != h2.schedules
