"""Docker multi-agent + chat channel example (NATS transport).

Mirror of examples/docker-multi-chat, but with Transport(type="nats") declared
on the platform. Same two agents (weather, time) + same chat channel — A2A
traffic flows over NATS JetStream queue-group subscriptions instead of HTTP.
Point any OpenAI-compatible client at http://localhost:18080 and switch agents
via the `model` field:

    model="vystak/weather-agent"  -> routed to the weather agent (over NATS)
    model="vystak/time-agent"     -> routed to the time agent (over NATS)

Reads from env (with defaults that target the MiniMax Anthropic-compat
endpoint):

    ANTHROPIC_API_KEY       -  model credential (required at runtime)
    ANTHROPIC_API_URL       -  Anthropic-compatible endpoint
    ANTHROPIC_MODEL_NAME    -  model identifier for that endpoint
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
    namespace="multi-nats",
    transport=ast.Transport(
        name="bus",
        type="nats",
        config=ast.NatsConfig(jetstream=True, subject_prefix="vystak-nats"),
    ),
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
    instructions=(
        "You are a weather specialist. Use get_weather for real data. "
        "Answer concisely with current conditions only."
    ),
    model=sonnet,
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
    model=sonnet,
    platform=platform,
    skills=[ast.Skill(name="time", tools=["get_time"])],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

# Coordinator agent. Calls time-agent and weather-agent via A2A (over NATS).
# Its tools use vystak.transport.ask_agent() — a 3-line replacement for the
# ~50 lines of httpx + JSON-RPC boilerplate the pre-transport examples used.
assistant_agent = ast.Agent(
    name="assistant-agent",
    instructions=(
        "You are a coordinator. For weather questions call ask_weather_agent; "
        "for time questions call ask_time_agent. When the user asks about "
        "both (e.g. 'what is the weather and time'), call both tools and "
        "synthesise a single concise reply."
    ),
    model=sonnet,
    platform=platform,
    skills=[
        ast.Skill(
            name="coordinator",
            tools=["ask_time_agent", "ask_weather_agent"],
        ),
    ],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

chat = ast.Channel(
    name="chat",
    type=ast.ChannelType.CHAT,
    platform=platform,
    config={"port": 18080},
    routes=[
        ast.RouteRule(match={}, agent="weather-agent"),
        ast.RouteRule(match={}, agent="time-agent"),
        ast.RouteRule(match={}, agent="assistant-agent"),
    ],
)
