"""Azure multi-agent + chat channel example.

Same shape as examples/docker-multi-chat, but deploys to Azure Container
Apps instead of Docker. Proves the channel plugin contract is
platform-agnostic: same `vystak-channel-chat` plugin, different native
container wrapper (AzureChannelAppNode vs DockerChannelNode).

Reads from env (with MiniMax Anthropic-compat defaults):

    ANTHROPIC_API_KEY       -  model credential (required at runtime)
    ANTHROPIC_API_URL       -  Anthropic-compatible endpoint
    ANTHROPIC_MODEL_NAME    -  model identifier for that endpoint
    AZURE_SUBSCRIPTION_ID   -  your Azure subscription ID
"""

import os

import vystak as ast

MODEL_NAME = os.environ.get("ANTHROPIC_MODEL_NAME", "MiniMax-M2.7")
API_URL = os.environ.get("ANTHROPIC_API_URL", "https://api.minimax.io/anthropic")
SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID", "YOUR_SUBSCRIPTION_ID")

azure = ast.Provider(
    name="azure",
    type="azure",
    config={
        "subscription_id": SUBSCRIPTION_ID,
        "location": "eastus2",
        "resource_group": "vystak-multi-chat-rg",
    },
)
anthropic = ast.Provider(name="anthropic", type="anthropic")

platform = ast.Platform(
    name="aca",
    type="container-apps",
    provider=azure,
    namespace="prod",
)

llm = ast.Model(
    name="llm",
    provider=anthropic,
    model_name=MODEL_NAME,
    api_keys=ast.Secret(name="ANTHROPIC_API_KEY"),
    parameters={
        "temperature": 0.3,
        "anthropic_api_url": API_URL,
    },
)

weather_agent = ast.Agent(
    name="weather-agent",
    instructions=(
        "You are a weather specialist. Use get_weather for real data. "
        "Answer concisely with current conditions only."
    ),
    model=llm,
    platform=platform,
    skills=[ast.Skill(name="weather", tools=["get_weather"])],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

time_agent = ast.Agent(
    name="time-agent",
    instructions=(
        "You are a time specialist. Use get_time to report the current "
        "UTC time. Keep replies one sentence."
    ),
    model=llm,
    platform=platform,
    skills=[ast.Skill(name="time", tools=["get_time"])],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

chat = ast.Channel(
    name="chat",
    type=ast.ChannelType.CHAT,
    platform=platform,
    config={"port": 8080},
    routes=[
        ast.RouteRule(match={}, agent="weather-agent"),
        ast.RouteRule(match={}, agent="time-agent"),
    ],
)
