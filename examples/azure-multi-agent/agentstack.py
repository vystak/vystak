"""Multi-agent Azure deployment — Python code-first."""

import agentstack as ast

# Shared infrastructure — declared once, referenced by all agents
azure = ast.Provider(name="azure", type="azure", config={
    "location": "eastus2",
    "resource_group": "agentstack-multi-rg",
})
anthropic = ast.Provider(name="anthropic", type="anthropic")
model = ast.Model(
    name="minimax", provider=anthropic, model_name="MiniMax-M2.7",
    parameters={"temperature": 0.7, "anthropic_api_url": "https://api.minimax.io/anthropic"},
)
platform = ast.Platform(name="aca", type="container-apps", provider=azure)

weather = ast.Agent(
    name="weather-agent",
    instructions="You are a weather specialist. Use get_weather for real data.",
    model=model,
    platform=platform,
    skills=[ast.Skill(name="weather", tools=["get_weather"])],
    channels=[ast.Channel(name="api", type=ast.ChannelType.API)],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

time_agent = ast.Agent(
    name="time-agent",
    instructions="You are a time specialist. Use get_time for current time.",
    model=model,
    platform=platform,
    skills=[ast.Skill(name="time", tools=["get_time"])],
    channels=[ast.Channel(name="api", type=ast.ChannelType.API)],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

assistant = ast.Agent(
    name="assistant-agent",
    instructions="You are a helpful assistant. Use ask_weather_agent and ask_time_agent.",
    model=model,
    platform=platform,
    skills=[ast.Skill(name="assistant", tools=["ask_weather_agent", "ask_time_agent"])],
    channels=[ast.Channel(name="api", type=ast.ChannelType.API)],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)
