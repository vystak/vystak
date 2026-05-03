"""Welcome message + bot-invite handler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vystak_channel_runtime.store import ChannelStore

    from vystak_channel_slack.inviters import InviterStore


def render_welcome(*, template: str, agents: list[str]) -> str:
    """Substitute {agent_mentions} with backtick-quoted agent names."""
    agent_mentions = ", ".join(f"`{a}`" for a in agents)
    return template.replace("{agent_mentions}", agent_mentions)


async def on_member_joined(
    *,
    bot_user_id: str,
    joined_user_id: str,
    inviter_id: str | None,
    team: str,
    channel: str,
    agents: list[str],
    single_agent_auto_bind: bool,
    welcome_template: str,
    slack,
    store: ChannelStore,
    inviters: InviterStore,
) -> None:
    """Handle a member_joined_channel event.

    No-ops when the joined user is not the bot. When the bot is the joined
    user: record the inviter, post welcome, and (if exactly one agent is
    routable) auto-bind the channel to it so the user doesn't have to run
    /vystak route for the trivial case.

    ``slack`` must be an object with an async-compatible ``chat_postMessage``
    coroutine (e.g. slack-bolt's ``AsyncWebClient``).
    """
    if joined_user_id != bot_user_id:
        return

    if inviter_id is not None:
        await inviters.record_inviter(team, channel, inviter_id)

    text = render_welcome(template=welcome_template, agents=agents)
    await slack.chat_postMessage(channel=channel, text=text)

    if single_agent_auto_bind and len(agents) == 1:
        await store.set_thread_binding("slack", team, f"{channel}:", agents[0])


def register(
    app: Any,
    config: dict,
    store: ChannelStore,
    inviters: InviterStore,
) -> None:
    """Wire the member_joined_channel bolt event handler into *app*."""
    agents: list[str] = config.get("agents", [])
    _default_tmpl = "Hello! I can route your messages to: {agent_mentions}"
    welcome_template: str = config.get("welcome_message") or _default_tmpl
    single_agent_auto_bind: bool = len(agents) == 1

    @app.event("member_joined_channel")
    async def _on_member_joined(event, client):  # noqa: ARG001
        await on_member_joined(
            bot_user_id=getattr(app, "_bot_user_id", ""),
            joined_user_id=event.get("user", ""),
            inviter_id=event.get("inviter"),
            team=event.get("team", ""),
            channel=event.get("channel", ""),
            agents=agents,
            single_agent_auto_bind=single_agent_auto_bind,
            welcome_template=welcome_template,
            slack=client,
            store=store,
            inviters=inviters,
        )
