"""D12: Discord with Postgres ChannelStore — exercises new shared schema."""

import json
import subprocess

import pytest


@pytest.mark.release_integration
@pytest.mark.docker
def test_D12_discord_postgres(project, discord_token):
    (project / "agent.yaml").write_text(
        """\
name: hero
model: anthropic/claude-haiku-4-5-20251001
adapter: langchain
provider: docker
channels:
  - name: discord-prod
    type: discord
    agents: [hero]
    default_agent: hero
    state:
      type: postgres
      dsn_secret: pg_dsn
secrets:
  - name: pg_dsn
    value: postgresql://postgres:vystakpw@vystak-data:5432/postgres
"""
    )
    apply = subprocess.run(
        ["vystak", "apply", "-y"],
        cwd=project, capture_output=True, text=True, timeout=300,
        env={**__import__("os").environ, "DISCORD_BOT_TOKEN": discord_token},
    )
    assert apply.returncode == 0, apply.stderr
    status = subprocess.run(
        ["vystak", "status", "--json"], cwd=project,
        capture_output=True, text=True, timeout=30,
    )
    parsed = json.loads(status.stdout)
    assert any(c.get("type") == "discord" for c in parsed.get("channels", []))
    subprocess.run(["vystak", "destroy", "-y"], cwd=project, check=True, timeout=120)
