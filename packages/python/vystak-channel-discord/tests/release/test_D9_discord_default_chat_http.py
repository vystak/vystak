"""D9: Discord default chat over HTTP — V1 plan, V2 apply, V4 health, V9 destroy."""

import json
import subprocess

import pytest


@pytest.mark.release_smoke
@pytest.mark.docker
def test_D9_discord_default_chat_http(project, discord_token):
    """Deploy a single-agent Discord channel; verify health, then destroy."""
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
"""
    )

    plan = subprocess.run(
        ["vystak", "plan"], cwd=project, capture_output=True, text=True, timeout=60,
    )
    assert plan.returncode == 0, plan.stderr

    apply = subprocess.run(
        ["vystak", "apply", "-y"],
        cwd=project,
        capture_output=True, text=True, timeout=300,
        env={
            **__import__("os").environ,
            "DISCORD_BOT_TOKEN": discord_token,
        },
    )
    assert apply.returncode == 0, apply.stderr

    status = subprocess.run(
        ["vystak", "status", "--json"],
        cwd=project, capture_output=True, text=True, timeout=30,
    )
    parsed = json.loads(status.stdout)
    discord_entries = [e for e in parsed.get("channels", []) if e.get("type") == "discord"]
    assert discord_entries, "no discord channel reported in status"
    assert all(e.get("health") == "ok" for e in discord_entries)

    destroy = subprocess.run(
        ["vystak", "destroy", "-y"],
        cwd=project, capture_output=True, text=True, timeout=120,
    )
    assert destroy.returncode == 0, destroy.stderr
