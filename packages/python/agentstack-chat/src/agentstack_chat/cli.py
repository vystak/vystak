"""AgentStack chat CLI — talk to your deployed agents."""

import asyncio

import click
from rich.console import Console
from rich.table import Table

from agentstack_chat import __version__, client
from agentstack_chat.chat import run_chat
from agentstack_chat.config import (
    add_agent,
    create_session,
    get_agent,
    get_session,
    get_sessions_for_agent,
    list_agents,
    list_sessions,
    remove_agent,
)

console = Console()


@click.group()
@click.version_option(version=__version__)
def cli():
    """AgentStack Chat — talk to your deployed agents."""


# --- Agent management ---


@cli.group()
def agents():
    """Manage saved agents."""


@agents.command("list")
def agents_list():
    """List saved agents."""
    saved = list_agents()
    if not saved:
        console.print("[dim]No saved agents. Add one with: agentstack-chat agents add <name> <url>[/dim]")
        return

    table = Table(title="Saved Agents")
    table.add_column("Name", style="bold cyan")
    table.add_column("URL")
    table.add_column("Status")

    for agent in saved:
        health_info = asyncio.run(client.health(agent["url"]))
        status = "[green]online[/green]" if health_info else "[red]offline[/red]"
        table.add_row(agent["name"], agent["url"], status)

    console.print(table)


@agents.command("add")
@click.argument("name")
@click.argument("url")
def agents_add(name, url):
    """Add or update a saved agent."""
    # Strip trailing slash
    url = url.rstrip("/")
    add_agent(name, url)
    console.print(f"[green]Saved agent '{name}' at {url}[/green]")


@agents.command("remove")
@click.argument("name")
def agents_remove(name):
    """Remove a saved agent."""
    if remove_agent(name):
        console.print(f"[green]Removed agent '{name}'[/green]")
    else:
        console.print(f"[red]Agent '{name}' not found[/red]")


# --- Session management ---


@cli.group()
def sessions():
    """Manage chat sessions."""


@sessions.command("list")
@click.option("--agent", "agent_name", default=None, help="Filter by agent name")
def sessions_list(agent_name):
    """List chat sessions."""
    if agent_name:
        saved = get_sessions_for_agent(agent_name)
    else:
        saved = list_sessions()

    if not saved:
        console.print("[dim]No sessions. Start one with: agentstack-chat chat <agent-name>[/dim]")
        return

    table = Table(title="Sessions")
    table.add_column("ID", style="bold")
    table.add_column("Agent", style="cyan")
    table.add_column("URL")

    for session in saved:
        table.add_row(session["id"][:8] + "...", session["agent_name"], session["agent_url"])

    console.print(table)


# --- Chat ---


@cli.command()
@click.argument("agent_name", required=False)
@click.option("--url", default=None, help="Agent URL (overrides saved config)")
@click.option("--session", "session_id", default=None, help="Resume a session by ID")
def chat(agent_name, url, session_id):
    """Start or resume a chat session.

    AGENT_NAME: Name of a saved agent, or omit to use --url.
    """
    # Resume existing session
    if session_id:
        session = get_session(session_id)
        if not session:
            # Try partial match
            for s in list_sessions():
                if s["id"].startswith(session_id):
                    session = s
                    break
        if not session:
            console.print(f"[red]Session '{session_id}' not found[/red]")
            raise SystemExit(1)
        run_chat(session["agent_name"], session["agent_url"], session["id"])
        return

    # Resolve agent URL
    if url:
        url = url.rstrip("/")
        agent_name = agent_name or "custom"
    elif agent_name:
        agent = get_agent(agent_name)
        if not agent:
            console.print(f"[red]Agent '{agent_name}' not found. Add it with: agentstack-chat agents add {agent_name} <url>[/red]")
            raise SystemExit(1)
        url = agent["url"]
    else:
        # Show agent picker
        saved = list_agents()
        if not saved:
            console.print("[red]No agents configured. Use --url or add an agent first.[/red]")
            raise SystemExit(1)

        console.print("\n[bold]Select an agent:[/bold]")
        for i, agent in enumerate(saved, 1):
            console.print(f"  [cyan]{i}[/cyan]. {agent['name']} ({agent['url']})")
        console.print()

        choice = click.prompt("Choice", type=int)
        if choice < 1 or choice > len(saved):
            console.print("[red]Invalid choice[/red]")
            raise SystemExit(1)

        selected = saved[choice - 1]
        agent_name = selected["name"]
        url = selected["url"]

    # Check health
    health_info = asyncio.run(client.health(url))
    if not health_info:
        console.print(f"[yellow]Warning: Agent at {url} is not responding[/yellow]")

    # Create new session
    session = create_session(agent_name, url)
    run_chat(agent_name, url, session["id"])


# --- Quick connect ---


@cli.command("connect")
@click.argument("url")
def connect(url):
    """Quick connect to an agent by URL (no saved config)."""
    url = url.rstrip("/")
    health_info = asyncio.run(client.health(url))

    if health_info:
        agent_name = health_info.get("agent", "unknown")
        console.print(f"[green]Connected to {agent_name}[/green]")
    else:
        agent_name = "unknown"
        console.print(f"[yellow]Warning: Agent at {url} is not responding[/yellow]")

    session = create_session(agent_name, url)
    run_chat(agent_name, url, session["id"])
