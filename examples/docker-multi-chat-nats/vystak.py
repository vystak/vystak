"""Docker multi-agent + chat channel example (NATS transport).

Mirror of examples/docker-multi-chat, but with Transport(type="nats") declared
on the platform. Same three agents (weather, time, coordinator) + same chat
channel — A2A traffic flows over NATS JetStream queue-group subscriptions
instead of HTTP. Point any OpenAI-compatible client at http://localhost:18080
and switch agents via the `model` field:

    model="vystak/weather-agent"   -> routed to the weather agent (over NATS)
    model="vystak/time-agent"      -> routed to the time agent (over NATS)
    model="vystak/assistant-agent" -> routed to the coordinator (over NATS)

The coordinator declares `subagents=[weather_agent, time_agent]` so its
generated server gets `ask_weather_agent` and `ask_time_agent` tools that
delegate via Vystak's transport — no manual ask_*_agent.py files needed.

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

# Coordinator declares its peers via subagents — the langchain adapter
# auto-generates ask_weather_agent and ask_time_agent tools.
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
    subagents=[weather_agent, time_agent],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

chat = ast.Channel(
    name="chat",
    type=ast.ChannelType.CHAT,
    platform=platform,
    config={"port": 18080},
    agents=[weather_agent, time_agent, assistant_agent],
)
