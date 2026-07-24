"""Heartbeat agent — periodic self-invocation via chat channel."""

from vystak.schema import (
    Agent,
    Channel,
    ChannelType,
    Heartbeat,
    Model,
    Platform,
    Provider,
    Secret,
)

anthropic = Provider(name="anthropic", type="anthropic")
docker = Provider(name="docker", type="docker")
local = Platform(name="local", type="docker", provider=docker, namespace="dev")

model = Model(
    name="claude",
    provider=anthropic,
    model_name="claude-sonnet-4-6",
    parameters={"temperature": 0.3},
)

ops_agent = Agent(
    name="ops-bot",
    framework="langchain-python",
    instructions=(
        "You are an ops assistant. On every heartbeat, scan the workspace's "
        "HEARTBEAT.md checklist and surface anything that needs attention. "
        "If nothing is wrong, reply with HEARTBEAT_OK and nothing else."
    ),
    default_model=model,
    platform=local,
    secrets=[Secret(name="ANTHROPIC_API_KEY")],
    heartbeat=Heartbeat(
        schedule="*/30 9-18 * * 1-5",
        timezone="America/New_York",
        target_channel="chat-main.channels.dev",
        target_thread="standup-room",
        isolated_session=True,
        skip_when_busy=True,
        ack_max_chars=300,
    ),
)

chat = Channel(
    name="chat-main",
    type=ChannelType.CHAT,
    platform=local,
    config={"port": 8080},
    agents=[ops_agent],
    default_agent=ops_agent,
)
