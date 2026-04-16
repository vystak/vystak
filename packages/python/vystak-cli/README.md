# vystak-cli

The `vystak` command — manage and deploy AI agents from the terminal.

## Install

```bash
pip install vystak-cli
```

This pulls in `vystak`, `vystak-adapter-langchain`, and `vystak-provider-docker` automatically.

## Quick start

```bash
# Create a starter agent
vystak init

# Preview what would be deployed
vystak plan

# Deploy to Docker
export ANTHROPIC_API_KEY=your-key
vystak apply

# Tail logs
vystak logs

# Check status
vystak status

# Tear down
vystak destroy
```

## Commands

| Command | Description |
|---------|-------------|
| `vystak init` | Scaffold a starter `vystak.yaml` |
| `vystak plan` | Show what would change without applying |
| `vystak apply` | Deploy or update the agent |
| `vystak destroy` | Stop and remove the agent |
| `vystak status` | Show deployed agent status |
| `vystak logs` | Tail agent container logs |

## Agent definition

The CLI loads either a YAML or Python file:

```yaml
# vystak.yaml
name: support-bot
model:
  name: claude
  provider: { name: anthropic, type: anthropic }
  model_name: claude-sonnet-4-20250514
platform:
  name: docker
  type: docker
  provider: { name: docker, type: docker }
channels:
  - { name: api, type: api }
secrets:
  - { name: ANTHROPIC_API_KEY }
```

```python
# vystak.py
import vystak as ast

anthropic = ast.Provider(name="anthropic", type="anthropic")
docker = ast.Provider(name="docker", type="docker")
agent = ast.Agent(
    name="support-bot",
    model=ast.Model(name="claude", provider=anthropic, model_name="claude-sonnet-4-20250514"),
    platform=ast.Platform(name="docker", type="docker", provider=docker),
    channels=[ast.Channel(name="api", type=ast.ChannelType.API)],
)
```

See the [main repository](https://github.com/vystak/vystak) for full documentation and examples.

## License

Apache-2.0
