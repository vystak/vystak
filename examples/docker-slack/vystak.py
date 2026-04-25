"""Docker + Slack channel example — self-serve routing.

One agent (`weather-agent`) plus one `ChannelType.SLACK` channel. With a
single agent declared, the channel auto-binds on bot invite — no slash
commands needed for the trivial case. With multiple agents, users pick
one per channel via `/vystak route <agent>`.

Prereqs:
- Slack app with Socket Mode enabled
- Bot token (`SLACK_BOT_TOKEN`, starts with `xoxb-`)
- App-level token (`SLACK_APP_TOKEN`, starts with `xapp-`)
- The bot's Slack app needs:
    * `app_mentions:read`, `chat:write`, `commands` scopes
    * a `/vystak` slash command pointing at the bot
    * Event subscriptions: `app_mention`, `member_joined_channel`, `message.channels`, `message.im`

Run:

    cp .env.example .env  # then edit
    cd examples/docker-slack
    vystak apply

Then in Slack, invite the bot to a channel — it'll post a welcome message
and (since this example has only one agent) auto-bind the channel.

    @weather-bot hi
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
    # Secrets must be declared on the agent for the Docker provider to
    # wire them into the container env. Add ANTHROPIC_API_URL here if
    # you're routing to a non-default Anthropic-compatible endpoint.
    secrets=[
        ast.Secret(name="ANTHROPIC_API_KEY"),
    ],
)

slack = ast.Channel(
    name="slack-main",
    type=ast.ChannelType.SLACK,
    platform=platform,
    secrets=[
        ast.Secret(name="SLACK_BOT_TOKEN"),
        ast.Secret(name="SLACK_APP_TOKEN"),
    ],
    # Routable agents. With one entry, the channel auto-binds on invite.
    # With multiple, users run `/vystak route <agent>` per channel.
    agents=[weather_agent],
    # Optional: pin specific Slack channel IDs at deploy time. Useful when
    # config-as-code matters (audit, reproducibility) more than self-serve UX.
    # channel_overrides={
    #     "C12345678": ast.SlackChannelOverride(
    #         agent=weather_agent,
    #         system_prompt="In #weather, always cite a source.",
    #     ),
    # },
    # state defaults to SQLite at /data/channel-state.db (provider mounts
    # the named volume vystak-slack-main-state automatically).
)
