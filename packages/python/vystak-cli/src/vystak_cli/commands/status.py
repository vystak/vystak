"""vystak status — show agent and channel status."""

from pathlib import Path

import click

from vystak_cli.loader import find_agent_file, load_definitions
from vystak_cli.provider_factory import get_provider


@click.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--file", "file_path", default=None, help="Path to agent definition file (legacy)")
@click.option("--name", "agent_name", default=None, help="Show status for a specific agent")
def status(files, file_path, agent_name):
    """Show the status of deployed agents and channels."""
    if agent_name and not files and not file_path:
        from vystak_provider_docker import DockerProvider

        provider = DockerProvider()
        _show_agent_status(provider, agent_name)
        return

    if files:
        paths = [Path(f) for f in files]
    elif file_path:
        paths = [Path(file_path)]
    else:
        paths = [find_agent_file()]

    base_dir = paths[0].parent if paths[0].is_file() else paths[0].parent
    defs = load_definitions(paths, base_dir=base_dir)

    agents = defs.agents
    channels = defs.channels

    if agent_name:
        agents = [a for a in agents if a.name == agent_name]
        channels = [c for c in channels if c.name == agent_name]

    for agent in agents:
        provider = get_provider(agent)
        provider.set_agent(agent)
        _show_agent_status(provider, agent.name)

    for channel in channels:
        provider = get_provider(channel)
        _show_channel_status(provider, channel)


def _show_agent_status(provider, agent_name: str):
    agent_status = provider.status(agent_name)
    click.echo(f"Agent: {agent_name}")
    if agent_status.running:
        click.echo("  Status: running")
        if agent_status.hash:
            click.echo(f"  Hash: {agent_status.hash[:16]}...")
        info = agent_status.info
        if "url" in info and info["url"]:
            click.echo(f"  URL: {info['url']}")
        elif "ports" in info and "8000/tcp" in info["ports"] and info["ports"]["8000/tcp"]:
            host_port = info["ports"]["8000/tcp"][0].get("HostPort", "?")
            click.echo(f"  URL: http://localhost:{host_port}")
    else:
        click.echo("  Status: not deployed")


def _show_channel_status(provider, channel):
    click.echo(f"Channel: {channel.name}")
    try:
        st = provider.channel_status(channel)
    except NotImplementedError as e:
        click.echo(f"  Status: unknown ({e})")
        return

    if st.running:
        click.echo("  Status: running")
        if st.hash:
            click.echo(f"  Hash: {st.hash[:16]}...")
        info = getattr(st, "info", {}) or {}
        if info.get("url"):
            click.echo(f"  URL: {info['url']}")
    else:
        click.echo("  Status: not deployed")
