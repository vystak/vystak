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

# The assistant agent coordinates the other two via A2A. Its tool files
# (tools/ask_weather_agent.py, tools/ask_time_agent.py) read peer URLs
# from `WEATHER_AGENT_URL` / `TIME_AGENT_URL` env vars. On Azure these
# must be exported to the shell running `vystak apply` after weather and
# time have been deployed once — e.g.
#
#   export WEATHER_AGENT_URL=https://weather-agent.<env>.azurecontainerapps.io
#   export TIME_AGENT_URL=https://time-agent.<env>.azurecontainerapps.io
#
# On Docker the defaults (`http://vystak-<name>:8000` on vystak-net) work.
assistant_agent = ast.Agent(
    name="assistant-agent",
    instructions=(
        "You are a coordinator. For weather questions use ask_weather_agent; "
        "for time questions use ask_time_agent. Call both tools when the user "
        "asks a combined question (e.g. 'what is the weather and time'). "
        "Synthesize the answers into a concise single reply."
    ),
    model=llm,
    platform=platform,
    skills=[
        ast.Skill(name="coordinator", tools=["ask_weather_agent", "ask_time_agent"]),
    ],
    secrets=[
        ast.Secret(name="ANTHROPIC_API_KEY"),
        ast.Secret(name="WEATHER_AGENT_URL"),
        ast.Secret(name="TIME_AGENT_URL"),
    ],
)

chat = ast.Channel(
    name="chat",
    type=ast.ChannelType.CHAT,
    platform=platform,
    config={"port": 8080},
    routes=[
        ast.RouteRule(match={}, agent="weather-agent"),
        ast.RouteRule(match={}, agent="time-agent"),
        ast.RouteRule(match={}, agent="assistant-agent"),
    ],
)
