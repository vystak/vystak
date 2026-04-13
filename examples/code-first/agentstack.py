# examples/code-first/agentstack.py
"""Code-first agent definition — Python instead of YAML."""

from agentstack.schema import (
    Agent,
    Channel,
    ChannelType,
    Model,
    Platform,
    Postgres,
    Provider,
    Secret,
    Skill,
)

anthropic = Provider(name="anthropic", type="anthropic")
docker = Provider(name="docker", type="docker")

model = Model(
    name="minimax",
    provider=anthropic,
    model_name="MiniMax-M2.7",
    parameters={
        "temperature": 0.7,
        "anthropic_api_url": "https://api.minimax.io/anthropic",
    },
)

agent = Agent(
    name="code-first-agent",
    instructions=(
        "You are a personal assistant defined in Python code.\n"
        "Remember important facts the user tells you.\n"
        "Use save_memory and forget_memory tools as needed."
    ),
    model=model,
    platform=Platform(name="docker", type="docker", provider=docker),
    sessions=Postgres(provider=docker),
    memory=Postgres(provider=docker),
    skills=[Skill(name="assistant", tools=[])],
    channels=[Channel(name="api", type=ChannelType.API)],
    secrets=[Secret(name="ANTHROPIC_API_KEY")],
    port=8094,
)
