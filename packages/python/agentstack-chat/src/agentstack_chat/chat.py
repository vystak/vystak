"""Interactive chat REPL — Claude Code-style terminal interface."""

import asyncio
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.layout.containers import Float, FloatContainer, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import Frame, TextArea
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from agentstack_chat import client
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


# Slash command definitions: (command, args_hint, description)
COMMANDS = [
    ("/connect", "<url>", "Connect to an agent by URL"),
    ("/use", "<name>", "Connect to a saved agent"),
    ("/agents", "", "List saved agents"),
    ("/agents add", "<name> <url>", "Save an agent"),
    ("/agents remove", "<name>", "Remove a saved agent"),
    ("/sessions", "[agent]", "List sessions"),
    ("/new", "", "New session (same agent)"),
    ("/resume", "<id>", "Resume a session"),
    ("/status", "", "Show connection info"),
    ("/help", "", "Show commands"),
    ("/exit", "", "Quit"),
]


class SlashCompleter(Completer):
    """Autocomplete slash commands with descriptions."""

    def __init__(self, repl: "ChatREPL"):
        self._repl = repl

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        if not text.startswith("/"):
            return

        # Complete agent names for /use and /agents remove
        parts = text.split()
        if len(parts) >= 2 and parts[0] in ("/use", "/resume"):
            prefix = parts[1] if len(parts) == 2 else ""
            if parts[0] == "/use":
                for agent in list_agents():
                    if agent["name"].startswith(prefix):
                        yield Completion(
                            agent["name"],
                            start_position=-len(prefix),
                            display=agent["name"],
                            display_meta=agent["url"],
                        )
            elif parts[0] == "/resume":
                for session in list_sessions():
                    short_id = session["id"][:8]
                    if short_id.startswith(prefix):
                        yield Completion(
                            short_id,
                            start_position=-len(prefix),
                            display=short_id,
                            display_meta=session["agent_name"],
                        )
            return

        if len(parts) >= 2 and parts[0] == "/agents" and parts[1] == "remove":
            prefix = parts[2] if len(parts) == 3 else ""
            for agent in list_agents():
                if agent["name"].startswith(prefix):
                    yield Completion(
                        agent["name"],
                        start_position=-len(prefix),
                        display=agent["name"],
                    )
            return

        # Complete commands
        for cmd, args_hint, desc in COMMANDS:
            if cmd.startswith(text):
                display_text = f"{cmd} {args_hint}".strip()
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display=display_text,
                    display_meta=desc,
                )

custom_theme = Theme({
    "user": "bold cyan",
    "agent": "bold blue",
    "system": "dim",
    "error": "bold red",
    "success": "bold green",
    "warning": "bold yellow",
})

console = Console(theme=custom_theme)


def _render_streaming(tokens: list[str], agent_name: str) -> Text:
    """Render accumulated tokens during streaming."""
    text = "".join(tokens)
    if text:
        return Text(text)
    return Text("...", style="dim")


async def _stream_response(url: str, message: str, session_id: str, agent_name: str) -> client.StreamResult:
    """Stream response with live rendering. Returns usage info."""
    stream_result = client.StreamResult()
    console.print(f"\n[agent]{agent_name}[/agent]")
    has_output = False

    try:
        async for event in client.stream_events(url, message, session_id, result=stream_result):
            if event.type == "token":
                has_output = True
                sys.stdout.write(event.token)
                sys.stdout.flush()

            elif event.type == "tool_call_start":
                if has_output:
                    console.print()  # newline before tool info
                console.print(f"  [dim]> calling {event.tool}...[/dim]")
                has_output = False

            elif event.type == "tool_result":
                result_preview = event.result[:100] + "..." if len(event.result) > 100 else event.result
                console.print(f"  [dim]> {event.tool}: {result_preview}[/dim]")

            elif event.type == "done":
                if has_output:
                    console.print()  # final newline after tokens

        if not has_output:
            # Streaming produced no text — fallback to invoke
            invoke_result = await client.invoke(url, message, session_id)
            console.print(Markdown(invoke_result.response))
            stream_result.input_tokens = invoke_result.input_tokens
            stream_result.output_tokens = invoke_result.output_tokens
            stream_result.total_tokens = invoke_result.total_tokens

    except Exception:
        console.print()
        invoke_result = await client.invoke(url, message, session_id)
        console.print(Markdown(invoke_result.response))
        stream_result.input_tokens = invoke_result.input_tokens
        stream_result.output_tokens = invoke_result.output_tokens
        stream_result.total_tokens = invoke_result.total_tokens

    return stream_result


class ChatREPL:
    """Interactive chat REPL with slash commands."""

    def __init__(self):
        self._agent_name: str | None = None
        self._agent_url: str | None = None
        self._session_id: str | None = None
        self._running = True
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._last_input_tokens: int = 0
        self._last_output_tokens: int = 0

    @property
    def connected(self) -> bool:
        return self._agent_url is not None and self._session_id is not None

    def _reset_tokens(self):
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._last_input_tokens = 0
        self._last_output_tokens = 0

    def _show_welcome(self):
        console.print()
        console.print("[bold]AgentStack Chat[/bold] v0.1.0", style="success")
        console.print("[system]Type /help for commands, or start chatting.[/system]")
        console.print()

    def _show_help(self):
        console.print()
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="cyan")
        table.add_column()
        table.add_row("/connect <url>", "Connect to an agent by URL")
        table.add_row("/use <name>", "Connect to a saved agent")
        table.add_row("/agents", "List saved agents")
        table.add_row("/agents add <name> <url>", "Save an agent")
        table.add_row("/agents remove <name>", "Remove a saved agent")
        table.add_row("/sessions", "List sessions")
        table.add_row("/new", "New session (same agent)")
        table.add_row("/resume <id>", "Resume a session")
        table.add_row("/status", "Show connection info")
        table.add_row("/help", "Show this help")
        table.add_row("/exit", "Quit")
        console.print(table)
        console.print()

    def _show_status(self):
        if self.connected:
            console.print(f"  [system]agent:[/system]   [agent]{self._agent_name}[/agent]")
            console.print(f"  [system]session:[/system] {self._session_id[:8]}...")
            console.print(f"  [system]url:[/system]     {self._agent_url}")
        else:
            console.print("[warning]Not connected[/warning]")

    def _prompt(self) -> str:
        """Get the prompt string."""
        if self.connected:
            return f"{self._agent_name} > "
        return "> "

    async def _cmd_connect(self, args: str):
        url = args.strip().rstrip("/")
        if not url:
            console.print("[error]Usage: /connect <url>[/error]")
            return

        health_info = await client.health(url)

        if health_info:
            agent_name = health_info.get("agent", "unknown")
            console.print(f"[success]Connected to {agent_name}[/success]")
        else:
            agent_name = "unknown"
            console.print(f"[warning]Agent at {url} not responding, connecting anyway[/warning]")

        self._agent_name = agent_name
        self._agent_url = url

        session = create_session(agent_name, url)
        self._session_id = session["id"]

        # Auto-save the agent
        add_agent(agent_name, url)

    async def _cmd_use(self, args: str):
        name = args.strip()
        if not name:
            console.print("[error]Usage: /use <agent-name>[/error]")
            return

        agent = get_agent(name)
        if not agent:
            console.print(f"[error]Agent '{name}' not found. /agents to list.[/error]")
            return

        await self._cmd_connect(agent["url"])

    async def _cmd_agents(self, args: str):
        parts = args.strip().split(maxsplit=2)
        sub = parts[0] if parts else ""

        if sub == "add" and len(parts) == 3:
            _, name, url = parts
            add_agent(name, url.rstrip("/"))
            console.print(f"[success]Saved: {name} -> {url}[/success]")
            return

        if sub == "remove" and len(parts) == 2:
            _, name = parts
            if remove_agent(name):
                console.print(f"[success]Removed: {name}[/success]")
            else:
                console.print(f"[error]Not found: {name}[/error]")
            return

        saved = list_agents()
        if not saved:
            console.print("[system]No saved agents. /agents add <name> <url>[/system]")
            return

        console.print()
        for agent in saved:
            health_info = await client.health(agent["url"])
            status = "[success]online[/success]" if health_info else "[error]offline[/error]"
            console.print(f"  [cyan]{agent['name']}[/cyan]  {agent['url']}  {status}")
        console.print()

    def _cmd_sessions(self, args: str):
        agent_filter = args.strip() or None
        saved = get_sessions_for_agent(agent_filter) if agent_filter else list_sessions()

        if not saved:
            console.print("[system]No sessions.[/system]")
            return

        console.print()
        for s in saved:
            marker = " [success]<- current[/success]" if s["id"] == self._session_id else ""
            console.print(f"  [bold]{s['id'][:8]}[/bold]  [cyan]{s['agent_name']}[/cyan]  {s['agent_url']}{marker}")
        console.print()

    def _cmd_resume(self, args: str):
        session_id = args.strip()
        if not session_id:
            console.print("[error]Usage: /resume <session-id>[/error]")
            return

        session = get_session(session_id)
        if not session:
            for s in list_sessions():
                if s["id"].startswith(session_id):
                    session = s
                    break

        if not session:
            console.print(f"[error]Session not found. /sessions to list.[/error]")
            return

        self._agent_name = session["agent_name"]
        self._agent_url = session["agent_url"]
        self._session_id = session["id"]
        console.print(f"[success]Resumed: {self._agent_name} ({self._session_id[:8]}...)[/success]")

    def _cmd_new(self):
        if not self._agent_url:
            console.print("[error]Not connected. /connect or /use first.[/error]")
            return

        session = create_session(self._agent_name, self._agent_url)
        self._session_id = session["id"]
        console.print(f"[success]New session: {self._session_id[:8]}...[/success]")

    async def _handle_command(self, line: str):
        parts = line[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        match cmd:
            case "exit" | "quit":
                self._running = False
            case "help":
                self._show_help()
            case "connect":
                await self._cmd_connect(args)
            case "use":
                await self._cmd_use(args)
            case "agents":
                await self._cmd_agents(args)
            case "sessions":
                self._cmd_sessions(args)
            case "resume":
                self._cmd_resume(args)
            case "new":
                self._cmd_new()
            case "status":
                self._show_status()
            case _:
                console.print(f"[error]Unknown: /{cmd}[/error]  [system]Type /help[/system]")

    async def _handle_message(self, message: str):
        if not self.connected:
            console.print("[warning]Not connected. /connect <url> or /use <name>[/warning]")
            return

        try:
            console.print(f"\n[user]You[/user]")
            console.print(message)
            result = await _stream_response(self._agent_url, message, self._session_id, self._agent_name)
            self._last_input_tokens = result.input_tokens
            self._last_output_tokens = result.output_tokens
            self._total_input_tokens += result.input_tokens
            self._total_output_tokens += result.output_tokens
        except Exception as e:
            console.print(f"[error]{e}[/error]")

    def _format_tokens(self, count: int) -> str:
        """Format token count with K/M suffixes."""
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        if count >= 1_000:
            return f"{count / 1_000:.1f}K"
        return str(count)

    def _bottom_toolbar(self):
        """Status line below the input — shows agent, session, tokens."""
        if self.connected:
            total = self._total_input_tokens + self._total_output_tokens
            tokens_str = (
                f'tokens: {self._format_tokens(total)}'
                f' ({self._format_tokens(self._total_input_tokens)} in'
                f' / {self._format_tokens(self._total_output_tokens)} out)'
            ) if total > 0 else "tokens: 0"

            return HTML(
                f'  <style fg="#6a6a8a">{self._agent_name}</style>'
                f' <style fg="#444444">|</style>'
                f' <style fg="#6a6a8a">session: {self._session_id[:8]}</style>'
                f' <style fg="#444444">|</style>'
                f' <style fg="#6a6a8a">{tokens_str}</style>'
            )
        return HTML(
            '  <style fg="#6a6a8a">not connected</style>'
            ' <style fg="#444444">|</style>'
            ' <style fg="#6a6a8a">/connect &lt;url&gt; or /use &lt;name&gt;</style>'
        )

    async def run(self):
        """Run the REPL."""
        self._show_welcome()

        session = PromptSession(
            completer=SlashCompleter(self),
            history=InMemoryHistory(),
            complete_while_typing=True,
            bottom_toolbar=self._bottom_toolbar,
        )

        while self._running:
            try:
                line = await session.prompt_async(
                    HTML('<b><style fg="ansibrightcyan">&gt; </style></b>'),
                )
            except (KeyboardInterrupt, EOFError):
                console.print("\n[system]Goodbye![/system]")
                break

            line = line.strip()
            if not line:
                continue

            if line.startswith("/"):
                await self._handle_command(line)
            else:
                await self._handle_message(line)


def run_repl(auto_connect_url: str | None = None):
    """Entry point."""
    async def _run():
        repl = ChatREPL()
        if auto_connect_url:
            repl._show_welcome()
            await repl._cmd_connect(auto_connect_url)
        await repl.run()

    asyncio.run(_run())
