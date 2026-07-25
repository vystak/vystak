"""Docker multi-agent + control panel example.

Two agents (weather, time) + the `panel` channel: the control-panel API
container (users, projects, conversations, SSE streaming chat). The panel
API listens on http://localhost:18100; the Next.js UI (`vystak-panel`,
run separately — see README) connects to it.

Reads from env (with defaults that target the MiniMax Anthropic-compat
endpoint):

    ANTHROPIC_API_KEY       -  model credential (required at runtime)
    ANTHROPIC_API_URL       -  Anthropic-compatible endpoint
    ANTHROPIC_MODEL_NAME    -  model identifier for that endpoint
    PANEL_SERVICE_TOKEN     -  shared secret between the panel channel and
                                the Next.js UI backend (required at runtime)
"""

import os

import vystak as ast

MODEL_NAME = os.environ.get("ANTHROPIC_MODEL_NAME", "MiniMax-M2.7")
API_URL = os.environ.get("ANTHROPIC_API_URL", "https://api.minimax.io/anthropic")

docker = ast.Provider(name="docker", type="docker")
anthropic = ast.Provider(name="anthropic", type="anthropic")

platform = ast.Platform(
    name="local",
    type="docker",
    provider=docker,
    namespace="multi",
)

sonnet = ast.Model(
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
    framework="langchain-python",
    instructions=(
        "You are a weather specialist. Use get_weather for real data. "
        "Answer concisely with current conditions only."
    ),
    default_model=sonnet,
    platform=platform,
    skills=[ast.Skill(name="weather", tools=["get_weather"])],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

time_agent = ast.Agent(
    name="time-agent",
    framework="langchain-python",
    instructions=(
        "You are a time specialist. Use get_time to report the current "
        "UTC time. Keep replies one sentence."
    ),
    default_model=sonnet,
    platform=platform,
    skills=[ast.Skill(name="time", tools=["get_time"])],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

panel = ast.Channel(
    name="panel",
    type=ast.ChannelType.PANEL,
    platform=platform,
    config={"port": 18100},
    agents=[weather_agent, time_agent],
    secrets=[ast.Secret(name="PANEL_SERVICE_TOKEN")],
)
