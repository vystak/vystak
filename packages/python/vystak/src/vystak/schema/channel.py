"""Channel model — top-level deployable I/O adapter for agent communication."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, model_validator

from vystak.schema.agent import Agent
from vystak.schema.common import ChannelType, NamedModel, RuntimeMode
from vystak.schema.platform import Platform
from vystak.schema.secret import Secret
from vystak.schema.service import Service, Sqlite

# Re-export ChannelType so callers can do `from vystak.schema.channel import ChannelType`
__all__ = [
    "Channel",
    "ChannelType",
    "Policy",
    "SlackChannelOverride",
    "SlackThreadConfig",
]


class Policy(StrEnum):
    """Access policy for a Slack channel gate."""

    OPEN = "open"
    ALLOWLIST = "allowlist"
    DISABLED = "disabled"


class SlackThreadConfig(BaseModel):
    """Per-channel thread behaviour. Mirrors openclaw's ``channels.slack.thread.*``.

    See: https://docs.openclaw.ai/channels/slack
    """

    history_scope: str = "thread"   # "thread" | "off" — what context to fetch
    initial_history_limit: int = 20  # 0 disables fetching on cold-start
    inherit_parent: bool = False     # carry parent-channel session into thread
    require_explicit_mention: bool = False  # suppress implicit thread mentions


class SlackChannelOverride(NamedModel):
    """Per Slack-channel configuration override pinned to a specific agent."""

    name: str = ""
    agent: Agent | None = None
    require_mention: bool = False
    users: list[str] = []
    system_prompt: str | None = None
    tools: list[str] | None = None
    skills: list[str] | None = None


class Channel(NamedModel):
    """A top-level channel deployable — sibling of Agent.

    Channels own their own platform, runtime, and routing policy.  Agents do
    not declare channels; channels declare which agents they route to.

    The legacy ``routes`` field (deploy-time RouteRule list) has been removed.
    Use ``agents`` + ``channel_overrides`` for self-serve routing instead.
    """

    type: ChannelType
    platform: Platform
    config: dict = {}
    runtime_mode: RuntimeMode | None = None
    secrets: list[Secret] = []

    # Self-serve routing fields
    agents: list[Agent] = []
    group_policy: Policy = Policy.OPEN
    dm_policy: Policy = Policy.OPEN
    allow_from: list[str] = []
    allow_bots: bool = False
    dangerously_allow_name_matching: bool = False
    reply_to_mode: str = "first"
    reply_to_mode_by_chat_type: dict[str, str] = {}   # "direct"|"group"|"channel" -> mode
    thread: SlackThreadConfig = SlackThreadConfig()
    # Legacy alias kept so existing callers don't break; new code should use
    # `thread.require_explicit_mention`.
    thread_require_explicit_mention: bool = False
    channel_overrides: dict[str, SlackChannelOverride] = {}
    state: Service | None = None
    route_authority: str = "inviter"
    default_agent: Agent | None = None
    ai_fallback: dict | None = None
    welcome_on_invite: bool = True
    welcome_message: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_routes(cls, values: dict) -> dict:
        if isinstance(values, dict) and "routes" in values:
            raise ValueError(
                "routes is deprecated — use agents + channel_overrides for self-serve routing. "
                "See docs/superpowers/specs/2026-04-24-slack-self-serve-routing-design.md"
            )
        return values

    @model_validator(mode="after")
    def _apply_state_default(self) -> Self:
        if self.type is ChannelType.SLACK and self.state is None:
            self.state = Sqlite(
                name=f"{self.name}-state",
                path="/data/channel-state.db",
            )
        return self

    @model_validator(mode="after")
    def _apply_single_agent_default(self) -> Self:
        """When a Slack channel declares exactly one routable agent and no
        explicit default_agent, fall back to that single agent. Without this,
        DMs would resolve to None even though there's an obvious choice."""
        if (
            self.type is ChannelType.SLACK
            and self.default_agent is None
            and len(self.agents) == 1
        ):
            self.default_agent = self.agents[0]
        return self

    @model_validator(mode="after")
    def _validate_default_agent(self) -> Self:
        if self.default_agent is not None and self.default_agent not in self.agents:
            raise ValueError("default_agent must be in agents list")
        return self

    @property
    def canonical_name(self) -> str:
        return f"{self.name}.channels.{self.platform.namespace}"
