"""Pure routing resolver — no Bolt, no I/O."""

from dataclasses import dataclass


@dataclass
class Event:
    team: str
    channel: str
    user: str
    text: str
    is_dm: bool
    is_bot: bool
    channel_name: str


@dataclass
class ResolverConfig:
    agents: list[str]
    group_policy: str
    dm_policy: str
    allow_from: list[str]
    allow_bots: bool
    channel_overrides: dict
    default_agent: str | None
    ai_fallback: object | None


def resolve(event: Event, cfg: ResolverConfig, store) -> str | None:
    if event.is_bot and not cfg.allow_bots:
        return None
    policy = cfg.dm_policy if event.is_dm else cfg.group_policy
    if policy == "disabled":
        return None
    if policy == "allowlist" and event.user not in cfg.allow_from:
        return None

    if event.is_dm:
        # Resolution order for DMs:
        # 1. user preference set via `/vystak prefer <agent>`
        # 2. configured default_agent
        # 3. single-agent auto-bind — when there's exactly one declared
        #    routable agent, it's unambiguous; mirrors the channel-side
        #    auto-bind behavior in welcome.on_member_joined.
        return (
            store.user_pref(event.team, event.user)
            or cfg.default_agent
            or (cfg.agents[0] if len(cfg.agents) == 1 else None)
        )

    ov = cfg.channel_overrides.get(event.channel)
    if ov is not None and ov.agent:
        return ov.agent
    binding = store.channel_binding(event.team, event.channel)
    if binding:
        return binding
    if cfg.ai_fallback is not None:
        return cfg.ai_fallback.pick(event, cfg.agents)
    # Channel-side single-agent auto-bind — same rationale as DM path.
    if cfg.default_agent is None and len(cfg.agents) == 1:
        return cfg.agents[0]
    return cfg.default_agent
