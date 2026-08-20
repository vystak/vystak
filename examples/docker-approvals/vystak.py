"""Docker control panel example demonstrating human-in-the-loop tool approvals.

One agent (`approvals-agent`) with two tools: `read_status` runs freely,
`restart_service` is gated behind `Skill.needs_approval` — the model can
propose the call, but the runtime parks it (durably, surviving a browser
close or an agent container restart) until a human clicks Approve or Deny
in the panel. See README.md for the full walkthrough.

An optional, commented-out Slack channel block is included below for anyone
who wants to also exercise the Block Kit approval flow — it requires
`SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` and is not part of the default deploy.

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
    namespace="approvals",
    transport=ast.Transport(
        name="bus",
        type="nats",
        config=ast.NatsConfig(jetstream=True),
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

ops = ast.Skill(
    name="ops",
    tools=["read_status", "restart_service"],
    # restart_service is destructive: the model can propose it, but the
    # turn parks until a human approves or denies it. read_status is not
    # gated and runs immediately.
    needs_approval=["restart_service"],
)

approvals_agent = ast.Agent(
    name="approvals-agent",
    framework="langchain-python",
    instructions=(
        "When asked to fix the service, first call read_status, then call "
        "restart_service for the failing service, then summarize."
    ),
    default_model=sonnet,
    platform=platform,
    skills=[ops],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

panel = ast.Channel(
    name="panel",
    type=ast.ChannelType.PANEL,
    platform=platform,
    config={"port": 18100},
    agents=[approvals_agent],
    secrets=[ast.Secret(name="PANEL_SERVICE_TOKEN")],
)

# Optional: also expose the agent over Slack to exercise the Block Kit
# approval flow (Approve/Deny buttons on the gated tool-call message).
# Requires a Slack app with Socket Mode enabled and the bot invited to a
# channel. Uncomment to deploy alongside the panel channel above.
#
# slack = ast.Channel(
#     name="slack-main",
#     type=ast.ChannelType.SLACK,
#     platform=platform,
#     secrets=[
#         ast.Secret(name="SLACK_BOT_TOKEN"),
#         ast.Secret(name="SLACK_APP_TOKEN"),
#     ],
#     agents=[approvals_agent],
# )
