"""Docker control panel example demonstrating durable/checkpointed execution.

One agent with a deliberately slow four-step tool, plus the `panel` channel,
over the NATS transport. The point of this example isn't the agent's task —
it's the restart window: each `slow_step` call sleeps 20s, so a turn takes
~80s end to end, long enough to `docker restart` the agent container mid-run
by hand and watch the durable checkpointer resume the turn from where it left
off instead of losing it. See README.md for the full walkthrough.

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
    namespace="panel-durable",
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

durable_agent = ast.Agent(
    name="durable-agent",
    framework="langchain-python",
    instructions=(
        "You run a four-step job. When asked to run the job, call the "
        "slow_step tool exactly four times, in order, with label='one', "
        "then label='two', then label='three', then label='four'. Wait for "
        "each call to complete before making the next one. After all four "
        "steps finish, reply with a short summary confirming all four steps "
        "completed."
    ),
    default_model=sonnet,
    platform=platform,
    skills=[ast.Skill(name="steps", tools=["slow_step"])],
    secrets=[ast.Secret(name="ANTHROPIC_API_KEY")],
)

panel = ast.Channel(
    name="panel",
    type=ast.ChannelType.PANEL,
    platform=platform,
    config={"port": 18100},
    agents=[durable_agent],
    secrets=[ast.Secret(name="PANEL_SERVICE_TOKEN")],
)
