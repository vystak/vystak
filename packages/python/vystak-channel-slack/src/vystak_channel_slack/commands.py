"""Slash command handlers for /vystak in Slack channels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vystak_channel_runtime.store import ChannelStore

    from vystak_channel_slack.inviters import InviterStore


@dataclass
class Result:
    """User-facing reply for a slash command."""

    message: str


class NotAuthorized(Exception):
    """Raised when the caller is not allowed to mutate routing config."""


async def handle_command(
    *,
    cmd: str,
    args: str,
    team: str,
    channel: str,
    user: str,
    agents: list[str],
    route_authority: str,
    store: ChannelStore,
    inviters: InviterStore,
) -> Result:
    """Dispatch a /vystak slash command.

    `cmd` is the slash command literal (`/vystak`); `args` is the remainder
    of the message. Returns a Result with a user-facing message. Raises
    NotAuthorized when the caller is not permitted to perform the action.
    """
    parts = (args or "").strip().split(maxsplit=1)
    if not parts:
        return Result(message=_help_text(agents))
    sub = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if sub == "route":
        await _check_authority("route", user, team, channel, route_authority, inviters)
        return await _route(team, channel, user, rest, agents, store)
    if sub == "unroute":
        await _check_authority("unroute", user, team, channel, route_authority, inviters)
        return await _unroute(team, channel, store)
    if sub == "prefer":
        return await _prefer(team, user, rest, agents, store)
    if sub == "unprefer":
        return await _unprefer(team, user, store)
    if sub == "status":
        return await _status(team, channel, user, store)
    return Result(message=_help_text(agents))


async def _check_authority(verb, user, team, channel, authority, inviters: InviterStore):
    if authority == "anyone":
        return
    if authority == "inviter":
        inv = await inviters.get_inviter(team, channel)
        if inv is None or user != inv:
            raise NotAuthorized(
                f"Only the user who invited the bot can /vystak {verb} in this channel."
            )
        return
    if authority == "admins":
        # TODO: query Slack API for admin status. For now, default to deny —
        # safer than silently allowing.
        inv = await inviters.get_inviter(team, channel)
        if inv is None or user != inv:
            raise NotAuthorized(
                f"Only workspace admins can /vystak {verb} in this channel."
            )
        return
    raise NotAuthorized(f"unknown route_authority={authority!r}")


async def _route(team, channel, user, agent_arg, agents, store: ChannelStore):
    if not agent_arg:
        return Result(message="Usage: /vystak route <agent>")
    if agent_arg not in agents:
        return Result(
            message=(
                f"Unknown agent '{agent_arg}'. "
                f"Available: {', '.join(agents)}"
            )
        )
    await store.set_thread_binding("slack", team, f"{channel}:", agent_arg, user)
    return Result(message=f"Channel routed to '{agent_arg}'.")


async def _unroute(team, channel, store: ChannelStore):
    await store.delete_thread_binding("slack", team, f"{channel}:")
    return Result(message="Channel unrouted.")


async def _prefer(team, user, agent_arg, agents, store: ChannelStore):
    if not agent_arg:
        return Result(message="Usage: /vystak prefer <agent>")
    if agent_arg not in agents:
        return Result(
            message=(
                f"Unknown agent '{agent_arg}'. "
                f"Available: {', '.join(agents)}"
            )
        )
    await store.set_route_pref("slack", f"{team}:{user}", agent_arg)
    return Result(message=f"Your preferred agent is now '{agent_arg}'.")


async def _unprefer(team, user, store: ChannelStore):
    await store.delete_route_pref("slack", f"{team}:{user}")
    return Result(message="Your preference cleared.")


async def _status(team, channel, user, store: ChannelStore):
    binding = await store.get_thread_binding("slack", team, f"{channel}:")
    pref = await store.get_route_pref("slack", f"{team}:{user}")
    parts = []
    if binding:
        parts.append(f"Channel routed to: {binding}")
    else:
        parts.append("Channel not pinned (using default fallback).")
    if pref:
        parts.append(f"Your DM preference: {pref}")
    return Result(message="\n".join(parts))


def _help_text(agents: list[str]) -> str:
    return (
        "Usage:\n"
        "  /vystak route <agent>     — pin this channel to an agent\n"
        "  /vystak unroute           — clear channel pin\n"
        "  /vystak prefer <agent>    — set your DM default\n"
        "  /vystak unprefer          — clear DM default\n"
        "  /vystak status            — show current routing\n"
        f"\nAvailable agents: {', '.join(agents)}"
    )


def register(
    app: Any,
    config: dict,
    store: ChannelStore,
    inviters: InviterStore,
) -> None:
    """Wire the /vystak slash command handler into *app*."""
    agents: list[str] = config.get("agents", [])
    route_authority: str = config.get("route_authority", "inviter")

    @app.command("/vystak")
    async def _on_slash_command(ack, body, client):
        await ack()
        team = body.get("team_id", "")
        channel = body.get("channel_id", "")
        user = body.get("user_id", "")
        text = body.get("text", "")
        cmd = body.get("command", "/vystak")
        try:
            result = await handle_command(
                cmd=cmd,
                args=text,
                team=team,
                channel=channel,
                user=user,
                agents=agents,
                route_authority=route_authority,
                store=store,
                inviters=inviters,
            )
            await client.chat_postEphemeral(channel=channel, user=user, text=result.message)
        except NotAuthorized as exc:
            await client.chat_postEphemeral(channel=channel, user=user, text=str(exc))
