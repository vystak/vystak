"""Interactive chat REPL — Claude Code-style terminal interface."""

import asyncio
import sys

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
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
from rich.padding import Padding


# Slash command definitions: (command, args_hint, description)
COMMANDS = [
    ("/connect", "<url>", "Connect to an agent by URL"),
    ("/use", "<name>", "Connect to a saved agent"),
    ("/agents", "", "List saved agents"),
    ("/agents add", "<name> <url>", "Save an agent"),
    ("/agents remove", "<name>", "Remove a saved agent"),
    ("/gateway", "<url>", "Connect to a gateway — discover agents"),
    ("/sessions", "", "Pick a session to resume"),
    ("/new", "", "New session (same agent)"),
    ("/resume", "<id>", "Resume a session by ID"),
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


async def _stream_response(
    url: str, message: str, agent_name: str, model: str = "",
    previous_response_id: str | None = None,
) -> tuple[client.StreamResult, str]:
    """Stream response without disrupting the prompt_toolkit layout.

    Returns (StreamResult, response_id).
    """
    stream_result = client.StreamResult()
    tokens_buf: list[str] = []
    has_output = False
    status_line_shown = False
    response_id = ""

    # Print status line (will be overwritten by first token)
    console.print(f"[agent]{agent_name}[/agent] [dim]thinking...[/dim]", end="\r")
    status_line_shown = True

    try:
        async for event in client.stream_response(
            url, message, model=model,
            previous_response_id=previous_response_id,
            result=stream_result,
        ):
            if event.type == "token":
                if status_line_shown:
                    console.print(" " * 60, end="\r")
                    status_line_shown = False
                has_output = True
                tokens_buf.append(event.token)

            elif event.type == "function_call_start":
                if status_line_shown:
                    console.print(" " * 60, end="\r")
                    status_line_shown = False
                console.print(f"[dim]  > calling {event.tool}...[/dim]")

            elif event.type == "function_call_output":
                result_preview = event.result[:200] + "..." if len(event.result) > 200 else event.result
                console.print(f"[dim]  > result:[/dim]")
                console.print(Padding(Markdown(result_preview), (0, 0, 0, 4)))
                console.print(f"[agent]{agent_name}[/agent] [dim]thinking...[/dim]", end="\r")
                status_line_shown = True

            elif event.type == "done":
                if event.response_id:
                    response_id = event.response_id
                if status_line_shown:
                    console.print(" " * 60, end="\r")
                    status_line_shown = False
                if has_output:
                    console.print(f"[agent]{agent_name}[/agent]")
                    console.print(Markdown("".join(tokens_buf)))

        if not has_output:
            if status_line_shown:
                console.print(" " * 60, end="\r")
            invoke_result = await client.send_response(
                url, message, model=model,
                previous_response_id=previous_response_id,
            )
            console.print(f"[agent]{agent_name}[/agent]")
            console.print(Markdown(invoke_result.response))
            stream_result.input_tokens = invoke_result.input_tokens
            stream_result.output_tokens = invoke_result.output_tokens
            stream_result.total_tokens = invoke_result.total_tokens
            response_id = invoke_result.response_id

    except Exception:
        if status_line_shown:
            console.print(" " * 60, end="\r")
        invoke_result = await client.send_response(
            url, message, model=model,
            previous_response_id=previous_response_id,
        )
        console.print(f"[agent]{agent_name}[/agent]")
        console.print(Markdown(invoke_result.response))
        stream_result.input_tokens = invoke_result.input_tokens
        stream_result.output_tokens = invoke_result.output_tokens
        stream_result.total_tokens = invoke_result.total_tokens
        response_id = invoke_result.response_id

    return stream_result, response_id


class ChatREPL:
    """Interactive chat REPL with slash commands."""

    def __init__(self):
        self._agent_name: str | None = None
        self._agent_url: str | None = None
        self._model: str = ""  # OpenAI model ID (e.g., "agentstack/assistant-agent")
        self._previous_response_id: str | None = None
        self._running = True
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._last_input_tokens: int = 0
        self._last_output_tokens: int = 0

    @property
    def connected(self) -> bool:
        return self._agent_url is not None

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
        table.add_row("/gateway <url>", "Discover agents from a gateway")
        table.add_row("/agents", "List saved agents")
        table.add_row("/agents add <name> <url>", "Save an agent")
        table.add_row("/agents remove <name>", "Remove a saved agent")
        table.add_row("/sessions", "Pick a session to resume")
        table.add_row("/new", "New session (same agent)")
        table.add_row("/resume <id>", "Resume a session by ID")
        table.add_row("/status", "Show connection info")
        table.add_row("/help", "Show this help")
        table.add_row("/exit", "Quit")
        console.print(table)
        console.print()

    def _show_status(self):
        if self.connected:
            console.print(f"  [system]agent:[/system]   [agent]{self._agent_name}[/agent]")
            response_label = (self._previous_response_id[:8] + "...") if self._previous_response_id else "new"
            console.print(f"  [system]response:[/system] {response_label}")
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

        if health_info and "routes" in health_info:
            # This is a gateway — auto-discover agents and pick one
            console.print(f"[dim]Detected gateway at {url}[/dim]")
            await self._cmd_gateway(url)
            return

        if health_info:
            agent_name = health_info.get("agent", "unknown")
            console.print(f"[success]Connected to {agent_name}[/success]")
        else:
            agent_name = "unknown"
            console.print(f"[warning]Agent at {url} not responding, connecting anyway[/warning]")

        self._agent_name = agent_name
        self._agent_url = url
        self._model = f"agentstack/{agent_name}"
        self._previous_response_id = None

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
        from agentstack_chat.picker import pick

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

        # Check health for all agents
        items = []
        for agent in saved:
            health_info = await client.health(agent["url"])
            status = "online" if health_info else "offline"
            current = " (connected)" if agent["url"] == self._agent_url else ""
            items.append({
                "label": f"{agent['name']}{current}",
                "detail": f"{agent['url']}  [{status}]",
                "agent": agent,
            })

        selected = await pick("Agents", items)
        if selected is None:
            return

        agent = selected["agent"]
        await self._cmd_connect(agent["url"])

    async def _cmd_sessions(self, args: str):
        from agentstack_chat.picker import pick

        agent_filter = args.strip() or None
        saved = get_sessions_for_agent(agent_filter) if agent_filter else list_sessions()

        if not saved:
            console.print("[system]No sessions. Start chatting to create one.[/system]")
            return

        # Build picker items
        items = []
        for s in saved:
            items.append({
                "label": f"{s['id'][:8]}  {s['agent_name']}",
                "detail": s["agent_url"],
                "session": s,
            })
        items.append({"label": "+ New conversation", "detail": "Start a new conversation", "session": None})

        selected = await pick("Sessions", items)
        if selected is None:
            return

        session = selected["session"]
        if session is None:
            # New conversation
            if self._agent_url:
                self._cmd_new()
            else:
                console.print("[warning]Connect to an agent first (/connect or /use)[/warning]")
            return

        self._agent_name = session["agent_name"]
        self._agent_url = session["agent_url"]
        self._previous_response_id = None
        self._reset_tokens()
        console.print(f"[success]Connected to {self._agent_name}[/success]")

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
        self._previous_response_id = None
        self._reset_tokens()
        console.print(f"[success]Connected to {self._agent_name}[/success]")

    def _cmd_new(self):
        if not self._agent_url:
            console.print("[error]Not connected. /connect or /use first.[/error]")
            return

        self._previous_response_id = None
        self._reset_tokens()
        console.print(f"[success]New conversation started[/success]")

    async def _cmd_gateway(self, args: str):
        """Connect to a gateway and pick an agent."""
        from agentstack_chat.picker import pick

        gateway_url = args.strip().rstrip("/")
        if not gateway_url:
            console.print("[error]Usage: /gateway <url>[/error]")
            return

        console.print(f"[dim]Connecting to gateway at {gateway_url}...[/dim]")
        routes = await client.gateway_routes(gateway_url)

        if not routes:
            console.print(f"[error]No agents found at {gateway_url}[/error]")
            return

        # Deduplicate agents from routes
        agents_map = {}
        for route in routes:
            name = route.get("agent_name", "unknown")
            url = route.get("agent_url", "")
            channels = route.get("channels", [])
            if name not in agents_map:
                agents_map[name] = {"name": name, "url": url, "channels": []}
            agents_map[name]["channels"].extend(channels)

        items = []
        for name, info in agents_map.items():
            channels_str = ", ".join(info["channels"]) if info["channels"] else "no channels"
            items.append({
                "label": name,
                "detail": f"{info['url']}  ({channels_str})",
                "agent_name": name,
                "agent_url": info["url"],
            })

        if len(items) == 1:
            selected = items[0]
        else:
            selected = await pick("Select Agent", items)

        if selected is None:
            return

        agent_name = selected["agent_name"]
        # Use gateway URL with model routing (not the old proxy URL)
        agent_url = gateway_url
        model_id = f"agentstack/{agent_name}"

        # Save and connect
        add_agent(agent_name, agent_url)
        console.print(f"[success]Connected to {agent_name} via gateway[/success]")

        self._agent_name = agent_name
        self._agent_url = agent_url
        self._model = model_id
        self._previous_response_id = None
        self._reset_tokens()

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
            case "gateway":
                await self._cmd_gateway(args)
            case "sessions":
                await self._cmd_sessions(args)
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
            result, response_id = await _stream_response(
                self._agent_url, message, self._agent_name,
                model=self._model,
                previous_response_id=self._previous_response_id,
            )
            if response_id:
                self._previous_response_id = response_id
            self._last_input_tokens = result.input_tokens
            self._last_output_tokens = result.output_tokens
            self._total_input_tokens += result.input_tokens
            self._total_output_tokens += result.output_tokens
        except Exception as e:
            console.print(f"[error]{e}[/error]")

    async def _process_queue(self):
        """Process all queued messages sequentially."""
        self._processing = True
        try:
            while not self._message_queue.empty():
                message = await self._message_queue.get()
                await self._handle_message(message)
                remaining = self._message_queue.qsize()
                if remaining > 0:
                    console.print(f"[system]  ({remaining} queued)[/system]")
        finally:
            self._processing = False

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

            response_label = self._previous_response_id[:8] if self._previous_response_id else "new"
            return HTML(
                f'  <style fg="#6a6a8a">{self._agent_name}</style>'
                f' <style fg="#444444">|</style>'
                f' <style fg="#6a6a8a">response: {response_label}</style>'
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

        # Persistent history — last 30 prompts saved to disk
        history_path = Path.home() / ".agentstack" / "chat_history"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history = FileHistory(str(history_path))

        session = PromptSession(
            completer=SlashCompleter(self),
            history=history,
            complete_while_typing=True,
            bottom_toolbar=self._bottom_toolbar,
        )

        # Message queue — type while agent is responding
        self._message_queue: asyncio.Queue[str] = asyncio.Queue()
        self._processing = False

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
                # Queue the message
                await self._message_queue.put(line)
                # Process queue if not already processing
                if not self._processing:
                    await self._process_queue()


def run_repl(auto_connect_url: str | None = None, auto_gateway_url: str | None = None):
    """Entry point for interactive REPL."""
    async def _run():
        repl = ChatREPL()
        if auto_connect_url:
            repl._show_welcome()
            await repl._cmd_connect(auto_connect_url)
        elif auto_gateway_url:
            repl._show_welcome()
            await repl._cmd_gateway(auto_gateway_url)
        await repl.run()

    asyncio.run(_run())


def run_oneshot(url: str | None = None, message: str = ""):
    """Send a single message and exit. For scripting/piping."""
    from agentstack_chat.config import get_agent, list_agents

    async def _run():
        # Resolve URL
        agent_url = url
        agent_name = "agent"
        model = ""

        if not agent_url:
            # Try first saved agent
            agents = list_agents()
            if agents:
                agent_url = agents[0]["url"]
                agent_name = agents[0]["name"]
            else:
                console.print("[error]No URL specified and no saved agents. Use --url or add an agent.[/error]")
                raise SystemExit(1)
        else:
            agent_url = agent_url.rstrip("/")
            health_info = await client.health(agent_url)
            if health_info:
                if "routes" in health_info:
                    # Gateway detected — use gateway URL with model routing
                    routes = await client.gateway_routes(agent_url)
                    if routes:
                        agent_name = routes[0].get("agent_name", "agent")
                        model = f"agentstack/{agent_name}"
                        console.print(f"[dim]Gateway detected. Using {agent_name}[/dim]")
                    else:
                        console.print("[error]Gateway has no agents[/error]")
                        raise SystemExit(1)
                else:
                    agent_name = health_info.get("agent", "agent")
                    model = ""

        result, _ = await _stream_response(agent_url, message, agent_name, model=model)

        if result.total_tokens:
            console.print(
                f"\n[dim]tokens: {result.input_tokens} in / {result.output_tokens} out[/dim]"
            )

    asyncio.run(_run())
