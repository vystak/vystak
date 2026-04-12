# Hello Agent

A minimal AgentStack example that deploys a LangGraph agent with two stub tools to a Docker container, using MiniMax's Anthropic-compatible API.

## Prerequisites

- Docker running locally
- A MiniMax API key (get one at https://platform.minimax.io)

## Quick Start

```bash
# From this directory:

# 1. Add your MiniMax API key to .env
cp .env.example .env
# Edit .env and paste your key

# 2. Preview the generated code (no Docker required)
uv run python preview.py

# 3. See what would be deployed
source .env && agentstack plan

# 4. Deploy to Docker
source .env && agentstack apply

# 5. Check status
agentstack status

# 6. Talk to your agent
curl -X POST http://localhost:PORT/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello! What can you do?"}'

# 7. Stream a response
curl -X POST http://localhost:PORT/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Tell me about yourself"}'

# 8. Check health
curl http://localhost:PORT/health

# 9. Tear down
agentstack destroy
```

Replace `PORT` with the port shown in `agentstack status`.

## How It Works

This example uses MiniMax's MiniMax-M2.7 model via their Anthropic-compatible API endpoint. The `agentstack.yaml` sets:

```yaml
model:
  provider:
    type: anthropic              # uses LangChain's ChatAnthropic
  model_name: MiniMax-M2.7       # MiniMax model
  parameters:
    anthropic_api_url: https://api.minimax.io/anthropic  # MiniMax endpoint
```

The `MINIMAX_API_KEY` env var holds your MiniMax token. LangChain's `ChatAnthropic` sends requests to MiniMax's endpoint instead of Anthropic's.

## What `agentstack apply` Creates

1. Reads `agentstack.yaml` and validates the agent definition
2. Generates three files using the LangChain adapter:
   - `agent.py` — LangGraph react agent with MiniMax model, stub tools, and system prompt
   - `server.py` — FastAPI server with `/invoke`, `/stream`, and `/health` endpoints
   - `requirements.txt` — Python dependencies
3. Generates a `Dockerfile` and builds a Docker image
4. Starts a container with the agent running on port 8000

## Customizing

Edit `agentstack.yaml` to change:

- **model** — switch model_name to `MiniMax-M2.5`, `MiniMax-M2.1`, etc.
- **skills** — add tools and prompts
- **parameters** — adjust temperature, max_tokens, etc.

To use Anthropic directly instead of MiniMax, remove the `anthropic_api_url` parameter and set `model_name` to a Claude model.

The generated tool functions are stubs. To add real tool implementations, replace the stub functions in the generated `agent.py`.

## Using Python Instead of YAML

You can also define agents in Python. Create `agentstack.py`:

```python
from agentstack import Agent, Model, Provider, Skill, Channel, ChannelType, Secret

provider = Provider(name="anthropic", type="anthropic")

model = Model(
    name="minimax",
    provider=provider,
    model_name="MiniMax-M2.7",
    parameters={
        "temperature": 0.7,
        "anthropic_api_url": "https://api.minimax.io/anthropic",
    },
)

agent = Agent(
    name="hello-agent",
    model=model,
    skills=[
        Skill(
            name="assistant",
            tools=["get_weather", "get_time"],
            prompt="You are a helpful assistant. Be concise and friendly.",
        ),
    ],
    channels=[Channel(name="api", type=ChannelType.API)],
    secrets=[Secret(name="MINIMAX_API_KEY")],
)
```

Then run `agentstack plan` / `agentstack apply` as usual.
