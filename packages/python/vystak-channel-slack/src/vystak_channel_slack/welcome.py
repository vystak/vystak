"""Welcome message + bot-invite handler."""


def render_welcome(*, template: str, agents: list[str]) -> str:
    """Substitute {agent_mentions} with backtick-quoted agent names."""
    agent_mentions = ", ".join(f"`{a}`" for a in agents)
    return template.replace("{agent_mentions}", agent_mentions)


def on_member_joined(
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
    store,
) -> None:
    """Handle a member_joined_channel event.

    No-ops when the joined user is not the bot. When the bot is the joined
    user: record the inviter, post welcome, and (if exactly one agent is
    routable) auto-bind the channel to it so the user doesn't have to run
    /vystak route for the trivial case.
    """
    if joined_user_id != bot_user_id:
        return

    if inviter_id is not None:
        store.record_inviter(team, channel, inviter_id)

    text = render_welcome(template=welcome_template, agents=agents)
    slack.chat_postMessage(channel=channel, text=text)

    if single_agent_auto_bind and len(agents) == 1:
        store.set_channel_binding(team, channel, agents[0], inviter_id)
