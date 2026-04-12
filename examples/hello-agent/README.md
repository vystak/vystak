# Hello Agent

A minimal AgentStack example that deploys a LangGraph agent with two stub tools to a Docker container.

## Prerequisites

- Docker running locally
- An Anthropic API key

## Quick Start

```bash
# From this directory:

# 1. See what would be deployed
agentstack plan

# 2. Deploy to Docker
ANTHROPIC_API_KEY=your-key-here agentstack apply

# 3. Check status
agentstack status

# 4. Talk to your agent
curl -X POST http://localhost:PORT/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello! What can you do?"}'

# 5. Stream a response
curl -X POST http://localhost:PORT/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Tell me about yourself"}'

# 6. Check health
curl http://localhost:PORT/health

# 7. Tear down
agentstack destroy
```

Replace `PORT` with the port shown in `agentstack status`.

## What This Creates

`agentstack apply` does the following:

1. Reads `agentstack.yaml` and validates the agent definition
2. Generates three files using the LangChain adapter:
   - `agent.py` — LangGraph react agent with Claude, stub tools, and system prompt
   - `server.py` — FastAPI server with `/invoke`, `/stream`, and `/health` endpoints
   - `requirements.txt` — Python dependencies
3. Generates a `Dockerfile` and builds a Docker image
4. Starts a container with the agent running on port 8000

## Customizing

Edit `agentstack.yaml` to change:

- **model** — switch to a different model or provider (e.g., OpenAI)
- **skills** — add tools and prompts
- **parameters** — adjust temperature, max_tokens, etc.

The generated tool functions are stubs. To add real tool implementations, you'll replace the stub functions in the generated `agent.py` after inspecting the output.

## Using Python Instead of YAML

You can also define agents in Python. Create `agentstack.py`:

```python
from agentstack import Agent, Model, Provider, Skill, Channel, ChannelType, Secret

anthropic = Provider(name="anthropic", type="anthropic")

model = Model(
    name="claude",
    provider=anthropic,
    model_name="claude-sonnet-4-20250514",
    parameters={"temperature": 0.7},
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
    secrets=[Secret(name="ANTHROPIC_API_KEY")],
)
```

Then run `agentstack plan` / `agentstack apply` as usual — the CLI auto-discovers `agentstack.py`.
