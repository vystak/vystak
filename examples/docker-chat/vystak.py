"""Docker + chat channel smoke example.

One agent (`weather-agent`) plus one `ChannelType.CHAT` channel (`chat`) that
routes to it. After `vystak apply` you can curl the chat endpoint with any
OpenAI-compatible client:

    curl -X POST http://localhost:8080/v1/chat/completions \\
        -H 'Content-Type: application/json' \\
        -d '{"model":"vystak/weather-agent","messages":[{"role":"user","content":"hi"}]}'
"""

import vystak as ast

docker = ast.Provider(name="docker", type="docker")
anthropic = ast.Provider(name="anthropic", type="anthropic")

platform = ast.Platform(
    name="local",
    type="docker",
    provider=docker,
    namespace="dev",
)

sonnet = ast.Model(
    name="sonnet",
    provider=anthropic,
    model_name="claude-sonnet-4-20250514",
    api_keys=ast.Secret(name="ANTHROPIC_API_KEY"),
)

weather_agent = ast.Agent(
    name="weather-agent",
    instructions="You are a weather specialist. Answer concisely.",
    model=sonnet,
    platform=platform,
    skills=[ast.Skill(name="weather", tools=[])],
)

chat = ast.Channel(
    name="chat",
    type=ast.ChannelType.CHAT,
    platform=platform,
    config={"port": 8080},
    routes=[
        ast.RouteRule(match={}, agent="weather-agent"),
    ],
)
