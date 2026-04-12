"""Interactive chat loop with Rich TUI."""

import asyncio

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from agentstack_chat import client


console = Console()


def _render_streaming(tokens: list[str]) -> Panel:
    """Render accumulated tokens as a markdown panel."""
    text = "".join(tokens)
    if text:
        return Panel(Markdown(text), title="Agent", border_style="blue", expand=True)
    return Panel(Text("Thinking...", style="dim"), title="Agent", border_style="blue", expand=True)


async def _stream_response(url: str, message: str, session_id: str) -> str:
    """Stream response with live Rich rendering."""
    tokens = []

    with Live(_render_streaming(tokens), console=console, refresh_per_second=15) as live:
        async for token in client.stream(url, message, session_id):
            tokens.append(token)
            live.update(_render_streaming(tokens))

    full_response = "".join(tokens)

    # If streaming didn't work, fall back to invoke
    if not full_response:
        console.print(Text("Streaming unavailable, using invoke...", style="dim"))
        full_response = await client.invoke(url, message, session_id)
        console.print(Panel(Markdown(full_response), title="Agent", border_style="blue"))

    return full_response


async def chat_loop(agent_name: str, agent_url: str, session_id: str) -> None:
    """Run the interactive chat loop."""
    console.print()
    console.print(
        Panel(
            f"[bold]Agent:[/bold] {agent_name}\n"
            f"[bold]Session:[/bold] {session_id[:8]}...\n"
            f"[bold]URL:[/bold] {agent_url}\n\n"
            "[dim]Type your message and press Enter. Type 'exit' or 'quit' to leave.[/dim]",
            title="AgentStack Chat",
            border_style="green",
        )
    )
    console.print()

    while True:
        try:
            message = Prompt.ask("[bold cyan]You[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break

        message = message.strip()
        if not message:
            continue
        if message.lower() in ("exit", "quit", "/exit", "/quit"):
            console.print("[dim]Goodbye![/dim]")
            break

        try:
            await _stream_response(agent_url, message, session_id)
            console.print()
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            console.print()


def run_chat(agent_name: str, agent_url: str, session_id: str) -> None:
    """Entry point for the chat loop."""
    asyncio.run(chat_loop(agent_name, agent_url, session_id))
