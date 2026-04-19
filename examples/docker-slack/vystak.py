"""Docker + Slack channel example.

One agent (`weather-agent`) plus one `ChannelType.SLACK` channel that forwards
Slack events to the agent via A2A.

Prereqs:
- Slack app with Socket Mode enabled
- Bot token (`SLACK_BOT_TOKEN`, starts with `xoxb-`)
- App-level token (`SLACK_APP_TOKEN`, starts with `xapp-`)
- Replace the placeholder channel IDs below with your real Slack channel IDs (Cxxxx)

Run:

    export ANTHROPIC_API_KEY=sk-ant-...
    export SLACK_BOT_TOKEN=xoxb-...
    export SLACK_APP_TOKEN=xapp-...

    cd examples/docker-slack
    vystak apply

Mention the bot in your Slack workspace:

    @weather-agent hi
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

slack = ast.Channel(
    name="slack-main",
    type=ast.ChannelType.SLACK,
    platform=platform,
    secrets=[
        ast.Secret(name="SLACK_BOT_TOKEN"),
        ast.Secret(name="SLACK_APP_TOKEN"),
    ],
    routes=[
        # Replace "C0000000000" with your real Slack channel ID
        ast.RouteRule(
            match={"slack_channel": "C0000000000"},
            agent="weather-agent",
        ),
        # Catch DMs to the bot
        ast.RouteRule(
            match={"dm": True},
            agent="weather-agent",
        ),
    ],
)
