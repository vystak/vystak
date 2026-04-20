"""Azure + chat channel example — cross-platform plugin reuse.

One `weather-agent` + one `chat` channel, both deployed to Azure Container
Apps. The chat plugin's generated code is identical to the Docker version;
the platform provider wraps it in ACA's native container app.

Prereqs:
- Azure subscription, `az login` completed
- ANTHROPIC_API_KEY exported

Replace YOUR_SUBSCRIPTION_ID with your actual subscription ID.

Run:

    export ANTHROPIC_API_KEY=sk-ant-...
    cd examples/azure-chat
    vystak apply

The chat channel's external FQDN is shown in the summary. Use it with any
OpenAI-compatible client:

    curl -s https://channel-chat.<env-domain>.azurecontainerapps.io/v1/models
"""

import vystak as ast

azure = ast.Provider(
    name="azure",
    type="azure",
    config={
        "subscription_id": "YOUR_SUBSCRIPTION_ID",
        "location": "eastus2",
        "resource_group": "vystak-chat-demo",
    },
)
anthropic = ast.Provider(name="anthropic", type="anthropic")

platform = ast.Platform(
    name="aca",
    type="container-apps",
    provider=azure,
    namespace="prod",
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
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

chat = ast.Channel(
    name="chat",
    type=ast.ChannelType.CHAT,
    platform=platform,
    config={"port": 8080},
    routes=[ast.RouteRule(match={}, agent="weather-agent")],
)
