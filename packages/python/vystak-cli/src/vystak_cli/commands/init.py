"""vystak init — create a starter agent definition."""

from pathlib import Path

import click

STARTER_YAML = """\
name: my-agent
model:
  name: claude
  provider:
    name: anthropic
    type: anthropic
  model_name: claude-sonnet-4-20250514
platform:
  name: docker
  type: docker
  provider:
    name: docker
    type: docker
sessions:
  type: postgres
  provider:
    name: docker
    type: docker
skills:
  - name: assistant
    tools: []
    prompt: You are a helpful assistant.
secrets:
  - name: ANTHROPIC_API_KEY
"""


@click.command()
def init():
    """Create a starter agent definition."""
    path = Path("vystak.yaml")
    if path.exists():
        click.echo("Error: vystak.yaml already exists", err=True)
        raise SystemExit(1)

    path.write_text(STARTER_YAML)
    click.echo(f"Created {path}")
