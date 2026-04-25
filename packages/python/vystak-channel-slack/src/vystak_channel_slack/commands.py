"""Slash command handlers for /vystak in Slack channels."""

from dataclasses import dataclass


@dataclass
class Result:
    """User-facing reply for a slash command."""

    message: str


class NotAuthorized(Exception):
    """Raised when the caller is not allowed to mutate routing config."""


def handle_command(
    *,
    cmd: str,
    args: str,
    team: str,
    channel: str,
    user: str,
    agents: list[str],
    route_authority: str,
    store,
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
        _check_authority("route", user, team, channel, route_authority, store)
        return _route(team, channel, user, rest, agents, store)
    if sub == "unroute":
        _check_authority("unroute", user, team, channel, route_authority, store)
        return _unroute(team, channel, store)
    if sub == "prefer":
        return _prefer(team, user, rest, agents, store)
    if sub == "unprefer":
        return _unprefer(team, user, store)
    if sub == "status":
        return _status(team, channel, user, store)
    return Result(message=_help_text(agents))


def _check_authority(verb, user, team, channel, authority, store):
    if authority == "anyone":
        return
    if authority == "inviter":
        inv = store.inviter(team, channel)
        if inv is None or user != inv:
            raise NotAuthorized(
                f"Only the user who invited the bot can /vystak {verb} in this channel."
            )
        return
    if authority == "admins":
        # TODO: query Slack API for admin status. For now, default to deny —
        # safer than silently allowing.
        inv = store.inviter(team, channel)
        if inv is None or user != inv:
            raise NotAuthorized(
                f"Only workspace admins can /vystak {verb} in this channel."
            )
        return
    raise NotAuthorized(f"unknown route_authority={authority!r}")


def _route(team, channel, user, agent_arg, agents, store):
    if not agent_arg:
        return Result(message="Usage: /vystak route <agent>")
    if agent_arg not in agents:
        return Result(
            message=(
                f"Unknown agent '{agent_arg}'. "
                f"Available: {', '.join(agents)}"
            )
        )
    store.set_channel_binding(team, channel, agent_arg, user)
    return Result(message=f"Channel routed to '{agent_arg}'.")


def _unroute(team, channel, store):
    store.unbind_channel(team, channel)
    return Result(message="Channel unrouted.")


def _prefer(team, user, agent_arg, agents, store):
    if not agent_arg:
        return Result(message="Usage: /vystak prefer <agent>")
    if agent_arg not in agents:
        return Result(
            message=(
                f"Unknown agent '{agent_arg}'. "
                f"Available: {', '.join(agents)}"
            )
        )
    store.set_user_pref(team, user, agent_arg)
    return Result(message=f"Your preferred agent is now '{agent_arg}'.")


def _unprefer(team, user, store):
    store.unset_user_pref(team, user)
    return Result(message="Your preference cleared.")


def _status(team, channel, user, store):
    binding = store.channel_binding(team, channel)
    pref = store.user_pref(team, user)
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
